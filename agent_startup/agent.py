"""Agent Startup — architecture agentique (LangGraph + tool-calling).

Converti en v2.2 depuis un pipeline linéaire vers une vraie boucle agentique,
identique à BenchmarkAgent dans sa mécanique (état LangGraph, tool-calling,
validation double) mais avec un prompt et des outils orientés startups :
    - Critères startup : fondateurs, financement, innovation, incubateur
    - Sources : plateformes startup.ma, médias agritech, OCP Innovation Hub…
    - Même anti-hallucination d'URL (index numérique → URL réelle)
    - Même validation double (source lue + similarité cosinus ≥ 0.45)

L'agent décide lui-même de ses actions à chaque tour au lieu d'un pipeline
figé recherche→scraping→extraction. Résultat : exploration plus profonde,
moins de faux positifs, architecture cohérente entre les deux agents.
"""
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent_startup import tools as startup_tools
from agent_startup.prompts import PROMPT_SYSTEME_STARTUP
from config.settings import settings
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee

logger = get_logger(__name__)


class StartupAgent:
    def __init__(self, llm: LLMClient, mode: str = "standard"):
        self.llm = llm
        self.mode = mode
        self.max_tours = settings.max_tours_agent(mode)

    class Etat(TypedDict):
        messages: list[dict]
        entites: list[EntiteAnalysee]
        tour: int

    def _construire_graphe(self, cible: str):
        graphe = StateGraph(self.Etat)

        def appeler_llm(etat: StartupAgent.Etat):
            tour = etat["tour"] + 1
            logger.info(f"--- Tour startup {tour}/{self.max_tours} ---")
            try:
                message = self.llm.chat_avec_outils(
                    etat["messages"], startup_tools.DEFINITIONS_OUTILS_STARTUP
                )
            except Exception as exc:
                logger.warning(f"Appel LLM startup échoué au tour {tour} : {exc}")
                message = {"role": "assistant", "content": "Erreur LLM : arrêt contrôlé."}
            return {"messages": etat["messages"] + [message], "tour": tour}

        def executer_outils(etat: StartupAgent.Etat):
            # Import local pour éviter la circularité au démarrage
            from agent_benchmark import tools as benchmark_tools

            message = etat["messages"][-1]
            messages = list(etat["messages"])
            entites = list(etat["entites"])

            for appel in message.get("tool_calls") or []:
                nom_outil = appel["function"]["name"]
                arguments = appel["function"].get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                logger.info(f"Outil startup : {nom_outil}({list(arguments.keys())})")

                if nom_outil == "rechercher_web":
                    resultat = benchmark_tools.outil_rechercher_web(
                        arguments.get("requete", "")
                    )
                elif nom_outil == "lire_page":
                    # Accepte "index" ou "url" pour robustesse
                    index = arguments.get("index", arguments.get("url", ""))
                    resultat = benchmark_tools.outil_lire_page(index)
                elif nom_outil == "rechercher_memoire":
                    resultat = benchmark_tools.outil_rechercher_memoire(
                        arguments.get("requete", ""), self.llm
                    )
                elif nom_outil == "enregistrer_entreprise":
                    resultat = benchmark_tools.outil_enregistrer_entreprise(
                        arguments, self.llm
                    )
                    if resultat.startswith("Enregistré"):
                        try:
                            entites.append(EntiteAnalysee.model_validate(arguments))
                        except Exception as exc:
                            logger.warning(
                                f"Startup enregistrée mais non re-parsable : {exc}"
                            )
                else:
                    resultat = f"Outil inconnu : {nom_outil}"

                messages.append(
                    {"role": "tool", "content": resultat[:5000], "name": nom_outil}
                )

            return {"messages": messages, "entites": entites}

        def continuer(etat: StartupAgent.Etat):
            dernier = etat["messages"][-1]
            if etat["tour"] >= self.max_tours or not dernier.get("tool_calls"):
                return END
            return "outils"

        graphe.add_node("llm", appeler_llm)
        graphe.add_node("outils", executer_outils)
        graphe.add_edge(START, "llm")
        graphe.add_conditional_edges(
            "llm", continuer, {"outils": "outils", END: END}
        )
        graphe.add_edge("outils", "llm")
        return graphe.compile()

    def run(self, cible: str) -> list[EntiteAnalysee]:
        """Point d'entrée principal — lance la boucle agentique."""
        from agent_benchmark import tools as benchmark_tools

        # Réinitialise les états de session partagés avec benchmark_tools
        benchmark_tools._derniers_textes_lus.clear()
        benchmark_tools._embeddings_session.clear()
        benchmark_tools._urls_indexees.clear()
        benchmark_tools._url_vers_index.clear()

        etat_initial = {
            "messages": [
                {
                    "role": "system",
                    "content": PROMPT_SYSTEME_STARTUP.format(cible=cible),
                },
                {
                    "role": "user",
                    "content": (
                        f"Identifie des startups agritech marocaines pertinentes pour : {cible}. "
                        f"Commence par consulter la mémoire, puis cherche sur le web."
                    ),
                },
            ],
            "entites": [],
            "tour": 0,
        }

        resultat = self._construire_graphe(cible).invoke(etat_initial)
        nb = len(resultat["entites"])
        logger.info(f"Veille startup terminée : {nb} startup(s) enregistrée(s)")
        return resultat["entites"]
