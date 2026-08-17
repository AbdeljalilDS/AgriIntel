"""
Générateur de rapport benchmark — niveau cabinet de conseil enterprise.

Rapport complet : Résumé exécutif, Cartographie, Matrice comparative,
Tendances, SWOT, PESTEL, Porter 5 forces, Recommandations.
"""
from __future__ import annotations

from agent_benchmark.prompts import PROMPT_SYNTHESE_RAPPORT
from core.analytics import calculer_statistiques, formater_statistiques
from core.llm_client import LLMClient
from core.logger import get_logger
from core.models import EntiteAnalysee, valeur_affichage

logger = get_logger(__name__)


def _ligne(label: str, valeur) -> str:
    if not valeur:
        return ""
    if isinstance(valeur, list):
        valeur = ", ".join(valeur_affichage(item) for item in valeur if item)
    if not valeur:
        return ""
    return f"- **{label}** : {valeur}\n"


def formater_entites(entites: list[EntiteAnalysee]) -> str:
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
        bloc += _ligne("Effectif", e.effectif)
        bloc += _ligne("Chiffre d'affaires", e.chiffre_affaires)
        bloc += _ligne("Produits/services", e.produits_services)
        bloc += _ligne("Positionnement", e.positionnement)
        bloc += _ligne("Technologies", e.technologies)
        bloc += _ligne("Compétences", e.competences)
        bloc += _ligne("Investissements", e.investissements)
        bloc += _ligne("Innovations", e.innovations)
        bloc += _ligne("Certifications", e.certifications)
        bloc += _ligne("Pays d'export", e.pays_export)
        bloc += _ligne("Marchés ciblés", e.marches_cibles)
        bloc += _ligne("Partenaires", e.partenaires)
        bloc += _ligne("Présence digitale", e.presence_digitale)
        bloc += _ligne("Réseaux sociaux", e.reseaux_sociaux)
        bloc += _ligne("Forces", e.forces)
        bloc += _ligne("Faiblesses", e.faiblesses)
        bloc += _ligne("Opportunités", e.opportunites)
        bloc += _ligne("Menaces", e.menaces)
        score = f"{e.score_pertinence:.2f}" if e.score_pertinence is not None else "-"
        bloc += f"- **Score de pertinence** : {score}\n"
        bloc += _ligne("Source", e.source_url)
        bloc += f"- **Date de collecte** : {e.date_collecte.strftime('%Y-%m-%d')}\n"
        blocs.append(bloc.strip())
    return "\n\n---\n\n".join(blocs)


def _tableau_matrice(entites: list[EntiteAnalysee]) -> str:
    """Matrice de comparaison concurrentielle."""
    lignes = [
        "| Entreprise | Secteur | Produits phares | Certifications | Export | Score |",
        "|------------|---------|-----------------|----------------|--------|-------|",
    ]
    for e in entites:
        produits = ", ".join((e.produits_services or [])[:2]) or "-"
        certifs = ", ".join((e.certifications or [])[:2]) or "-"
        pays = ", ".join((e.pays_export or [])[:2]) or "-"
        score = f"{e.score_pertinence:.2f}" if e.score_pertinence is not None else "-"
        lignes.append(
            f"| {e.nom} | {e.secteur or '-'} | {produits} | {certifs} | {pays} | {score} |"
        )
    return "\n".join(lignes)


def _section_swot_globale(entites: list[EntiteAnalysee], cible: str) -> str:
    """Agrège les SWOT individuelles pour une vue globale."""
    toutes_forces: list[str] = []
    toutes_faiblesses: list[str] = []
    toutes_opportunites: list[str] = []
    toutes_menaces: list[str] = []
    for e in entites:
        toutes_forces.extend(e.forces or [])
        toutes_faiblesses.extend(e.faiblesses or [])
        toutes_opportunites.extend(e.opportunites or [])
        toutes_menaces.extend(e.menaces or [])

    def fmt_liste(items: list[str], max_items: int = 5) -> str:
        seen: set[str] = set()
        unique = []
        for it in items:
            if it.lower() not in seen:
                seen.add(it.lower())
                unique.append(f"• {it}")
        return "\n".join(unique[:max_items]) or "Données insuffisantes"

    return f"""#### Forces observées dans l'écosystème
{fmt_liste(toutes_forces)}

#### Faiblesses / points d'amélioration
{fmt_liste(toutes_faiblesses)}

#### Opportunités
{fmt_liste(toutes_opportunites)}

#### Menaces
{fmt_liste(toutes_menaces)}"""


async def generer_rapport(llm: LLMClient, cible: str, entites: list[EntiteAnalysee]) -> str:
    if not entites:
        return (
            f"# Étude Benchmark — {cible}\n\n"
            "**Résultat** : Aucune entité pertinente identifiée lors de cette exécution.\n\n"
            "> Suggestions : vérifier les clés API de recherche, relancer en mode 'large', "
            "ou vérifier que la connexion Internet est active."
        )

    entites_triees = sorted(entites, key=lambda e: (e.score_pertinence or 0), reverse=True)
    details = formater_entites(entites_triees)
    statistiques = calculer_statistiques(entites_triees)
    matrice = _tableau_matrice(entites_triees)
    swot = _section_swot_globale(entites_triees, cible)

    prompt = (
        PROMPT_SYNTHESE_RAPPORT.format(
            cible=cible,
            nb=len(entites_triees),
            donnees=details,
        )
        + "\n\nStatistiques calculées :\n"
        + formater_statistiques(statistiques)
    )

    try:
        synthese = await llm.generate(prompt)
    except Exception as exc:
        logger.warning(f"Échec génération synthèse : {exc}")
        synthese = "*(Synthèse automatique indisponible — voir les données ci-dessous.)*"

    return f"""# Étude Benchmark Concurrentielle — {cible}

---

## 📊 Matrice Comparative

{matrice}

---

## 📈 Statistiques de Collecte

{formater_statistiques(statistiques)}

---

## 🔍 Analyse SWOT Globale de l'Écosystème

{swot}

---

{synthese.strip()}

---

## 📋 Fiches Détaillées des Acteurs Identifiés

{details}
"""
