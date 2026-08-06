from core.models import EntiteAnalysee, DonneeSourcee


def _preuves(entites: list[EntiteAnalysee]) -> list[dict]:
    resultats = []
    vus = set()
    for entite in entites:
        for champ in ("technologies", "competences", "investissements", "innovations", "innovations_recentes"):
            for preuve in getattr(entite, champ):
                if not isinstance(preuve, DonneeSourcee) or not preuve.source_url:
                    continue
                cle = (preuve.source_url, preuve.date_collecte.isoformat() if preuve.date_collecte else None)
                if cle in vus:
                    continue
                vus.add(cle)
                resultats.append({
                    "source": preuve.source_url,
                    "date": preuve.date_collecte.isoformat() if preuve.date_collecte else None,
                    "confiance": preuve.confiance,
                    "entite": entite.nom,
                    "donnee": preuve.valeur,
                })
        if entite.source_url and entite.source_url not in vus:
            vus.add(entite.source_url)
            resultats.append({"source": entite.source_url, "date": entite.date_collecte.isoformat(), "confiance": entite.score_pertinence, "entite": entite.nom, "donnee": entite.description or entite.nom})
    return resultats


def verifier_reponse(question: str, reponse: str, entites: list[EntiteAnalysee], citations_documents: list[dict] | None = None) -> dict:
    preuves = _preuves(entites)
    preuves.extend(citations_documents or [])
    stopwords = {"donne", "donner", "quels", "quelles", "avec", "pourquoi", "faire", "rapport", "sources", "limites", "statistiques", "exécutif", "executif"}
    tokens = {token.casefold() for token in question.split() if len(token) > 3 and token.casefold() not in stopwords}
    classees = []
    for preuve in preuves:
        texte = f"{preuve['entite']} {preuve['donnee']}".casefold()
        score = sum(token in texte for token in tokens)
        if score:
            classees.append((score, preuve))
    classees.sort(key=lambda item: item[0], reverse=True)
    retenues = [preuve for _, preuve in classees[:8]]
    scores = [p["confiance"] for p in retenues if p["confiance"] is not None and p["confiance"] > 0]
    confiance = round(sum(scores) / len(scores), 2) if scores else None
    verifiee = bool(reponse.strip()) and bool(retenues) and bool(scores)
    return {
        "verifiee": verifiee,
        "niveau": "élevé" if confiance is not None and confiance >= 0.75 else "moyen" if confiance is not None and confiance >= 0.45 else "à confirmer",
        "confiance": confiance,
        "citations": retenues,
        "message": "Réponse appuyée par des preuves confiantes." if verifiee else "Des citations existent, mais leur niveau de confiance n'est pas documenté.",
    }