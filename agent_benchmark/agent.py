"""Agent Benchmark — le LLM choisit lui-même ses outils (tool-calling),
au lieu d'un pipeline figé recherche→scrape→extrait. C'est ce qui donne
le comportement "il cherche et réfléchit" plutôt que "on lui donne des
URLs toutes faites"."""
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent_benchmark import tools
from config.settings import settings
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee

logger = get_logger(__name__)

PROMPT_SYSTEME = """Tu es un agent de recherche spécialisé en benchmark concurrentiel du
secteur agricole marocain. Ta mission : identifier des entreprises concurrentes
de "{cible}" et enregistrer leurs informations réelles.

MÉTHODE DE RAISONNEMENT À APPLIQUER À CHAQUE TOUR :
1. Définis mentalement la cible, son marché, sa zone géographique et les critères
    qui rendent une entreprise comparable.
2. Formule une recherche correspondant à un seul angle documentaire à la fois.
3. Pour chaque résultat, sépare le fait observé, la source et l'interprétation.
4. Ne classe une entreprise comme concurrente que si au moins deux critères sont
    documentés parmi : produit, marché, clients, zone ou canal de distribution.
5. Si deux sources se contredisent, conserve les deux faits, signale le conflit
    et ne tranche pas sans preuve plus forte.
6. Avant tout enregistrement, vérifie : page lue, source_url cohérente, données
    non vides et confiance justifiée. Sinon, rejette la fiche.

Utilise tes outils dans cet ordre logique :
1. rechercher_memoire — vérifie d'abord ce qui est déjà connu d'une étude précédente
2. rechercher_web — cherche des pistes si la mémoire ne suffit pas
3. lire_page — lis les pages prometteuses trouvées
4. enregistrer_entreprise — enregistre chaque entreprise identifiée, avec
   UNIQUEMENT les informations réellement lues dans une page (jamais inventées)

Pour couvrir les ressources disponibles, formule plusieurs recherches ciblées :
site officiel et activités, concurrents et export, financement, technologie,
presse spécialisée, réglementation et partenariats. Ne te limite pas au premier
résultat et ne considère jamais un extrait de moteur comme une preuve suffisante.

Pour chaque concurrent potentiel, croise au moins deux sources quand c'est
possible, privilégie les sites officiels et les sources institutionnelles,
et utilise le score de fiabilité fourni par la recherche pour choisir les URLs.
Ne confonds pas un fournisseur agricole avec un concurrent producteur/exportateur.
Ne réponds jamais sur les données d'une entreprise sans les avoir vérifiées
via rechercher_web puis lire_page.

Ne révèle pas une chaîne de pensée détaillée : produis seulement des décisions
courtes et vérifiables dans les appels d'outils et le résumé final.

Quand tu juges avoir trouvé assez d'entreprises pertinentes (entre 5 et 12),
ou si tu as fait le tour sans plus de pistes, termine en écrivant un court
résumé texte (sans appeler d'outil supplémentaire)."""


class BenchmarkAgent:
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

        def appeler_llm(etat: BenchmarkAgent.Etat):
            tour = etat["tour"] + 1
            logger.info(f"--- Tour {tour}/{self.max_tours} ---")
            try:
                message = self.llm.chat_avec_outils(etat["messages"], tools.DEFINITIONS_OUTILS)
            except Exception as exc:
                logger.warning(f"Appel LLM échoué au tour {tour} : {exc}")
                message = {"role": "assistant", "content": "Erreur LLM : arrêt contrôlé."}
            return {"messages": etat["messages"] + [message], "tour": tour}

        def executer_outils(etat: BenchmarkAgent.Etat):
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
                logger.info(f"Outil appelé : {nom_outil}({arguments})")
                if nom_outil == "rechercher_web":
                    resultat = tools.outil_rechercher_web(arguments.get("requete", ""))
                elif nom_outil == "lire_page":
                    resultat = tools.outil_lire_page(arguments.get("url", ""))
                elif nom_outil == "rechercher_memoire":
                    resultat = tools.outil_rechercher_memoire(arguments.get("requete", ""), self.llm)
                elif nom_outil == "enregistrer_entreprise":
                    resultat = tools.outil_enregistrer_entreprise(arguments, self.llm)
                    if resultat.startswith("Enregistré"):
                        try:
                            entites.append(EntiteAnalysee.model_validate(arguments))
                        except Exception as exc:
                            logger.warning(f"Entité enregistrée mais non re-parsable : {exc}")
                else:
                    resultat = f"Outil inconnu : {nom_outil}"
                messages.append({"role": "tool", "content": resultat[:5000], "name": nom_outil})
            return {"messages": messages, "entites": entites}

        def continuer(etat: BenchmarkAgent.Etat):
            dernier = etat["messages"][-1]
            if etat["tour"] >= self.max_tours or not dernier.get("tool_calls"):
                return END
            return "outils"

        graphe.add_node("llm", appeler_llm)
        graphe.add_node("outils", executer_outils)
        graphe.add_edge(START, "llm")
        graphe.add_conditional_edges("llm", continuer, {"outils": "outils", END: END})
        graphe.add_edge("outils", "llm")
        return graphe.compile()

    def run(self, cible: str) -> list[EntiteAnalysee]:
        tools._derniers_textes_lus.clear()
        tools._embeddings_session.clear()
        etat_initial = {
            "messages": [
            {"role": "system", "content": PROMPT_SYSTEME.format(cible=cible)},
            {"role": "user", "content": f"Fais un benchmark concurrentiel pour : {cible}"},
            ],
            "entites": [],
            "tour": 0,
        }
        resultat = self._construire_graphe(cible).invoke(etat_initial)
        logger.info(f"Étude terminée : {len(resultat['entites'])} entité(s) enregistrée(s)")
        return resultat["entites"]
