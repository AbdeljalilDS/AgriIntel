"""Boîte à outils de l'agent — chaque fonction est une action que le LLM
peut décider d'appeler lui-même via le tool-calling (voir agent.py).
Volontairement limité à ce qui sert réellement le benchmark concurrentiel :
chercher, lire, se souvenir, enregistrer. Pas de SQL générique, OCR ou
exécution de code — hors sujet pour ce cas d'usage."""
import json
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit, urlunsplit

from agent_benchmark.sources import etendre_requete, rechercher_avec_repli, url_scrapable
from agent_benchmark.sources import score_fiabilite_source
from config.settings import settings
from core import memoire
from core.exceptions import ScrapingError
from core.logger import get_logger
from core.models import EntiteAnalysee, _est_valeur_vide
from core.scraper_base import fetch_clean_text
from core.storage import JSONStorage

logger = get_logger(__name__)

# Textes réellement lus pendant l'exécution en cours — sert à la
# vérification légère (une entreprise enregistrée doit provenir d'une page
# vraiment consultée, pas d'une supposition du LLM).
_derniers_textes_lus: dict[str, str] = {}
_embeddings_session: dict[str, list[float] | None] = {}

# Le LLM ne doit JAMAIS taper une URL lui-même (il en invente sinon — c'est
# la cause des domaines inexistants observés en logs, ex. entreprises-
# lemonde.fr). À la place, rechercher_web numérote les résultats réels
# qu'il a obtenus, et lire_page n'accepte qu'un numéro déjà attribué par
# le code. Index -> URL canonique, remis à zéro à chaque étude (agent.run).
_urls_indexees: dict[int, str] = {}
_url_vers_index: dict[str, int] = {}


def _canoniser_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _indexer_url(url: str) -> int:
    """Attribue (ou retrouve) l'index stable d'une URL réelle issue d'une recherche."""
    cle = _canoniser_url(url)
    if cle in _url_vers_index:
        return _url_vers_index[cle]
    index = len(_urls_indexees) + 1
    _urls_indexees[index] = url
    _url_vers_index[cle] = index
    return index


def _embedding_cache(llm, texte: str, limite: int = 5000) -> list[float] | None:
    """Reutilise les embeddings durant une etude pour reduire les appels Ollama."""
    texte_normalise = texte[:limite].strip()
    cle = hashlib.sha256(texte_normalise.encode("utf-8")).hexdigest()
    if cle not in _embeddings_session:
        if len(_embeddings_session) >= 128:
            _embeddings_session.pop(next(iter(_embeddings_session)))
        _embeddings_session[cle] = llm.embed(texte_normalise)
    return _embeddings_session[cle]


def ranker(resultats: list[dict], requete: str, limite: int = 15) -> list[dict]:
    """Classe les resultats par score moteur, couverture lexicale et contenu."""
    mots = {mot.lower() for mot in re.findall(r"[\wÀ-ÿ]+", requete) if len(mot) > 3}

    def canoniser(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))

    uniques_par_url = {}
    for resultat in resultats:
        url = resultat.get("url", "")
        if not url or not url_scrapable(url):
            continue
        contenu = f"{resultat.get('titre', '')} {resultat.get('contenu', '')}".lower()
        pertinence = sum(1 for mot in mots if mot in contenu)
        try:
            score_moteur = float(resultat.get("score") or 0)
        except (TypeError, ValueError):
            score_moteur = 0.0
        resultat = dict(resultat)
        fiabilite = score_fiabilite_source(url, resultat.get("titre", ""), resultat.get("contenu", ""))
        resultat["fiabilite_source"] = fiabilite
        resultat["score_classement"] = round(score_moteur + pertinence * 0.1 + fiabilite * 0.25, 4)
        cle = canoniser(url)
        precedent = uniques_par_url.get(cle)
        if precedent is None or resultat["score_classement"] > precedent["score_classement"]:
            uniques_par_url[cle] = resultat
    return sorted(uniques_par_url.values(), key=lambda item: item["score_classement"], reverse=True)[:limite]


def outil_rechercher_web(requete: str) -> str:
    variantes = etendre_requete(requete)[:settings.max_variantes_recherche]
    resultats: list[dict] = []
    workers = settings.workers_recherche()

    def _chercher(variante: str) -> list[dict]:
        try:
            return rechercher_avec_repli(variante)
        except Exception as exc:
            logger.warning(str(exc))
            return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_chercher, v): v for v in variantes}
        for future in as_completed(futures):
            resultats.extend(future.result())

    uniques = ranker(resultats, requete)

    if not uniques:
        return "Aucun résultat trouvé pour cette requête."

    # On numérote nous-mêmes les résultats réels : le LLM devra citer un
    # numéro (via lire_page), jamais retaper une URL — ça élimine les
    # hallucinations de domaines inexistants.
    lignes = []
    for r in uniques[:15]:
        if not url_scrapable(r["url"]):
            continue
        index = _indexer_url(r["url"])
        lignes.append(
            f"- [{index}] {r['titre']}\n"
            f"  Moteur: {r.get('moteur', 'inconnu')} | Fiabilité estimée: {r['fiabilite_source']:.2f}\n"
            f"  Extrait: {r.get('contenu', '')[:400]}"
        )
    if not lignes:
        return "Aucun résultat exploitable pour cette requête."
    return (
        "Résultats trouvés (utilise lire_page avec le numéro [n] exact, "
        "jamais une URL tapée toi-même) :\n" + "\n".join(lignes)
    )


def outil_lire_page(index) -> str:
    try:
        index = int(index)
    except (TypeError, ValueError):
        return "Refusé : indique le numéro [n] d'un résultat retourné par rechercher_web, pas une URL."
    url = _urls_indexees.get(index)
    if url is None:
        return (
            f"Refusé : aucun résultat numéro [{index}] connu. "
            "Utilise uniquement un numéro affiché par rechercher_web."
        )
    if not url_scrapable(url):
        return "Impossible de lire cette URL : domaine non autorisé ou URL invalide."
    try:
        texte = fetch_clean_text(url)
    except ScrapingError as exc:
        return f"Impossible de lire cette page : {exc}"
    if not texte:
        return "Cette page ne contient pas de contenu exploitable."
    _derniers_textes_lus[url] = texte
    return f"[Source: {url}]\n" + texte[:5000]


def outil_rechercher_memoire(requete: str, llm) -> str:
    """C'est la brique RAG : cherche d'abord dans ce qui est déjà connu
    avant de partir chercher sur le web."""
    embedding = _embedding_cache(llm, requete, limite=2000)
    if embedding:
        resultats = memoire.rechercher_hybride(requete, embedding, top_k=5)
    else:
        resultats = memoire.rechercher_par_mot_cle(requete, top_k=5)

    preuves = memoire.rechercher_preuves(requete, embedding, top_k=8)
    if preuves:
        lignes = [f"- [{i}] {p['type']}: {p['texte']} | source={p['source']} | date={p['date']} | confiance={p['confiance'] or 'non précisée'}" for i, p in enumerate(preuves, 1)]
        return "Preuves atomiques trouvées en mémoire :\n" + "\n".join(lignes)
    if not resultats:
        return "Rien en mémoire pour cette recherche — il faut chercher sur le web."
    lignes = [f"- {r.get('nom')} : {r.get('description') or 'pas de description enregistrée'}" for r in resultats]
    return "Trouvé en mémoire (déjà connu d'une étude précédente) :\n" + "\n".join(lignes)


def outil_enregistrer_entreprise(donnees: dict, llm) -> str:
    nom_brut = donnees.get("nom")
    if isinstance(nom_brut, list):
        nom_brut = nom_brut[0] if nom_brut else None
    if _est_valeur_vide(nom_brut):
        return "Refusé : nom vide ou invalide."

    try:
        entite = EntiteAnalysee.model_validate(donnees)
    except Exception as exc:
        return f"Refusé : données invalides ({exc})"

    def canoniser(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))

    source_lue = canoniser(entite.source_url) in {canoniser(url) for url in _derniers_textes_lus}
    if not source_lue:
        return "Refusé : la source_url fournie n'a pas été lue par l'outil lire_page."

    # Vérification sémantique : la fiche doit être proche d'une page réellement lue.
    texte_entite = " ".join(
        [entite.nom, entite.secteur or "", entite.description or "", " ".join(entite.produits_services)]
    )
    embedding_entite = _embedding_cache(llm, texte_entite)
    scores = []
    if embedding_entite:
        for texte in _derniers_textes_lus.values():
            embedding_page = _embedding_cache(llm, texte, limite=5000)
            score = _similarite_cosinus(embedding_entite, embedding_page)
            if score is not None:
                scores.append(score)
    meilleur_score = max(scores, default=0.0)
    if not scores:
        return "Refusé : validation embedding indisponible."
    if meilleur_score < settings.embedding_validation_threshold:
        return f"Refusé : preuve sémantique insuffisante (score {meilleur_score:.2f})."
    logger.info(f"Validation embedding de '{entite.nom}' : {meilleur_score:.2f}")

    storage = JSONStorage()
    storage.save([entite], f"session_{entite.cle_normalisee()}")

    embedding = _embedding_cache(llm, f"{entite.nom} {entite.secteur or ''} {entite.description or ''}", limite=2000)
    memoire.enregistrer(entite.cle_normalisee(), entite.nom, entite.model_dump_json(), embedding)
    preuves = []
    champs = ("technologies", "competences", "investissements", "innovations", "innovations_recentes")
    faits_texte = [("description", entite.description), ("secteur", entite.secteur)]
    faits_texte.extend(("produits_services", produit) for produit in entite.produits_services)
    for type_fait, valeur in faits_texte:
        if not valeur:
            continue
        texte = f"{entite.nom} — {valeur}"
        preuves.append({
            "type_fait": type_fait,
            "texte": texte,
            "source_url": entite.source_url,
            "date_collecte": entite.date_collecte.isoformat(),
            "confiance": entite.score_pertinence,
            "embedding": _embedding_cache(llm, texte, limite=2000),
        })
    for champ in champs:
        for fait in getattr(entite, champ):
            texte = f"{entite.nom} — {fait.valeur}"
            preuves.append({
                "type_fait": champ,
                "texte": texte,
                "source_url": fait.source_url or entite.source_url,
                "date_collecte": (fait.date_collecte or entite.date_collecte).isoformat(),
                "confiance": fait.confiance,
                "embedding": _embedding_cache(llm, texte, limite=2000),
            })
    memoire.enregistrer_preuves(entite.cle_normalisee(), preuves)

    return f"Enregistré avec succès : {entite.nom}"


def _similarite_cosinus(gauche: list[float] | None, droite: list[float] | None) -> float | None:
    if not gauche or not droite or len(gauche) != len(droite):
        return None
    norme_gauche = sum(valeur * valeur for valeur in gauche) ** 0.5
    norme_droite = sum(valeur * valeur for valeur in droite) ** 0.5
    if not norme_gauche or not norme_droite:
        return None
    return sum(a * b for a, b in zip(gauche, droite)) / (norme_gauche * norme_droite)


DEFINITIONS_OUTILS = [
    {
        "type": "function",
        "function": {
            "name": "rechercher_memoire",
            "description": (
                "Cherche si une information est déjà connue en mémoire (études précédentes) "
                "avant de chercher sur le web — à utiliser en premier."
            ),
            "parameters": {
                "type": "object",
                "properties": {"requete": {"type": "string", "description": "Ce qu'on cherche à retrouver"}},
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rechercher_web",
            "description": "Cherche sur le web des informations récentes (entreprises, actualités, PDF...).",
            "parameters": {
                "type": "object",
                "properties": {"requete": {"type": "string", "description": "La requête de recherche"}},
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lire_page",
            "description": (
                "Lit le contenu texte d'une page à partir de son NUMÉRO [n], tel qu'affiché par "
                "rechercher_web. N'accepte jamais une URL tapée directement — utilise uniquement "
                "un numéro déjà vu dans les résultats d'une recherche précédente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "Le numéro [n] du résultat à lire, tel qu'affiché par rechercher_web.",
                    }
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
                "Enregistre une entreprise identifiée avec ses informations, UNIQUEMENT si trouvées "
                "dans une page réellement lue via lire_page (jamais depuis ta mémoire seule)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string"},
                    "secteur": {"type": "string"},
                    "description": {"type": "string"},
                    "produits_services": {"type": "array", "items": {"type": "string"}},
                    "technologies": {"type": "array", "items": {"type": "object", "properties": {"valeur": {"type": "string"}, "source_url": {"type": "string"}, "date_collecte": {"type": "string"}, "confiance": {"type": "number"}}}},
                    "certifications": {"type": "array", "items": {"type": "string"}},
                    "score_pertinence": {"type": "number"},
                    "source_url": {"type": "string"},
                },
                "required": ["nom", "source_url"],
            },
        },
    },
]
