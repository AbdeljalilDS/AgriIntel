"""
Agent Startup — recherche de l'écosystème startup, innovation, financement.

Workflow dédié (distinct du benchmark) :
  DISCOVERY → PROFILE → FOUNDERS → FUNDING → TECH → TRACTION → ECOSYSTEM → REPORT

Spécificités startup :
- Critères différents : fondateurs, stade financement, montant levé, incubateurs
- Sources spécialisées : Crunchbase, MaGnitt, Dealroom, TechCrunch, press africaine tech
- Traction signals : clients, utilisateurs, ARR, partenariats
- Écosystème : investisseurs, incubateurs, accélérateurs, programmes gouvernementaux
"""
from __future__ import annotations

import json
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_startup import tools
from agent_benchmark.prompts import PROMPT_SYSTEME_STARTUP
from config.settings import settings
from core.entity_resolution import normalize_name, name_similarity, extract_domain
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee

logger = get_logger(__name__)


class StartupAgent:
    """Agent de recherche de startups — workflow dédié à l'écosystème innovation avec résolution d'entités."""

    def __init__(self, llm: LLMClient, mode: str = "standard"):
        self.llm = llm
        self.mode = mode
        self.max_tours = settings.max_tours_agent(mode)

    class Etat(TypedDict):
        messages:            list[dict]
        entites:             list[EntiteAnalysee]
        tour:                int
        queries_used:        int
        pages_scraped:       int
        consecutive_no_gain: int

    @staticmethod
    def _normaliser_arguments(arguments: Any) -> dict:
        if arguments is None:
            return {}
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                r = json.loads(arguments)
                return r if isinstance(r, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _extraire_nom_outil(appel: dict) -> str:
        fn = appel.get("function", {})
        if isinstance(fn, dict):
            return str(fn.get("name", "")).strip()
        return ""

    @staticmethod
    def _extraire_arguments(appel: dict) -> dict:
        fn = appel.get("function", {})
        if not isinstance(fn, dict):
            return {}
        return StartupAgent._normaliser_arguments(fn.get("arguments", {}))

    @staticmethod
    def _cle_entite(entite: EntiteAnalysee) -> str:
        cle = getattr(entite, "cle_normalisee", None)
        if callable(cle):
            return str(cle())
        return str(getattr(entite, "nom", "")).strip().casefold()

    @staticmethod
    def _ajouter_entite_unique(entites: list[EntiteAnalysee], entite: EntiteAnalysee) -> bool:
        if not entite or not getattr(entite, "nom", None):
            return False

        nom_norm = normalize_name(entite.nom) or entite.nom.strip().lower()

        # Recherche de doublon canonique via entity_resolution
        for existante in entites:
            nom_exist = normalize_name(existante.nom) or existante.nom.strip().lower()
            sim = name_similarity(nom_norm, nom_exist)

            meme_domaine = False
            if entite.site_web and existante.site_web:
                d1 = extract_domain(entite.site_web)
                d2 = extract_domain(existante.site_web)
                meme_domaine = bool(d1 and d2 and d1 == d2 and len(d1) > 2)

            if sim >= 0.80 or meme_domaine:
                # Enrichissement fusionnel
                if not existante.description and entite.description:
                    existante.description = entite.description
                if not existante.site_web and entite.site_web:
                    existante.site_web = entite.site_web
                for p in (entite.produits_services or []):
                    if p not in (existante.produits_services or []):
                        existante.produits_services.append(p)
                for t in (entite.technologies or []):
                    if t not in (existante.technologies or []):
                        existante.technologies.append(t)
                for f in (entite.forces or []):
                    if f not in (existante.forces or []):
                        existante.forces.append(f)
                logger.info("Startup existante enrichie : %s", existante.nom)
                return True

        entites.append(entite)
        logger.info("Nouvelle startup ajoutée : %s", entite.nom)
        return True

    def _construire_rappel(self, etat: "StartupAgent.Etat") -> str:
        nb = len(etat["entites"])
        objectif = settings.benchmark_cible_min_entites
        tour = etat["tour"]

        session = tools.get_session()
        pages_lues = list(session.derniers_textes_lus.keys())

        if nb == 0:
            rappel = (
                f"[Tour {tour}/{self.max_tours}] ❌ Aucune startup enregistrée. "
                "Appelle enregistrer_entreprise dès qu'une page mentionne : "
                "nom de startup + (secteur OU description OU fondateurs OU financement). "
                "Cherche sur : startups agritech liste, levée de fonds financement startup, "
                "incubateurs programmes startup. "
            )
        elif nb < objectif:
            rappel = (
                f"[Tour {tour}/{self.max_tours}] ✓ {nb}/{objectif} startups. "
                "Continue : cherche les investisseurs, incubateurs, programmes d'accompagnement. "
                "Explore les plateformes : Crunchbase, MaGnitt, CFC, wamda.com, disrupt-africa.com. "
            )
        else:
            rappel = (
                f"[Tour {tour}/{self.max_tours}] ✓ {nb} startups enregistrées. "
                "Enrichis les fiches : montants de financement, fondateurs, "
                "traction (clients, ARR), investisseurs. "
            )

        if pages_lues:
            rappel += f"Pages lues : {len(pages_lues)}. "
        return rappel

    def _doit_sarreter(self, etat: "StartupAgent.Etat") -> tuple[bool, str]:
        tour = etat["tour"]
        nb = len(etat["entites"])
        consecutive = etat.get("consecutive_no_gain", 0)
        min_entites = settings.benchmark_cible_min_entites

        if tour >= self.max_tours:
            return True, f"max_tours ({self.max_tours}) atteint"
        if nb < min_entites:
            return False, f"startups insuffisantes ({nb}/{min_entites})"
        if consecutive >= 4 and nb >= min_entites:
            return True, f"rendements décroissants ({consecutive} tours)"
        return True, "objectif atteint"

    def _construire_graphe(self, cible: str):
        graphe = StateGraph(self.Etat)

        async def appeler_llm(etat: StartupAgent.Etat):
            tour = etat["tour"] + 1
            logger.info("--- Tour startup %s/%s ---", tour, self.max_tours)
            try:
                message = await self.llm.chat_avec_outils(
                    etat["messages"], tools.DEFINITIONS_OUTILS
                )
                if not isinstance(message, dict):
                    message = {"role": "assistant", "content": str(message)}
            except Exception as exc:
                logger.exception("LLM startup échoué tour %s", tour)
                message = {"role": "assistant", "content": f"Erreur LLM : {exc}"}
            return {"messages": etat["messages"] + [message], "tour": tour}

        async def executer_outils(etat: StartupAgent.Etat):
            message = etat["messages"][-1]
            messages = list(etat["messages"])
            entites = list(etat["entites"])
            appels = message.get("tool_calls") or []
            pages_scraped = etat.get("pages_scraped", 0)
            queries_used = etat.get("queries_used", 0)
            gained = False

            if not appels:
                rappel = self._construire_rappel(etat)
                messages.append({"role": "user", "content": rappel})
                return {
                    "messages": messages,
                    "entites": entites,
                    "consecutive_no_gain": etat.get("consecutive_no_gain", 0) + 1,
                }

            for appel in appels:
                nom_outil = self._extraire_nom_outil(appel)
                arguments = self._extraire_arguments(appel)
                if not nom_outil:
                    messages.append({"role": "tool", "content": "Erreur : nom d'outil absent.", "name": "outil_inconnu"})
                    continue

                logger.info("Outil startup : %s(%s...)", nom_outil, str(arguments)[:80])
                try:
                    if nom_outil == "rechercher_web":
                        resultat = await tools.outil_rechercher_web(arguments.get("requete", ""))
                        queries_used += 1
                    elif nom_outil == "rechercher_memoire":
                        resultat = await tools.outil_rechercher_memoire(arguments.get("requete", ""), self.llm)
                    elif nom_outil == "lire_page":
                        resultat = await tools.outil_lire_page(arguments.get("index", 0))
                        pages_scraped += 1
                    elif nom_outil == "enregistrer_entreprise":
                        resultat, entite = await tools.outil_enregistrer_entreprise(arguments, self.llm)
                        if entite is not None:
                            added = self._ajouter_entite_unique(entites, entite)
                            if added:
                                gained = True
                        else:
                            logger.warning("Startup refusée : %s", resultat[:200])
                    else:
                        resultat = f"Outil inconnu : {nom_outil}. Utilise les outils déclarés."
                        logger.warning(resultat)
                except Exception as exc:
                    logger.exception("Erreur outil startup %s", nom_outil)
                    resultat = f"Erreur : {exc}"

                messages.append({"role": "tool", "content": str(resultat)[:4000], "name": nom_outil})

            consecutive = 0 if gained else etat.get("consecutive_no_gain", 0) + 1
            return {
                "messages": messages,
                "entites": entites,
                "pages_scraped": pages_scraped,
                "queries_used": queries_used,
                "consecutive_no_gain": consecutive,
            }

        def ajouter_rappel(etat: StartupAgent.Etat):
            rappel = self._construire_rappel(etat)
            return {"messages": etat["messages"] + [{"role": "user", "content": rappel}]}

        def continuer(etat: StartupAgent.Etat):
            stop, reason = self._doit_sarreter(etat)
            if stop:
                logger.info("Startup agent arrêt : %s", reason)
                return END
            dernier = etat["messages"][-1]
            if dernier.get("tool_calls"):
                return "outils"
            return "rappel"

        graphe.add_node("llm", appeler_llm)
        graphe.add_node("outils", executer_outils)
        graphe.add_node("rappel", ajouter_rappel)
        graphe.add_edge(START, "llm")
        graphe.add_conditional_edges("llm", continuer, {"outils": "outils", "rappel": "rappel", END: END})
        graphe.add_edge("outils", "llm")
        graphe.add_edge("rappel", "llm")
        return graphe.compile()

    async def run(self, cible: str) -> list[EntiteAnalysee]:
        tools.reinitialiser_session()
        min_entites = settings.benchmark_cible_min_entites
        start_time = time.time()

        logger.info("=== Startup Research démarré : %s (max_tours=%s) ===", cible, self.max_tours)

        etat_initial: StartupAgent.Etat = {
            "messages": [
                {
                    "role": "system",
                    "content": PROMPT_SYSTEME_STARTUP.format(
                        cible=cible,
                        min_entites=min_entites,
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Lance la recherche de startups dans le domaine : {cible}\n"
                        f"Objectif : {min_entites}+ startups documentées.\n"
                        f"Commence par :\n"
                        f"1) rechercher_memoire 'startups {cible}'\n"
                        f"2) rechercher_web 'startups {cible} 2024 liste levée fonds'\n"
                        f"3) lire_page sur les résultats les plus pertinents\n"
                        f"4) enregistrer_entreprise pour chaque startup identifiée\n"
                        f"Explore aussi : incubateurs, accélérateurs, investisseurs dans ce domaine."
                    ),
                },
            ],
            "entites": [],
            "tour": 0,
            "queries_used": 0,
            "pages_scraped": 0,
            "consecutive_no_gain": 0,
        }

        graphe = self._construire_graphe(cible)
        resultat = await graphe.ainvoke(etat_initial)
        entites = resultat.get("entites", [])
        elapsed = time.time() - start_time
        logger.info(
            "=== Startup Research terminé : %s startup(s) en %.1fs ===",
            len(entites), elapsed
        )
        return entites
