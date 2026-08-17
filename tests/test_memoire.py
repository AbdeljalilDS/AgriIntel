"""Tests de la mémoire long terme — version async corrigée."""
import tempfile

import pytest

import config.settings as settings_module


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    settings_module.settings.memoire_db = str(tmp_path / "test_memoire.sqlite3")


@pytest.mark.asyncio
async def test_memoire_stockage_et_similarite():
    from core import memoire
    await memoire.enregistrer("delassus", "Delassus Group", '{"nom": "Delassus Group"}', [1.0, 0.0, 0.0])
    await memoire.enregistrer("agri40", "Agri 4.0", '{"nom": "Agri 4.0"}', [0.0, 0.0, 1.0])

    tout = await memoire.lister_tout()
    assert len(tout) == 2

    similaires = await memoire.rechercher_similaire([1.0, 0.0, 0.0], top_k=1)
    assert similaires[0]["nom"] == "Delassus Group"


@pytest.mark.asyncio
async def test_memoire_repli_mot_cle():
    from core import memoire
    await memoire.enregistrer("cosumar", "Cosumar", '{"nom": "Cosumar"}', None)
    resultats = await memoire.rechercher_par_mot_cle("Cosumar", top_k=5)
    assert len(resultats) == 1
    assert resultats[0]["nom"] == "Cosumar"


@pytest.mark.asyncio
async def test_memoire_preuves_atomiques():
    from core import memoire
    await memoire.enregistrer_preuves("azura", [
        {
            "type_fait": "export",
            "texte": "Azura exporte vers l'Europe",
            "source_url": "https://example.com/azura",
            "date_collecte": "2024-01-01",
            "confiance": 0.9,
            "embedding": [1.0, 0.0],
        }
    ])
    resultats = await memoire.rechercher_preuves(
        "export Europe", [1.0, 0.0], top_k=5, seuil=0.0
    )
    assert len(resultats) >= 1
    assert resultats[0]["source"] == "https://example.com/azura"


@pytest.mark.asyncio
async def test_memoire_ignore_les_preuves_hors_sujet():
    from core import memoire
    await memoire.enregistrer_preuves("x", [
        {
            "type_fait": "technologie",
            "texte": "Utilise des capteurs IoT",
            "source_url": "https://example.com",
            "date_collecte": "2024-01-01",
            "confiance": 0.5,
            "embedding": [1.0, 0.0],
        }
    ])
    # Recherche orthogonale avec seuil très élevé → aucun résultat
    resultats = await memoire.rechercher_preuves(
        "levée de fonds", [0.0, 1.0], top_k=5, seuil=0.99
    )
    assert resultats == [], f"Attendu vide, reçu {resultats}"


@pytest.mark.asyncio
async def test_memoire_hybride():
    from core import memoire
    await memoire.enregistrer("saifresh", "Saifresh", '{"nom": "Saifresh", "secteur": "Agriculture"}', [0.5, 0.5, 0.0])
    resultats = await memoire.rechercher_hybride("agriculture Saifresh", [0.5, 0.5, 0.0], top_k=5)
    assert len(resultats) >= 1
    assert resultats[0]["nom"] == "Saifresh"
