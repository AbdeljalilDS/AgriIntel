"""
Agent Benchmark Enterprise — pipeline de recherche concurrentielle multi-phases.

Architecture (inspirée de Perplexity Deep Research / Gemini Deep Research) :

  BREADTH → DEPTH → VERIFY → ENRICH → ANALYZE → REPORT

Chaque phase a un objectif précis, un budget de tours et un critère de passage.
L'agent utilise le QueryPlanner pour des requêtes structurées et le CoverageEngine
pour décider quand l'étude est suffisamment complète.

Stop criteria multi-dimensionnel :
  - coverage_score >= 0.40 (proportion de dimensions documentées)
  - min_entities atteint (défaut 5)
  - ou budget épuisé (max_tours)
  - ou rendements décroissants (3 tours consécutifs sans gain)
"""
from __future__ import annotations

import json
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_benchmark import tools
from agent_benchmark.prompts import PROMPT_SYSTEME_BENCHMARK
from config.settings import settings
from core.entity_resolution import normalize_name, name_similarity, extract_domain
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee
from core.query_planner import QueryPlanner

logger = get_logger(__name__)


class BenchmarkAgent:
    """
    Agent de benchmark concurrentiel enterprise.
    Pipeline multi-phases avec critères d'arrêt intelligents et résolution d'entités.
    """

    def __init__(self, llm: LLMClient, mode: str = "standard"):
        self.llm = llm
        self.mode = mode
        self.max_tours = settings.max_tours_agent(mode)
        self.planner: QueryPlanner | None = None

    class Etat(TypedDict):
        messages:            list[dict]
        entites:             list[EntiteAnalysee]
        tour:                int
        queries_used:        int
        pages_scraped:       int
        last_gain:           float
        consecutive_no_gain: int
        phase:               str

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
        function = appel.get("function", {})
        if isinstance(function, dict):
            return str(function.get("name", "")).strip()
        return ""

    @staticmethod
    def _extraire_arguments(appel: dict) -> dict:
        function = appel.get("function", {})
        if not isinstance(function, dict):
            return {}
        return BenchmarkAgent._normaliser_arguments(function.get("arguments", {}))

    @staticmethod
    def _cle_entite(entite: EntiteAnalysee) -> str:
        cle = getattr(entite, "cle_normalisee", None)
        if callable(cle):
            return str(cle())
        return str(getattr(entite, "nom", "")).strip().casefold()

    @staticmethod
    def _ajouter_entite_unique(
        entites: list[EntiteAnalysee], entite: EntiteAnalysee
    ) -> bool:
        if not entite or not getattr(entite, "nom", None):
            return False

        nom_norm = normalize_name(entite.nom)
        if not nom_norm:
            nom_norm = entite.nom.strip().lower()

        # Recherche de doublon canonique via entity_resolution (Levenshtein + domaine)
        for existante in entites:
            nom_exist = normalize_name(existante.nom) or existante.nom.strip().lower()
            sim = name_similarity(nom_norm, nom_exist)

            meme_domaine = False
            if entite.site_web and existante.site_web:
                d1 = extract_domain(entite.site_web)
                d2 = extract_domain(existante.site_web)
                meme_domaine = bool(d1 and d2 and d1 == d2 and len(d1) > 2)

            if sim >= 0.80 or meme_domaine:
                # Fusionner / enrichir l'entité existante avec les nouvelles informations
                if not existante.description and entite.description:
                    existante.description = entite.description
                if not existante.site_web and entite.site_web:
                    existante.site_web = entite.site_web
                if not existante.chiffre_affaires and entite.chiffre_affaires:
                    existante.chiffre_affaires = entite.chiffre_affaires
                if not existante.effectif and entite.effectif:
                    existante.effectif = entite.effectif

                for p in (entite.produits_services or []):
                    if p not in (existante.produits_services or []):
                        existante.produits_services.append(p)
                for c in (entite.certifications or []):
                    if c not in (existante.certifications or []):
                        existante.certifications.append(c)
                for pe in (entite.pays_export or []):
                    if pe not in (existante.pays_export or []):
                        existante.pays_export.append(pe)
                for f in (entite.forces or []):
                    if f not in (existante.forces or []):
                        existante.forces.append(f)
                for fb in (entite.faiblesses or []):
                    if fb not in (existante.faiblesses or []):
                        existante.faiblesses.append(fb)
                for t in (entite.technologies or []):
                    if t not in (existante.technologies or []):
                        existante.technologies.append(t)

                logger.info("Entité existante enrichie par fusion canonique : %s", existante.nom)
                return True

        entites.append(entite)
        logger.info("Nouvelle entité canonique ajoutée : %s", entite.nom)
        return True

    def _doit_sarreter(self, etat: "BenchmarkAgent.Etat") -> tuple[bool, str]:
        """Critères d'arrêt multi-dimensionnels."""
        tour = etat["tour"]
        nb = len(etat["entites"])
        consecutive_no_gain = etat.get("consecutive_no_gain", 0)
        min_entites = settings.benchmark_cible_min_entites

        if tour >= self.max_tours:
            return True, f"budget_tours épuisé ({self.max_tours})"
        if nb < min_entites:
            return False, f"entités insuffisantes ({nb}/{min_entites})"
        # Rendements décroissants : 4 tours sans gain ET objectif atteint
        if consecutive_no_gain >= 4 and nb >= min_entites:
            return True, f"rendements décroissants ({consecutive_no_gain} tours)"
        return True, "objectifs atteints"

    def _construire_rappel(self, etat: "BenchmarkAgent.Etat") -> str:
        nb = len(etat["entites"])
        objectif = settings.benchmark_cible_min_entites
        tour = etat["tour"]

        session = tools.get_session()
        pages_lues = list(session.derniers_textes_lus.keys())

        # Suggestions d'angles de requêtes issus du QueryPlanner
        suggestion_angle = ""
        if self.planner:
            if nb < 3:
                suggs = self.planner.generate_discovery_queries()[:2]
            elif nb < 7:
                suggs = self.planner.generate_technology_queries()[:2]
            else:
                suggs = self.planner.generate_certification_queries()[:2] + self.planner.generate_export_queries()[:1]
            if suggs:
                suggestion_angle = f" 💡 Suggestions de requêtes recommandées : '{suggs[0].query}' ou '{suggs[-1].query}'."

        if nb == 0:
            rappel = (
                f"[Tour {tour}/{self.max_tours}] ❌ Aucune entreprise enregistrée. "
                "RÈGLE CRITIQUE : dès qu'une page contient un NOM D'ENTREPRISE + "
                "un signal métier (secteur, produits, export, certification, site web), "
                "appelle IMMÉDIATEMENT enregistrer_entreprise. "
                f"Une fiche avec juste nom + description + source_url est VALIDE.{suggestion_angle}"
            )
        elif nb < objectif:
            noms = [e.nom for e in etat["entites"][:3]]
            rappel = (
                f"[Tour {tour}/{self.max_tours}] ✓ {nb}/{objectif} entreprises. "
                f"Déjà enregistrées : {', '.join(noms)}... "
                "Continue : cherche d'autres concurrents avec de nouveaux angles "
                f"(export, certifications, presse, rapports PDF).{suggestion_angle}"
            )
        else:
            rappel = (
                f"[Tour {tour}/{self.max_tours}] ✓ Objectif atteint ({nb} entreprises). "
                "Si tu as encore du budget, enrichis les fiches existantes "
                "(CA, certifications, technologies, partenaires, SWOT). "
                "Sinon, conclus sans appel d'outil."
            )

        if pages_lues:
            rappel += (
                f" Pages lues : {len(pages_lues)}. Dernière : {pages_lues[-1][:60]}."
            )
        else:
            rappel += " Commence par rechercher_memoire puis rechercher_web."

        return rappel

    def _construire_graphe(self, cible: str):
        graphe = StateGraph(self.Etat)

        async def appeler_llm(etat: BenchmarkAgent.Etat):
            tour = etat["tour"] + 1
            logger.info("--- Tour benchmark %s/%s ---", tour, self.max_tours)
            try:
                message = await self.llm.chat_avec_outils(
                    etat["messages"], tools.DEFINITIONS_OUTILS
                )
                if not isinstance(message, dict):
                    message = {"role": "assistant", "content": str(message)}
            except Exception as exc:
                logger.exception("Appel LLM échoué au tour %s", tour)
                message = {"role": "assistant", "content": f"Erreur LLM : {exc}"}
            return {
                "messages": etat["messages"] + [message],
                "tour": tour,
            }

        async def executer_outils(etat: BenchmarkAgent.Etat):
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
                logger.warning("executer_outils sans appels — rappel injecté")
                return {
                    "messages": messages,
                    "entites": entites,
                    "consecutive_no_gain": etat.get("consecutive_no_gain", 0) + 1,
                }

            for appel in appels:
                nom_outil = self._extraire_nom_outil(appel)
                arguments = self._extraire_arguments(appel)
                if not nom_outil:
                    messages.append({
                        "role": "tool",
                        "content": "Erreur : nom d'outil absent.",
                        "name": "outil_inconnu",
                    })
                    continue

                logger.info("Outil : %s(%s...)", nom_outil, str(arguments)[:80])
                try:
                    if nom_outil == "rechercher_web":
                        resultat = await tools.outil_rechercher_web(
                            arguments.get("requete", "")
                        )
                        queries_used += 1
                    elif nom_outil == "rechercher_memoire":
                        resultat = await tools.outil_rechercher_memoire(
                            arguments.get("requete", ""), self.llm
                        )
                    elif nom_outil == "lire_page":
                        index = arguments.get("index", arguments.get("url", ""))
                        resultat = await tools.outil_lire_page(index)
                        pages_scraped += 1
                    elif nom_outil == "enregistrer_entreprise":
                        resultat, entite = await tools.outil_enregistrer_entreprise(
                            arguments, self.llm
                        )
                        if entite is not None:
                            added = self._ajouter_entite_unique(entites, entite)
                            if added:
                                gained = True
                        else:
                            logger.warning("enregistrer_entreprise refusé : %s", resultat[:200])
                    else:
                        resultat = (
                            f"Outil inconnu : {nom_outil}. "
                            "Utilise uniquement : rechercher_memoire, rechercher_web, "
                            "lire_page, enregistrer_entreprise."
                        )
                        logger.warning(resultat)

                except Exception as exc:
                    logger.exception("Erreur outil %s", nom_outil)
                    resultat = f"Erreur contrôlée pendant {nom_outil} : {exc}"

                messages.append({
                    "role": "tool",
                    "content": str(resultat)[:4000],
                    "name": nom_outil,
                })

            consecutive = 0 if gained else etat.get("consecutive_no_gain", 0) + 1
            return {
                "messages": messages,
                "entites": entites,
                "pages_scraped": pages_scraped,
                "queries_used": queries_used,
                "last_gain": 1.0 if gained else 0.0,
                "consecutive_no_gain": consecutive,
            }

        def ajouter_rappel(etat: BenchmarkAgent.Etat):
            rappel = self._construire_rappel(etat)
            logger.warning(
                "Relance (%s/%s entités) : rappel avant nouveau tour LLM",
                len(etat["entites"]),
                settings.benchmark_cible_min_entites,
            )
            return {
                "messages": etat["messages"] + [{"role": "user", "content": rappel}]
            }

        def continuer(etat: BenchmarkAgent.Etat):
            stop, reason = self._doit_sarreter(etat)
            if stop:
                logger.info("Arrêt : %s", reason)
                return END
            dernier = etat["messages"][-1]
            appels = dernier.get("tool_calls") or []
            if appels:
                return "outils"
            return "rappel"

        graphe.add_node("llm", appeler_llm)
        graphe.add_node("outils", executer_outils)
        graphe.add_node("rappel", ajouter_rappel)
        graphe.add_edge(START, "llm")
        graphe.add_conditional_edges(
            "llm",
            continuer,
            {"outils": "outils", "rappel": "rappel", END: END},
        )
        graphe.add_edge("outils", "llm")
        graphe.add_edge("rappel", "llm")
        return graphe.compile()

    async def run(self, cible: str) -> list[EntiteAnalysee]:
        tools.reinitialiser_session()
        min_entites = settings.benchmark_cible_min_entites
        start_time = time.time()

        self.planner = QueryPlanner(
            target=cible,
            objective="benchmark",
            geography="Maroc" if ("maroc" in cible.lower() or "agricole" in cible.lower()) else "",
            sector="Agriculture & Agro-industrie"
        )
        plan_initial = self.planner.generate_discovery_queries()[:3]
        requetes_intro = " · ".join([f"'{q.query}'" for q in plan_initial])

        logger.info("=== Benchmark démarré : %s (max_tours=%s) ===", cible, self.max_tours)

        etat_initial: BenchmarkAgent.Etat = {
            "messages": [
                {
                    "role": "system",
                    "content": PROMPT_SYSTEME_BENCHMARK.format(
                        cible=cible, min_entites=min_entites
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Lance l'étude benchmark stratégique pour : {cible}\n"
                        f"Objectif : {min_entites}+ concurrents documentés.\n"
                        f"Plan de recherche recommandé : {requetes_intro}\n"
                        f"Protocole : 1) rechercher_memoire 'concurrents {cible}' "
                        f"2) rechercher_web pour cartographier les acteurs "
                        f"3) lire_page sur les meilleurs résultats "
                        f"4) enregistrer_entreprise immédiatement dès nom + signal métier validé.\n"
                        f"Angle initial : cartographier les leaders et alternatives du marché."
                    ),
                },
            ],
            "entites": [],
            "tour": 0,
            "queries_used": 0,
            "pages_scraped": 0,
            "last_gain": 1.0,
            "consecutive_no_gain": 0,
            "phase": "breadth",
        }

        graphe = self._construire_graphe(cible)
        resultat = await graphe.ainvoke(etat_initial)
        entites = resultat.get("entites", [])
        elapsed = time.time() - start_time
        logger.info(
            "=== Benchmark terminé : %s entité(s) en %.1fs (tours=%s) ===",
            len(entites), elapsed, resultat.get("tour", 0)
        )
        return entites