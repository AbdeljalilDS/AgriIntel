"""
Outils de l'agent benchmark — tool-calling asynchrone enterprise.

Améliorations vs version précédente :
- outil_rechercher_web utilise le nouveau SearchEngine multi-provider
- outil_lire_page limite et résume le contenu si trop long
- outil_enregistrer_entreprise enrichi avec coverage scoring
- session isolée par ContextVar (thread-safe, multi-user)
- url_scrapable importé depuis scraper_base
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from config.settings import settings
from core import memoire
from core.logger import get_logger
from core.models import EntiteAnalysee, _est_valeur_vide
from core.scraper_base import fetch_clean_text, url_scrapable
from core.storage import JSONStorage

logger = get_logger(__name__)

# ContextVar pour isoler l'état par session async
_session_var: contextvars.ContextVar["EtatSession"] = contextvars.ContextVar("_etat_session_benchmark")


class EtatSession:
    def __init__(self):
        self.derniers_textes_lus:    dict[str, str] = {}
        self.embeddings_session:     dict[str, list[float] | None] = {}
        self.derniere_url_lue:       str | None = None
        self.urls_indexees:          dict[int, str] = {}
        self.url_vers_index:         dict[str, int] = {}
        self.entreprises_enregistrees: set[str] = set()


def get_session() -> EtatSession:
    try:
        return _session_var.get()
    except LookupError:
        sess = EtatSession()
        _session_var.set(sess)
        return sess


def reinitialiser_session() -> None:
    _session_var.set(EtatSession())


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _canoniser_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?(previous\s+)?instructions|system\s+prompt|disregard\s+all|override\s+instructions|system:\s*you\s+are)",
    re.IGNORECASE
)


def _sanitiser_texte_web(texte: str) -> str:
    """Nettoie le texte scrapé pour empêcher les attaques par Prompt Injection."""
    if not texte:
        return ""
    return _INJECTION_PATTERNS.sub("[instruction ignorée]", texte)


def _domaine(url: str) -> str:
    return urlsplit(url).netloc.lower().replace("www.", "")


def _indexer_url(url: str) -> int:
    session = get_session()
    cle = _canoniser_url(url)
    if cle in session.url_vers_index:
        return session.url_vers_index[cle]
    index = len(session.urls_indexees) + 1
    session.urls_indexees[index] = url
    session.url_vers_index[cle] = index
    return index


async def _embedding_cache(llm, texte: str, limite: int = 5000) -> list[float] | None:
    session = get_session()
    texte_normalise = texte[:limite].strip()
    if not texte_normalise:
        return None
    cle = hashlib.sha256(texte_normalise.encode("utf-8")).hexdigest()
    if cle not in session.embeddings_session:
        if len(session.embeddings_session) >= 128:
            session.embeddings_session.pop(next(iter(session.embeddings_session)))
        try:
            session.embeddings_session[cle] = await llm.embed(texte_normalise)
        except Exception as exc:
            logger.warning(f"Embedding échoué : {exc}")
            session.embeddings_session[cle] = None
    return session.embeddings_session[cle]


def _similarite_cosinus(gauche: list[float] | None, droite: list[float] | None) -> float | None:
    if not gauche or not droite or len(gauche) != len(droite):
        return None
    norme_g = sum(v * v for v in gauche) ** 0.5
    norme_d = sum(v * v for v in droite) ** 0.5
    if not norme_g or not norme_d:
        return None
    return sum(a * b for a, b in zip(gauche, droite)) / (norme_g * norme_d)


def _formater_resultat_recherche(resultats: list, requete: str) -> str:
    """Formate les résultats de recherche pour le LLM."""
    if not resultats:
        return "Aucun résultat trouvé pour cette requête."

    lignes = [
        f"Résultats pour '{requete}' ({len(resultats)} sources trouvées) :\n"
        "Utilise lire_page avec le numéro [n] exact.\n"
    ]
    for r in resultats[:15]:
        url = r.get("url", "")
        if not url or not url_scrapable(url):
            continue
        index = _indexer_url(url)
        titre = r.get("titre") or r.get("title", "")
        extrait = r.get("contenu") or r.get("snippet", "")
        provider = r.get("provider", "")
        score = r.get("score", r.get("authority", 0))
        authority = r.get("authority", 0)
        tier = r.get("tier", 4)
        tier_label = {1: "★★★★★ officiel", 2: "★★★★ institutionnel", 3: "★★★ presse", 4: "★★ web"}.get(tier, "★ web")
        lignes.append(
            f"[{index}] {titre[:80]}\n"
            f"  Source: {tier_label} | Provider: {provider} | Score: {score:.2f}\n"
            f"  Extrait: {extrait[:300]}\n"
        )

    if len(lignes) <= 1:
        return "Aucun résultat exploitable pour cette requête."
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Outil : rechercher_web
# ---------------------------------------------------------------------------

async def outil_rechercher_web(requete: str) -> str:
    if not requete or len(requete.strip()) < 3:
        return "Requête trop courte. Précise ce que tu cherches."

    from agent_benchmark.sources import SearchEngine, etendre_requete
    engine = SearchEngine(sector="agriculture")

    # Requête principale + variantes
    variantes = await etendre_requete(requete)
    all_queries = [requete] + variantes[:settings.max_variantes_recherche - 1]

    # Recherche parallèle sur toutes les variantes
    resultats = await engine.parallel_search(
        all_queries,
        max_results_each=settings.max_results_per_query,
        max_workers=settings.search_parallel_workers,
    )

    # Convertir en dicts pour compatibilité
    dicts = [
        {
            "url": r.url,
            "titre": r.title,
            "contenu": r.snippet,
            "provider": r.provider,
            "score": r.score,
            "authority": r.authority,
            "tier": r.tier,
        }
        for r in resultats
    ]

    return _formater_resultat_recherche(dicts, requete)


# ---------------------------------------------------------------------------
# Outil : lire_page
# ---------------------------------------------------------------------------

async def outil_lire_page(index: int | str) -> str:
    session = get_session()
    url = _resoudre_url(index, session)
    if not url:
        return (
            f"Index invalide : '{index}'. "
            "Utilise uniquement un numéro affiché par rechercher_web."
        )
    if not url_scrapable(url):
        return "Impossible : domaine non autorisé ou URL invalide."

    try:
        texte = await fetch_clean_text(url)
    except Exception as exc:
        return f"Impossible de lire cette page : {exc}"

    if not texte:
        return "Cette page ne contient pas de contenu exploitable."

    # Sanitisation anti-injection
    texte = _sanitiser_texte_web(texte)

    session.derniers_textes_lus[url] = texte
    session.derniere_url_lue = url

    # Limiter la taille (économie de tokens et respect payload Groq)
    contenu = texte[:3500]
    return (
        f"[Source #{index}: {url}]\n"
        f"=== CONTENU ({len(texte):,} caractères) ===\n"
        f"{contenu}"
    )


# ---------------------------------------------------------------------------
# Outil : rechercher_memoire
# ---------------------------------------------------------------------------

async def outil_rechercher_memoire(requete: str, llm) -> str:
    embedding = await _embedding_cache(llm, requete, limite=2000)
    if embedding:
        resultats = await memoire.rechercher_hybride(requete, embedding, top_k=6)
    else:
        resultats = await memoire.rechercher_par_mot_cle(requete, top_k=6)

    preuves = await memoire.rechercher_preuves(requete, embedding, top_k=8)
    if preuves:
        lignes = [
            f"- [{i}] {p['type']}: {p['texte']} | source={p['source']} | "
            f"confiance={p['confiance'] or 'inconnue'}"
            for i, p in enumerate(preuves, 1)
        ]
        return "Preuves trouvées en mémoire (études précédentes) :\n" + "\n".join(lignes)

    if not resultats:
        return "Rien en mémoire pour cette recherche — cherche sur le web."

    lignes = [
        f"- {r.get('nom')} : {r.get('description') or 'pas de description'}"
        for r in resultats
    ]
    return "Connu en mémoire (étude précédente) :\n" + "\n".join(lignes)


# ---------------------------------------------------------------------------
# Outil : enregistrer_entreprise
# ---------------------------------------------------------------------------

async def outil_enregistrer_entreprise(
    donnees: dict, llm
) -> tuple[str, EntiteAnalysee | None]:
    nom_brut = donnees.get("nom")
    if isinstance(nom_brut, list):
        nom_brut = nom_brut[0] if nom_brut else None
    if _est_valeur_vide(nom_brut):
        return "Refusé : nom vide ou invalide.", None

    session = get_session()

    # Injecter la dernière URL lue si source_url absent
    if _est_valeur_vide(donnees.get("source_url")) and session.derniere_url_lue:
        donnees = {**donnees, "source_url": session.derniere_url_lue}

    try:
        entite = EntiteAnalysee.model_validate(donnees)
    except Exception as exc:
        return f"Refusé : données invalides ({exc})", None

    cle = entite.cle_normalisee()

    # Anti-doublon dans la session
    if cle in session.entreprises_enregistrees:
        return (
            f"Refusé : '{entite.nom}' déjà enregistrée dans cette étude. "
            "Passe à une autre entreprise.",
            None,
        )

    # Vérification / assignation de la source
    urls_lues = list(session.derniers_textes_lus.keys())
    domaines_lus = {_domaine(u) for u in urls_lues}
    source_canon = _canoniser_url(entite.source_url) if entite.source_url else ""
    source_ok = (
        any(_canoniser_url(u) == source_canon for u in urls_lues)
        or (_domaine(entite.source_url) in domaines_lus if entite.source_url else False)
    )
    if not source_ok and urls_lues:
        # Assigner la dernière URL lue comme source_url fiable
        if not entite.site_web and entite.source_url and "http" in entite.source_url:
            entite.site_web = entite.source_url
        entite.source_url = session.derniere_url_lue or urls_lues[-1]
        source_ok = True

    # Vérification richesse minimale
    signaux = [
        entite.secteur, entite.description, entite.site_web,
        entite.positionnement, entite.siege_social,
        entite.produits_services, entite.certifications,
        entite.pays_export, entite.technologies, entite.marches_cibles,
    ]
    nb_signaux = sum(
        1 for s in signaux
        if (isinstance(s, list) and len(s) > 0) or (not isinstance(s, list) and not _est_valeur_vide(s))
    )
    if nb_signaux < 1:
        return (
            "Refusé : fiche trop pauvre. Minimum : nom + source_url + "
            "(secteur OU description OU produits_services OU site_web).",
            None,
        )

    # Validation sémantique par embedding (optionnelle — ne bloque pas)
    meilleur_score = 0.0
    texte_entite = " ".join([
        entite.nom,
        entite.secteur or "",
        entite.description or "",
        " ".join(entite.produits_services or []),
    ])
    embedding_entite = await _embedding_cache(llm, texte_entite)
    if embedding_entite and session.derniers_textes_lus:
        scores = []
        for texte in list(session.derniers_textes_lus.values())[:3]:
            emb_page = await _embedding_cache(llm, texte, limite=4000)
            s = _similarite_cosinus(embedding_entite, emb_page)
            if s is not None:
                scores.append(s)
        if scores:
            meilleur_score = max(scores)

    seuil = settings.embedding_validation_threshold
    if meilleur_score > 0 and meilleur_score < seuil:
        logger.warning(
            "Preuve sémantique faible pour '%s' (%.2f) — accepté quand même.",
            entite.nom, meilleur_score
        )

    # Enregistrement
    session.entreprises_enregistrees.add(cle)

    # Sauvegarde JSON locale
    storage = JSONStorage()
    await asyncio.to_thread(storage.save, [entite], f"session_{cle}")

    # Mémoire long terme
    embedding = await _embedding_cache(
        llm,
        f"{entite.nom} {entite.secteur or ''} {entite.description or ''}",
        limite=2000,
    )
    await memoire.enregistrer(cle, entite.nom, entite.model_dump_json(), embedding)

    # Enregistrement des preuves atomiques
    preuves = []
    faits_texte = [("description", entite.description), ("secteur", entite.secteur)]
    faits_texte.extend(("produits_services", p) for p in (entite.produits_services or []))
    for type_fait, valeur in faits_texte:
        if not valeur:
            continue
        texte = f"{entite.nom} — {valeur}"
        preuves.append({
            "type_fait": type_fait,
            "texte": texte,
            "source_url": entite.source_url,
            "date_collecte": entite.date_collecte.isoformat(),
            "confiance": entite.score_pertinence or meilleur_score or None,
            "embedding": await _embedding_cache(llm, texte, limite=2000),
        })
    for champ in ("technologies", "competences", "investissements", "innovations", "innovations_recentes"):
        for fait in getattr(entite, champ, []) or []:
            texte = f"{entite.nom} — {getattr(fait, 'valeur', fait)}"
            preuves.append({
                "type_fait": champ,
                "texte": texte,
                "source_url": getattr(fait, "source_url", None) or entite.source_url,
                "date_collecte": (getattr(fait, "date_collecte", None) or entite.date_collecte).isoformat(),
                "confiance": getattr(fait, "confiance", None),
                "embedding": await _embedding_cache(llm, texte, limite=2000),
            })
    await memoire.enregistrer_preuves(cle, preuves)

    nb_signaux_label = "fiche riche" if nb_signaux >= 4 else "fiche partielle"
    return (
        f"✓ Enregistré ({nb_signaux_label}, {nb_signaux} champs) : {entite.nom} | "
        f"Source: {entite.source_url[:60]} | Score: {meilleur_score:.2f}",
        entite,
    )


# ---------------------------------------------------------------------------
# Définitions des outils pour le LLM
# ---------------------------------------------------------------------------

DEFINITIONS_OUTILS = [
    {
        "type": "function",
        "function": {
            "name": "rechercher_memoire",
            "description": (
                "Consulte la mémoire des études précédentes avant de chercher sur le web. "
                "À utiliser EN PREMIER pour éviter les doublons et réutiliser les données connues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "requete": {"type": "string", "description": "Ce qu'on cherche à retrouver en mémoire"}
                },
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rechercher_web",
            "description": (
                "Recherche sur le web via plusieurs moteurs (Tavily, Google, DuckDuckGo, Bing...). "
                "Retourne une liste numérotée [n] de sources à lire via lire_page. "
                "Utilise des requêtes précises et variées (concurrents, export, certifications, actualités...)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "requete": {
                        "type": "string",
                        "description": "Requête de recherche précise. Ex: 'exportateurs tomates Maroc certifications GlobalGAP'",
                    }
                },
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lire_page",
            "description": (
                "Lit le contenu complet d'une page web à partir de son numéro [n] "
                "affiché par rechercher_web. Supporte HTML, JavaScript (Playwright), PDF. "
                "N'accepte que des numéros entiers, jamais des URLs directes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "Le numéro [n] du résultat à lire (entier)."}
                },
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enregistrer_entreprise",
            "description": (
                "Enregistre une entreprise identifiée dans l'étude. "
                "Minimum requis : nom + source_url + au moins 1 champ (secteur, description, produits, site_web). "
                "Enregistre vite avec les informations disponibles — tu pourras enrichir plus tard. "
                "Ne jamais inventer un champ absent de la source lue."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nom":             {"type": "string", "description": "Nom officiel de l'entreprise"},
                    "secteur":         {"type": "string", "description": "Secteur d'activité principal"},
                    "description":     {"type": "string", "description": "Description de l'activité (2-4 phrases)"},
                    "site_web":        {"type": "string", "description": "URL du site officiel"},
                    "annee_creation":  {"type": "string"},
                    "siege_social":    {"type": "string", "description": "Ville et pays"},
                    "effectif":        {"type": "string", "description": "Nombre d'employés si mentionné"},
                    "chiffre_affaires":{"type": "string", "description": "CA si mentionné"},
                    "produits_services":{"type": "array", "items": {"type": "string"}},
                    "positionnement":  {"type": "string", "description": "premium, low-cost, innovation..."},
                    "technologies":    {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "valeur":      {"type": "string"},
                                "source_url":  {"type": "string"},
                                "confiance":   {"type": "number"},
                            },
                        },
                    },
                    "certifications":  {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "ISO 9001, GlobalGAP, Bio, HACCP, BRC, IFS...",
                    },
                    "pays_export":    {"type": "array", "items": {"type": "string"}},
                    "marches_cibles": {"type": "array", "items": {"type": "string"}},
                    "partenaires":    {"type": "array", "items": {"type": "string"}},
                    "presence_digitale": {"type": "string"},
                    "reseaux_sociaux": {"type": "array", "items": {"type": "string"}},
                    "forces":         {"type": "array", "items": {"type": "string"}, "description": "Points forts observés"},
                    "faiblesses":     {"type": "array", "items": {"type": "string"}},
                    "opportunites":   {"type": "array", "items": {"type": "string"}},
                    "menaces":        {"type": "array", "items": {"type": "string"}},
                    "score_pertinence": {"type": "number", "description": "0.0 à 1.0"},
                    "source_url":     {"type": "string", "description": "URL source où l'info a été lue"},
                },
                "required": ["nom", "source_url"],
            },
        },
    },
]