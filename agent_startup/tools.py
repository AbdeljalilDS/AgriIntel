"""
Outils de l'agent Startup — version dédiée avec session isolée.
Utilise le même moteur de recherche mais avec des requêtes startup-spécialisées.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
from urllib.parse import urlsplit, urlunsplit

from config.settings import settings
from core import memoire
from core.logger import get_logger
from core.models import EntiteAnalysee, _est_valeur_vide
from core.scraper_base import fetch_clean_text, url_scrapable
from core.storage import JSONStorage

logger = get_logger(__name__)

_session_var: contextvars.ContextVar["EtatSession"] = contextvars.ContextVar("_etat_session_startup")


class EtatSession:
    def __init__(self):
        self.derniers_textes_lus:      dict[str, str] = {}
        self.embeddings_session:       dict[str, list[float] | None] = {}
        self.derniere_url_lue:         str | None = None
        self.urls_indexees:            dict[int, str] = {}
        self.url_vers_index:           dict[str, int] = {}
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


def _canoniser_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


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


async def outil_rechercher_web(requete: str) -> str:
    if not requete or len(requete.strip()) < 3:
        return "Requête trop courte."

    from agent_benchmark.sources import SearchEngine, etendre_requete
    engine = SearchEngine(sector="startup")

    # Requêtes startup spécialisées
    variantes = await etendre_requete(requete)
    # Ajouter des variantes startup-spécifiques
    startup_variantes = [
        f"{requete} startup financement levée fonds 2024",
        f"{requete} incubateur accélérateur programme",
        f"{requete} crunchbase dealroom magnitt",
    ]
    all_queries = [requete] + variantes[:3] + startup_variantes[:2]

    resultats = await engine.parallel_search(
        all_queries,
        max_results_each=settings.max_results_per_query,
        max_workers=settings.search_parallel_workers,
    )

    if not resultats:
        return "Aucun résultat trouvé."

    lignes = [f"Résultats pour '{requete}' ({len(resultats)} sources) :\n"]
    for r in resultats[:15]:
        if not url_scrapable(r.url):
            continue
        index = _indexer_url(r.url)
        tier_label = {1: "★★★★★", 2: "★★★★", 3: "★★★", 4: "★★"}.get(r.tier, "★")
        lignes.append(
            f"[{index}] {r.title[:80]}\n"
            f"  {tier_label} | {r.provider} | Score: {r.score:.2f}\n"
            f"  {r.snippet[:250]}\n"
        )
    return "\n".join(lignes)


async def outil_lire_page(index) -> str:
    try:
        index = int(index)
    except (TypeError, ValueError):
        return "Refusé : indique le numéro [n] retourné par rechercher_web."

    session = get_session()
    url = session.urls_indexees.get(index)
    if url is None:
        return f"Refusé : numéro [{index}] inconnu. Utilise un numéro de rechercher_web."
    if not url_scrapable(url):
        return "Impossible : domaine non autorisé."

    try:
        texte = await fetch_clean_text(url)
    except Exception as exc:
        return f"Impossible de lire : {exc}"

    if not texte:
        return "Page sans contenu exploitable."

    session.derniers_textes_lus[url] = texte
    session.derniere_url_lue = url
    return (
        f"[Source #{index}: {url}]\n"
        f"=== CONTENU ({len(texte):,} caractères) ===\n"
        f"{texte[:3500]}"
    )


async def outil_rechercher_memoire(requete: str, llm) -> str:
    embedding = await _embedding_cache(llm, requete, limite=2000)
    if embedding:
        resultats = await memoire.rechercher_hybride(requete, embedding, top_k=6)
    else:
        resultats = await memoire.rechercher_par_mot_cle(requete, top_k=6)

    preuves = await memoire.rechercher_preuves(requete, embedding, top_k=8)
    if preuves:
        lignes = [
            f"- [{i}] {p['type']}: {p['texte']} | source={p['source']} | confiance={p['confiance'] or 'inconnue'}"
            for i, p in enumerate(preuves, 1)
        ]
        return "Startups/preuves en mémoire :\n" + "\n".join(lignes)
    if not resultats:
        return "Rien en mémoire — cherche sur le web."
    lignes = [f"- {r.get('nom')} : {r.get('description') or '-'}" for r in resultats]
    return "En mémoire :\n" + "\n".join(lignes)


async def outil_enregistrer_entreprise(donnees: dict, llm) -> tuple[str, EntiteAnalysee | None]:
    nom_brut = donnees.get("nom")
    if isinstance(nom_brut, list):
        nom_brut = nom_brut[0] if nom_brut else None
    if _est_valeur_vide(nom_brut):
        return "Refusé : nom vide.", None

    session = get_session()
    if _est_valeur_vide(donnees.get("source_url")) and session.derniere_url_lue:
        donnees = {**donnees, "source_url": session.derniere_url_lue}

    try:
        entite = EntiteAnalysee.model_validate(donnees)
    except Exception as exc:
        return f"Refusé : données invalides ({exc})", None

    cle = entite.cle_normalisee()
    if cle in session.entreprises_enregistrees:
        return f"Refusé : '{entite.nom}' déjà enregistrée.", None

    urls_lues = list(session.derniers_textes_lus.keys())
    domaines_lus = {_domaine(u) for u in urls_lues}
    source_ok = (
        any(_canoniser_url(u) == _canoniser_url(entite.source_url) for u in urls_lues)
        or (_domaine(entite.source_url) in domaines_lus if entite.source_url else False)
        or not urls_lues
    )
    if not source_ok and urls_lues:
        if not entite.site_web and entite.source_url and "http" in entite.source_url:
            entite.site_web = entite.source_url
        entite.source_url = session.derniere_url_lue or urls_lues[-1]
        source_ok = True

    signaux = [
        entite.secteur, entite.description, entite.site_web,
        entite.fondateurs, entite.stade_financement, entite.financement_leve,
        entite.produits_services, entite.technologies,
    ]
    nb_signaux = sum(
        1 for s in signaux
        if (isinstance(s, list) and len(s) > 0) or (not isinstance(s, list) and not _est_valeur_vide(s))
    )
    if nb_signaux < 1:
        return "Refusé : fiche trop pauvre. Ajoute description, secteur ou fondateurs.", None

    session.entreprises_enregistrees.add(cle)
    storage = JSONStorage()
    await asyncio.to_thread(storage.save, [entite], f"startup_{cle}")
    embedding = await _embedding_cache(llm, f"{entite.nom} {entite.secteur or ''} {entite.description or ''}", 2000)
    await memoire.enregistrer(cle, entite.nom, entite.model_dump_json(), embedding)

    preuves = []
    for type_fait, valeur in [("description", entite.description), ("secteur", entite.secteur)]:
        if valeur:
            texte = f"{entite.nom} — {valeur}"
            preuves.append({
                "type_fait": type_fait,
                "texte": texte,
                "source_url": entite.source_url,
                "date_collecte": entite.date_collecte.isoformat(),
                "confiance": entite.score_pertinence,
                "embedding": await _embedding_cache(llm, texte, 2000),
            })
    await memoire.enregistrer_preuves(cle, preuves)

    return f"✓ Startup enregistrée ({nb_signaux} champs) : {entite.nom}", entite


DEFINITIONS_OUTILS = [
    {
        "type": "function",
        "function": {
            "name": "rechercher_memoire",
            "description": "Cherche les startups et données déjà connues en mémoire.",
            "parameters": {
                "type": "object",
                "properties": {"requete": {"type": "string"}},
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rechercher_web",
            "description": (
                "Recherche startups, levées de fonds, incubateurs, investisseurs via plusieurs moteurs. "
                "Utilise des requêtes précises : 'startups agritech Maroc 2024', "
                "'levée fonds startup financement seed', 'incubateurs accélérateurs programme startup'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"requete": {"type": "string"}},
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lire_page",
            "description": "Lit le contenu d'une page à partir de son numéro [n] de rechercher_web.",
            "parameters": {
                "type": "object",
                "properties": {"index": {"type": "integer"}},
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enregistrer_entreprise",
            "description": (
                "Enregistre une startup identifiée. "
                "Champs startup importants : fondateurs, stade_financement, financement_leve, incubateurs. "
                "Minimum : nom + source_url + 1 champ descriptif."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nom":                {"type": "string"},
                    "secteur":            {"type": "string"},
                    "description":        {"type": "string"},
                    "site_web":           {"type": "string"},
                    "annee_creation":     {"type": "string"},
                    "siege_social":       {"type": "string"},
                    "fondateurs":         {"type": "array", "items": {"type": "string"}},
                    "stade_financement":  {"type": "string", "description": "pre-seed, seed, serie-a, serie-b..."},
                    "financement_leve":   {"type": "string", "description": "Ex: '2M USD', '500k EUR'"},
                    "produits_services":  {"type": "array", "items": {"type": "string"}},
                    "technologies":       {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "valeur":     {"type": "string"},
                                "source_url": {"type": "string"},
                                "confiance":  {"type": "number"},
                            },
                        },
                    },
                    "partenaires":        {"type": "array", "items": {"type": "string"}},
                    "investisseurs":      {"type": "array", "items": {"type": "string"},
                                          "description": "Noms des investisseurs/VCs"},
                    "incubateurs":        {"type": "array", "items": {"type": "string"},
                                          "description": "Incubateurs et accélérateurs"},
                    "forces":             {"type": "array", "items": {"type": "string"}},
                    "score_pertinence":   {"type": "number"},
                    "source_url":         {"type": "string"},
                },
                "required": ["nom", "source_url"],
            },
        },
    },
]