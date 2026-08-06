from pathlib import Path

from core.models import EntiteAnalysee
from core.storage import JSONStorage
from core.analytics import calculer_statistiques


def test_entite_cle_normalisee():
    e = EntiteAnalysee(nom="Société Générale Agricole", source_url="https://example.com")
    assert e.cle_normalisee() == "societe generale agricole"


def test_entite_nom_null_textuel_rejete():
    try:
        EntiteAnalysee(nom="null", source_url="https://example.com")
        assert False, "aurait dû être rejeté"
    except Exception:
        pass


def test_entite_nom_liste_garde_premier():
    e = EntiteAnalysee(nom=["Maroc Dattes", "Maroc Bio"], source_url="https://example.com")
    assert e.nom == "Maroc Dattes"


def test_score_invalide_devient_none():
    e = EntiteAnalysee(nom="Test", score_pertinence="", source_url="https://example.com")
    assert e.score_pertinence is None


def test_storage_save(tmp_path):
    storage = JSONStorage(dossier=str(tmp_path))
    entites = [EntiteAnalysee(nom="Test SA", source_url="https://example.com")]
    chemin = storage.save(entites, "test_output")
    assert Path(chemin).exists()


def test_statistiques_sont_calculees_sur_les_donnees_validees():
    entites = [EntiteAnalysee(
        nom="Entreprise A",
        secteur="Agriculture",
        source_url="https://example.com/a",
        technologies=[{"valeur": "Irrigation", "confiance": 0.9}],
    )]
    statistiques = calculer_statistiques(entites)
    assert statistiques["entites_analysees"] == 1
    assert statistiques["sources_distinctes"] == 1
    assert statistiques["secteurs"] == {"Agriculture": 1}
    assert statistiques["technologies_top"] == {"Irrigation": 1}
