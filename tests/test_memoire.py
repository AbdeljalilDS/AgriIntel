import tempfile

import config.settings as settings_module


def test_memoire_stockage_et_similarite():
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    from core import memoire

    memoire.enregistrer("delassus", "Delassus Group", '{"nom": "Delassus Group"}', [1.0, 0.0, 0.0])
    memoire.enregistrer("agri40", "Agri 4.0", '{"nom": "Agri 4.0"}', [0.0, 0.0, 1.0])

    assert len(memoire.lister_tout()) == 2

    resultats = memoire.rechercher_similaire([1.0, 0.0, 0.0], top_k=1)
    assert resultats[0]["nom"] == "Delassus Group"


def test_memoire_repli_mot_cle():
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    from core import memoire

    memoire.enregistrer("cosumar", "Cosumar", '{"nom": "Cosumar"}', None)
    resultats = memoire.rechercher_par_mot_cle("Cosu")
    assert len(resultats) == 1


def test_memoire_preuves_atomiques():
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    from core import memoire

    memoire.enregistrer_preuves("azura", [{
        "type_fait": "technologies",
        "texte": "Azura utilise l'irrigation intelligente",
        "source_url": "https://example.com/azura",
        "date_collecte": "2026-07-31",
        "confiance": 0.9,
        "embedding": [1.0, 0.0],
    }])
    resultats = memoire.rechercher_preuves("irrigation", [1.0, 0.0])
    assert resultats[0]["source"] == "https://example.com/azura"
    assert resultats[0]["type"] == "technologies"


def test_memoire_ignore_les_preuves_hors_sujet():
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    from core import memoire

    memoire.enregistrer_preuves("x", [{
        "type_fait": "technologies",
        "texte": "X utilise l'irrigation intelligente",
        "source_url": "https://example.com/x",
        "date_collecte": "2026-07-31",
        "confiance": 0.9,
        "embedding": [1.0, 0.0],
    }])
    assert memoire.rechercher_preuves("levée de fonds", [0.0, 1.0]) == []
