from collections import Counter
import unicodedata

from core.models import DonneeSourcee, EntiteAnalysee, valeur_affichage


def _valeurs(entites: list[EntiteAnalysee], champ: str) -> list[str]:
    valeurs = []
    for entite in entites:
        for item in getattr(entite, champ, []):
            valeurs.append(valeur_affichage(item))
    return [valeur for valeur in valeurs if valeur]


def _canonique(valeur: str) -> str:
    texte = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode().casefold().strip()
    correspondances = {
        "agritech": "Agritech",
        "agriculture": "Agriculture",
        "agrifoodtech": "Agrifoodtech",
        "agroalimentaire": "Agroalimentaire",
        "logistique agricole": "Logistique agricole",
    }
    return correspondances.get(texte, valeur.strip())


def _valeurs_propres(entites: list[EntiteAnalysee], champ: str) -> list[str]:
    generiques = {"innovation", "investissement", "technologie", "competence", "expertise"}
    return [_canonique(valeur) for valeur in _valeurs(entites, champ) if valeur.casefold() not in generiques]


def calculer_statistiques(entites: list[EntiteAnalysee]) -> dict:
    secteurs = Counter(_canonique(entite.secteur) for entite in entites if entite.secteur)
    technologies = Counter(_valeurs_propres(entites, "technologies"))
    competences = Counter(_valeurs_propres(entites, "competences"))
    investissements = Counter(_valeurs_propres(entites, "investissements"))
    innovations = Counter(_valeurs_propres(entites, "innovations"))
    confiances = []
    sources = set()
    for entite in entites:
        if entite.source_url:
            sources.add(entite.source_url)
        for champ in ("technologies", "competences", "investissements", "innovations", "innovations_recentes"):
            for preuve in getattr(entite, champ):
                if isinstance(preuve, DonneeSourcee):
                    if preuve.source_url:
                        sources.add(preuve.source_url)
                    if preuve.confiance is not None and preuve.confiance > 0:
                        confiances.append(preuve.confiance)
    moyenne = round(sum(confiances) / len(confiances), 2) if confiances else None
    return {
        "entites_analysees": len(entites),
        "sources_distinctes": len(sources),
        "secteurs": dict(secteurs.most_common(10)),
        "technologies_top": dict(technologies.most_common(10)),
        "competences_top": dict(competences.most_common(10)),
        "investissements_top": dict(investissements.most_common(10)),
        "innovations_top": dict(innovations.most_common(10)),
        "confiance_moyenne": moyenne,
        "preuves_avec_confiance": len(confiances),
        "preuves_sans_confiance": max(0, sum(len(getattr(e, champ)) for e in entites for champ in ("technologies", "competences", "investissements", "innovations", "innovations_recentes")) - len(confiances)),
    }


def formater_statistiques(statistiques: dict) -> str:
    lignes = [
        f"- Entités analysées : {statistiques['entites_analysees']}",
        f"- Sources distinctes : {statistiques['sources_distinctes']}",
        f"- Confiance moyenne : {statistiques['confiance_moyenne'] if statistiques['confiance_moyenne'] is not None else 'non calculable'}",
        f"- Secteurs : {statistiques['secteurs'] or 'aucun'}",
        f"- Technologies les plus fréquentes : {statistiques['technologies_top'] or 'aucune'}",
        f"- Innovations les plus fréquentes : {statistiques['innovations_top'] or 'aucune'}",
        f"- Documents utilisateur : {statistiques.get('documents_fournis', 0)}",
        f"- Passages documentaires sélectionnés : {statistiques.get('passages_documentaires', 0)}",
    ]
    return "\n".join(lignes)