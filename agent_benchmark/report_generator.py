from agent_benchmark.prompts import PROMPT_SYNTHESE_RAPPORT
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee, valeur_affichage
from core.analytics import calculer_statistiques, formater_statistiques

logger = get_logger(__name__)


def _ligne(label: str, valeur) -> str:
    if not valeur:
        return ""
    if isinstance(valeur, list):
        valeur = ", ".join(valeur_affichage(item) for item in valeur)
    return f"- {label} : {valeur}\n"


def formater_entites(entites: list[EntiteAnalysee]) -> str:
    if not entites:
        return "(aucune)"
    blocs = []
    for e in entites:
        bloc = f"### {e.nom}\n"
        bloc += _ligne("Secteur", e.secteur)
        bloc += _ligne("Description", e.description)
        bloc += _ligne("Produits/services", e.produits_services)
        bloc += _ligne("Technologies", e.technologies)
        bloc += _ligne("Compétences", e.competences)
        bloc += _ligne("Investissements", e.investissements)
        bloc += _ligne("Innovations", e.innovations)
        bloc += _ligne("Certifications", e.certifications)
        bloc += _ligne("Score de pertinence", e.score_pertinence)
        bloc += _ligne("Source", e.source_url)
        bloc += _ligne("Date de collecte", e.date_collecte.isoformat())
        blocs.append(bloc.strip())
    return "\n\n".join(blocs)


def _tableau_resume(entites: list[EntiteAnalysee]) -> str:
    lignes = ["| Entreprise | Secteur | Score |", "|---|---|---|"]
    for e in entites:
        score = f"{e.score_pertinence:.1f}" if e.score_pertinence is not None else "-"
        lignes.append(f"| {e.nom} | {e.secteur or '-'} | {score} |")
    return "\n".join(lignes)


def generer_rapport(llm: LLMClient, cible: str, entites: list[EntiteAnalysee]) -> str:
    if not entites:
        return f"# Étude Benchmark — {cible}\n\nAucune entité pertinente identifiée lors de cette exécution."

    entites_triees = sorted(entites, key=lambda e: (e.score_pertinence or 0), reverse=True)
    details = formater_entites(entites_triees)
    statistiques = calculer_statistiques(entites_triees)
    prompt = PROMPT_SYNTHESE_RAPPORT.format(cible=cible, nb=len(entites_triees), donnees=details) + "\n\nStatistiques calculées :\n" + formater_statistiques(statistiques)

    try:
        synthese = llm.generate(prompt)
    except Exception as exc:
        logger.warning(f"Échec de la génération de synthèse : {exc}")
        synthese = "*(Synthèse automatique indisponible — voir les données ci-dessous.)*"

    return f"""# Étude Benchmark — {cible}

## Résumé

{_tableau_resume(entites_triees)}

## Statistiques de collecte

{formater_statistiques(statistiques)}

{synthese.strip()}

---

## Détail des entités

{details}
"""
