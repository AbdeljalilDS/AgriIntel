"""
Générateur de rapport startup — FIXED (async) + enrichi.
"""
from __future__ import annotations

from agent_benchmark.prompts import PROMPT_SYNTHESE_RAPPORT_STARTUP
from core.analytics import calculer_statistiques, formater_statistiques
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee, valeur_affichage

logger = get_logger(__name__)


def _ligne(label, valeur) -> str:
    if not valeur:
        return ""
    if isinstance(valeur, list):
        valeur = ", ".join(valeur_affichage(item) for item in valeur if item)
    if not valeur:
        return ""
    return f"- **{label}** : {valeur}\n"


def formater_startups(entites: list[EntiteAnalysee]) -> str:
    if not entites:
        return "(aucune)"
    blocs = []
    for e in entites:
        bloc = f"### {e.nom}\n"
        bloc += _ligne("Secteur", e.secteur)
        bloc += _ligne("Description", e.description)
        bloc += _ligne("Site web", e.site_web)
        bloc += _ligne("Siège social", e.siege_social)
        bloc += _ligne("Année de création", e.annee_creation)
        bloc += _ligne("Fondateurs", e.fondateurs)
        bloc += _ligne("Stade de financement", e.stade_financement)
        bloc += _ligne("Financement levé", e.financement_leve)
        bloc += _ligne("Investisseurs", e.investisseurs)
        bloc += _ligne("Incubateurs / Accélérateurs", e.incubateurs)
        bloc += _ligne("Technologies", e.technologies)
        bloc += _ligne("Produits / Services", e.produits_services)
        bloc += _ligne("Compétences", e.competences)
        bloc += _ligne("Innovations", e.innovations)
        bloc += _ligne("Partenaires", e.partenaires)
        bloc += _ligne("Forces", e.forces)
        bloc += _ligne("Score de pertinence", f"{e.score_pertinence:.2f}" if e.score_pertinence is not None else None)
        bloc += _ligne("Source", e.source_url)
        blocs.append(bloc.strip())
    return "\n\n---\n\n".join(blocs)


def _tableau_startups(entites: list[EntiteAnalysee]) -> str:
    lignes = [
        "| Startup | Secteur | Stade | Financement | Fondateurs | Score |",
        "|---------|---------|-------|-------------|------------|-------|",
    ]
    for e in entites:
        fondateurs = ", ".join((e.fondateurs or [])[:2]) or "-"
        stade = e.stade_financement or "-"
        financement = e.financement_leve or "-"
        score = f"{e.score_pertinence:.2f}" if e.score_pertinence is not None else "-"
        lignes.append(
            f"| {e.nom} | {e.secteur or '-'} | {stade} | {financement} | {fondateurs} | {score} |"
        )
    return "\n".join(lignes)


async def generer_rapport_startup(llm: LLMClient, cible: str, entites: list[EntiteAnalysee]) -> str:
    """ASYNC — BUG CORRIGÉ : await sur llm.generate()"""
    if not entites:
        return (
            f"# Veille Startups — {cible}\n\n"
            "**Résultat** : Aucune startup identifiée lors de cette exécution.\n\n"
            "> Suggestions : vérifier les clés API de recherche (Tavily, Google), "
            "relancer en mode 'large', ou préciser le domaine de recherche."
        )

    entites_triees = sorted(entites, key=lambda e: (e.score_pertinence or 0), reverse=True)
    details = formater_startups(entites_triees)
    statistiques = calculer_statistiques(entites_triees)
    tableau = _tableau_startups(entites_triees)

    prompt = (
        PROMPT_SYNTHESE_RAPPORT_STARTUP.format(cible=cible, donnees=details)
        + "\n\nStatistiques calculées :\n"
        + formater_statistiques(statistiques)
    )

    try:
        # CORRECTIF CRITIQUE : await obligatoire (llm.generate est async)
        synthese = await llm.generate(prompt)
    except Exception as exc:
        logger.warning(f"Synthèse startup échouée : {exc}")
        synthese = "*(Synthèse automatique indisponible.)*"

    return f"""# Veille Startups — {cible}

---

## 📊 Tableau de Bord Startups

{tableau}

---

## 📈 Statistiques de Collecte

{formater_statistiques(statistiques)}

---

{synthese.strip()}

---

## 📋 Fiches Détaillées

{details}
"""
