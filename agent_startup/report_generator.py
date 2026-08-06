from agent_startup.prompts import PROMPT_SYNTHESE_RAPPORT_STARTUP
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee, valeur_affichage
from core.analytics import calculer_statistiques, formater_statistiques

logger = get_logger(__name__)


def _ligne(label, valeur):
    if not valeur:
        return ""
    if isinstance(valeur, list):
        valeur = ", ".join(valeur_affichage(item) for item in valeur)
    return f"- {label} : {valeur}\n"


def formater_startups(entites: list[EntiteAnalysee]) -> str:
    if not entites:
        return "(aucune)"
    blocs = []
    for e in entites:
        bloc = f"### {e.nom}\n"
        bloc += _ligne("Secteur", e.secteur)
        bloc += _ligne("Description", e.description)
        bloc += _ligne("Fondateurs", e.fondateurs)
        bloc += _ligne("Stade de financement", e.stade_financement)
        bloc += _ligne("Financement levé", e.financement_leve)
        bloc += _ligne("Technologies", e.technologies)
        bloc += _ligne("Compétences", e.competences)
        bloc += _ligne("Investissements", e.investissements)
        bloc += _ligne("Innovations", e.innovations)
        bloc += _ligne("Score de pertinence", e.score_pertinence)
        bloc += _ligne("Source", e.source_url)
        bloc += _ligne("Date de collecte", e.date_collecte.isoformat())
        blocs.append(bloc.strip())
    return "\n\n".join(blocs)


def generer_rapport_startup(llm: LLMClient, cible: str, entites: list[EntiteAnalysee]) -> str:
    if not entites:
        return f"# Veille Startups — {cible}\n\nAucune startup identifiée lors de cette exécution."
    entites_triees = sorted(entites, key=lambda e: (e.score_pertinence or 0), reverse=True)
    details = formater_startups(entites_triees)
    statistiques = calculer_statistiques(entites_triees)
    prompt = PROMPT_SYNTHESE_RAPPORT_STARTUP.format(cible=cible, donnees=details) + "\n\nStatistiques calculées :\n" + formater_statistiques(statistiques)
    try:
        synthese = llm.generate(prompt)
    except Exception as exc:
        logger.warning(f"Synthèse échouée : {exc}")
        synthese = "*(Synthèse indisponible.)*"
    return f"# Veille Startups — {cible}\n\n## Statistiques de collecte\n\n{formater_statistiques(statistiques)}\n\n{synthese.strip()}\n\n---\n\n## Détail\n\n{details}\n"
