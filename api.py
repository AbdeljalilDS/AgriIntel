"""API FastAPI — expose les deux agents via HTTP. Les études tournent en
tâche de fond asynchrone sans bloquer l'Event Loop principal.
Lancer : uvicorn api:app --reload | Doc interactive : /docs
"""
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from agent_benchmark.agent import BenchmarkAgent
from agent_benchmark.prompts import PROMPT_CHAT_SYSTEME
from agent_benchmark.report_generator import formater_entites, generer_rapport
from agent_startup.agent import StartupAgent
from agent_startup.report_generator import generer_rapport_startup
from config.settings import settings
from core.exports import exporter_excel, exporter_pdf
from core.analytics import calculer_statistiques, formater_statistiques
from core.llm_client import get_llm_client
from core.logger import get_logger
from core.models import EntiteAnalysee
from core.verification import verifier_reponse
from core.storage import JSONStorage
from core.cache import cle_reponse, enregistrer_reponse, lire_reponse
from core.jobs import job_store

logger = get_logger(__name__)
app = FastAPI(title="Benchmark Intelligence API", version="2.1")

_cors_origins = settings.cors_origins_liste()
if settings.app_env == "production" and not _cors_origins:
    logger.warning("APP_ENV=production sans CORS_ORIGINS — accès frontend bloqué par le navigateur")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if settings.app_env == "production" else (_cors_origins or ["*"]),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def verifier_cle_api(request: Request, call_next):
    chemins_libres = ("/api/health", "/", "/docs", "/openapi.json", "/redoc")
    if settings.api_key and request.url.path.startswith("/api/") and request.url.path not in chemins_libres:
        if request.headers.get("x-api-key") != settings.api_key:
            return Response(status_code=401, content="Clé API manquante ou invalide (header X-API-Key).")
    return await call_next(request)

@app.on_event("startup")
async def _demarrage_api():
    await job_store.reprendre_jobs_interrompus()

def _mots(texte: str) -> set[str]:
    return {mot.lower() for mot in re.findall(r"[\wÀ-ÿ]+", texte) if len(mot) > 3}

def _contexte_documents(question: str, documents: list[dict]) -> tuple[str, list[dict]]:
    mots_question = _mots(question)
    blocs = []
    citations = []
    for document in documents[:5]:
        nom = str(document.get("nom") or "document utilisateur")
        texte = str(document.get("texte") or "")[:12000]
        paragraphes = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-ZÀ-Ý])", texte) if p.strip()]
        candidats = []
        for index, paragraphe in enumerate(paragraphes):
            score = len(mots_question & _mots(paragraphe))
            candidats.append((score, index, paragraphe))
        selection = sorted(candidats, key=lambda item: (item[0], -item[1]), reverse=True)[:4]
        if not selection:
            continue
        for _, index, paragraphe in selection:
            blocs.append(f"### {nom} · passage {index + 1}\n{paragraphe[:3500]}")
            citations.append({"source": f"document://{nom}", "date": None, "confiance": 0.8, "entite": nom, "donnee": paragraphe[:500]})
    return "\n\n".join(blocs) or "(aucun passage documentaire pertinent)", citations

def _contexte_chat(question: str, entites: list[EntiteAnalysee]) -> tuple[str, str]:
    question_min = question.lower()
    cible = next((e.nom for e in entites if e.nom.lower() in question_min), "Les Domaines Agricoles")
    cible_mots = _mots(cible)
    question_mots = _mots(question)
    candidats = []
    for entite in entites:
        if entite.nom.lower() == cible.lower():
            continue
        texte = " ".join(filter(None, [entite.nom, entite.secteur or "", entite.description or "", " ".join(entite.produits_services or [])]))
        score = len(question_mots & _mots(texte))
        if entite.secteur and cible_mots & _mots(entite.secteur):
            score += 2
        candidats.append((score, entite))
    candidats.sort(key=lambda item: (item[0], item[1].score_pertinence or 0), reverse=True)
    selection = [entite for _, entite in candidats[:8]]
    return cible, formater_entites(selection)

def _contexte_insuffisant(question: str, entites: list[EntiteAnalysee]) -> bool:
    if not entites:
        return True
    cible = next((entite for entite in entites if entite.nom.lower() in question.lower()), None)
    if cible is None:
        return True
    cible_mots = _mots(" ".join(filter(None, [cible.nom, cible.secteur, cible.description])))
    candidats = []
    for entite in entites:
        if entite.nom == cible.nom:
            continue
        texte = " ".join(filter(None, [entite.nom, entite.secteur, entite.description]))
        if cible_mots.intersection(_mots(texte)):
            candidats.append(entite)
    return len(candidats) < 3

def _question_synthese(question: str) -> bool:
    termes = _mots(question)
    return bool(termes & {
        "rapport", "exécutif", "executif", "statistiques", "statistique",
        "conclusions", "sources", "limites", "synthèse", "synthese",
        "résumé", "resume", "analyse", "comparaison", "compare",
    })

def _question_recherche_live(question: str) -> bool:
    return bool(_mots(question) & {
        "recherche", "rechercher", "actualise", "actualiser", "récent", "recente",
        "récentes", "recentes", "web", "internet", "collecte", "nouvelles",
        "nouveaux", "nouvelle", "aujourd'hui", "aujourd’hui",
    })

@app.get("/")
def racine():
    return {"message": "API opérationnelle — documentation sur /docs"}

class LancerEtudeRequest(BaseModel):
    cible: str
    mode: str = "standard"

class JobStatus(BaseModel):
    job_id: str
    statut: str
    etape: Optional[str] = None
    resultat: Optional[dict] = None
    erreur: Optional[str] = None

class ChatRequest(BaseModel):
    question: str
    historique: list[list[str]] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)

async def _sauvegarder(job_id: str, cible: str, prefixe: str, entites: list[EntiteAnalysee], rapport: str) -> None:
    storage = JSONStorage()
    nom_fichier = f"{prefixe}_{cible.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}"
    await asyncio.to_thread(storage.save, entites, nom_fichier)
    chemin = Path(settings.output_dir) / f"{nom_fichier}_rapport.md"
    await asyncio.to_thread(chemin.write_text, rapport, encoding="utf-8")
    await job_store.mettre_a_jour(
        job_id,
        statut="termine",
        etape="Terminé",
        resultat={
            "nb_entites": len(entites),
            "entites": [json.loads(e.model_dump_json()) for e in entites],
            "rapport": rapport,
            "fichier": nom_fichier,
        },
    )

async def _executer_benchmark(job_id: str, cible: str, mode: str = "standard") -> None:
    try:
        llm = get_llm_client()
        await job_store.mettre_a_jour(job_id, etape="L'agent recherche et analyse (mémoire, web, lecture de pages)...")
        agent = BenchmarkAgent(llm, mode=mode)
        entites = await agent.run(cible)
        await job_store.mettre_a_jour(job_id, etape="Rédaction du rapport...")
        # Si generer_rapport est asynchrone, await-le. Sinon to_thread.
        if asyncio.iscoroutinefunction(generer_rapport):
            rapport = await generer_rapport(llm, cible, entites)
        else:
            rapport = await asyncio.to_thread(generer_rapport, llm, cible, entites)
        await _sauvegarder(job_id, cible, "benchmark", entites, rapport)
    except Exception as exc:
        logger.warning(f"Job {job_id} (benchmark) échoué : {exc}")
        await job_store.mettre_a_jour(job_id, statut="erreur", erreur=str(exc))

async def _executer_startup(job_id: str, cible: str, mode: str = "standard") -> None:
    try:
        llm = get_llm_client()
        await job_store.mettre_a_jour(
            job_id,
            etape="L'agent recherche et analyse les startups (mémoire, web, lecture de pages)...",
        )
        agent = StartupAgent(llm, mode=mode)
        entites = await agent.run(cible)
        await job_store.mettre_a_jour(job_id, etape="Rédaction du rapport...")
        if asyncio.iscoroutinefunction(generer_rapport_startup):
            rapport = await generer_rapport_startup(llm, cible, entites)
        else:
            rapport = await asyncio.to_thread(generer_rapport_startup, llm, cible, entites)
        await _sauvegarder(job_id, cible, "startups", entites, rapport)
    except Exception as exc:
        logger.warning(f"Job {job_id} (startup) échoué : {exc}")
        await job_store.mettre_a_jour(job_id, statut="erreur", erreur=str(exc))

async def _charger_toutes_entites() -> list[EntiteAnalysee]:
    def _charger():
        entites_par_cle = {}
        dossier = Path(settings.output_dir)
        if not dossier.exists():
            return []
        for fichier in dossier.glob("*.json"):
            try:
                data = json.loads(fichier.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for item in data:
                try:
                    e = EntiteAnalysee.model_validate(item)
                except Exception:
                    continue
                entites_par_cle[e.cle_normalisee()] = e
        return list(entites_par_cle.values())
    return await asyncio.to_thread(_charger)

@app.post("/api/benchmark/lancer", response_model=JobStatus)
async def lancer_benchmark(requete: LancerEtudeRequest, background_tasks: BackgroundTasks):
    mode = requete.mode if requete.mode in {"standard", "large"} else "standard"
    job_id = await job_store.creer("benchmark", requete.cible, mode)
    background_tasks.add_task(_executer_benchmark, job_id, requete.cible, mode)
    return JobStatus(job_id=job_id, statut="en_cours", etape="Initialisation...")

@app.post("/api/startup/lancer", response_model=JobStatus)
async def lancer_startup(requete: LancerEtudeRequest, background_tasks: BackgroundTasks):
    mode = requete.mode if requete.mode in {"standard", "large"} else "standard"
    job_id = await job_store.creer("startup", requete.cible, mode)
    background_tasks.add_task(_executer_startup, job_id, requete.cible, mode)
    return JobStatus(job_id=job_id, statut="en_cours", etape="Initialisation...")

@app.get("/api/jobs")
async def liste_jobs():
    return await job_store.lister_recents()

@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def statut_job(job_id: str):
    job = await job_store.lire(job_id)
    if not job:
        raise HTTPException(404, "Job introuvable")
    return JobStatus(
        job_id=job_id,
        statut=job["statut"],
        etape=job.get("etape"),
        resultat=job.get("resultat"),
        erreur=job.get("erreur"),
    )

@app.get("/api/entites")
async def toutes_les_entites():
    entites = await _charger_toutes_entites()
    return [json.loads(e.model_dump_json()) for e in entites]

@app.get("/api/rapports")
async def liste_rapports():
    def _lister():
        dossier = Path(settings.output_dir)
        return sorted([f.name for f in dossier.glob("*_rapport.md")], reverse=True) if dossier.exists() else []
    return await asyncio.to_thread(_lister)

@app.get("/api/rapports/{nom}/markdown")
async def telecharger_markdown(nom: str):
    chemin = Path(settings.output_dir) / nom
    if not await asyncio.to_thread(chemin.exists):
        raise HTTPException(404, "Rapport introuvable")
    return FileResponse(chemin, media_type="text/markdown", filename=nom)

@app.get("/api/rapports/{nom}/excel")
async def telecharger_excel(nom: str):
    chemin_json = Path(settings.output_dir) / nom.replace("_rapport.md", ".json")
    if not await asyncio.to_thread(chemin_json.exists):
        raise HTTPException(404, "Données introuvables")
    def _exporter():
        entites = [EntiteAnalysee.model_validate(i) for i in json.loads(chemin_json.read_text(encoding="utf-8"))]
        return exporter_excel(entites)
    content = await asyncio.to_thread(_exporter)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={nom.replace('_rapport.md', '.xlsx')}"},
    )

@app.get("/api/rapports/{nom}/pdf")
async def telecharger_pdf(nom: str):
    chemin_md = Path(settings.output_dir) / nom
    if not await asyncio.to_thread(chemin_md.exists):
        raise HTTPException(404, "Rapport introuvable")
    def _exporter():
        contenu_md = chemin_md.read_text(encoding="utf-8")
        chemin_json = Path(settings.output_dir) / nom.replace("_rapport.md", ".json")
        entites = [EntiteAnalysee.model_validate(i) for i in json.loads(chemin_json.read_text(encoding="utf-8"))] if chemin_json.exists() else []
        return exporter_pdf(nom.replace("_rapport.md", ""), entites, contenu_md)
    content = await asyncio.to_thread(_exporter)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nom.replace('_rapport.md', '.pdf')}"},
    )

@app.post("/api/chat")
async def chat(requete: ChatRequest):
    debut = time.perf_counter()
    entites = await _charger_toutes_entites()
    cache_key = cle_reponse(requete.question, requete.historique, [document.get("nom", "") for document in requete.documents], len(entites))
    reponse_cachee = lire_reponse(cache_key)
    if reponse_cachee:
        reponse_cachee["cache"] = True
        return reponse_cachee
    recherche_live = settings.chat_recherche_live and _question_recherche_live(requete.question) and not _question_synthese(requete.question)
    if recherche_live and _contexte_insuffisant(requete.question, entites):
        cible_detectee = next(
            (entite.nom for entite in entites if entite.nom.lower() in requete.question.lower()),
            "Les Domaines Agricoles",
        )
        try:
            logger.info(f"Contexte insuffisant : lancement d'une recherche live pour '{cible_detectee}'")
            nouvelles_entites = await BenchmarkAgent(get_llm_client()).run(cible_detectee)
            entites = await _charger_toutes_entites() or nouvelles_entites
        except Exception as exc:
            logger.warning(f"Recherche live du chat indisponible : {exc}")
    cible, donnees = _contexte_chat(requete.question, entites)
    statistiques = calculer_statistiques(entites)
    system_prompt = PROMPT_CHAT_SYSTEME.format(cible=cible, donnees=donnees)
    historique_texte = "\n\n".join(f"Q: {q}\nR: {r}" for q, r in requete.historique[-5:])
    documents, citations_documents = _contexte_documents(requete.question, requete.documents)
    statistiques["documents_fournis"] = len(requete.documents[:5])
    statistiques["passages_documentaires"] = len(citations_documents)
    prompt_complet = f"{system_prompt}\n\nStatistiques calculées par le système (ne pas modifier) :\n{formater_statistiques(statistiques)}\n\nDocuments fournis par l'utilisateur, priorité pour cette question :\n{documents}\n\nHistorique récent:\n{historique_texte}\n\nNouvelle question: {requete.question}"
    llm = get_llm_client()
    reponse = await llm.generate(prompt_complet)
    verification = await asyncio.to_thread(verifier_reponse, requete.question, reponse, entites, citations_documents)
    resultat = {"reponse": reponse, "statistiques": statistiques, **verification, "cache": False}
    enregistrer_reponse(cache_key, resultat)
    try:
        def _log():
            chemin_audit = Path(settings.audit_log_path)
            chemin_audit.parent.mkdir(parents=True, exist_ok=True)
            with chemin_audit.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps({
                    "date": datetime.now().isoformat(),
                    "question": requete.question[:300],
                    "documents": [document.get("nom") for document in requete.documents[:5]],
                    "nb_entites": len(entites),
                    "nb_citations": len(resultat.get("citations", [])),
                    "confiance": resultat.get("confiance"),
                    "duree_secondes": round(time.perf_counter() - debut, 2),
                    "cache": False,
                }, ensure_ascii=False) + "\n")
        await asyncio.to_thread(_log)
    except OSError as exc:
        logger.warning(f"Audit indisponible : {exc}")
    return resultat

@app.get("/api/health")
async def health():
    entites = await _charger_toutes_entites()
    jobs = await job_store.lister_en_cours()
    return {
        "status": "ok",
        "entites_en_base": len(entites),
        "modele": settings.ollama_model,
        "app_env": settings.app_env,
        "fast_mode": settings.fast_mode,
        "jobs_en_cours": len(jobs),
    }