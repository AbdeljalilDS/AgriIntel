"""Tests de persistance des jobs."""
import tempfile

import config.settings as settings_module


def test_job_store_persiste_et_reprend():
    settings_module.settings.jobs_db = tempfile.mktemp(suffix=".sqlite3")
    from core.jobs import JobStore

    store = JobStore()
    job_id = store.creer("benchmark", "Les Domaines Agricoles", "standard")
    store.mettre_a_jour(job_id, etape="Recherche en cours...")
    job = store.lire(job_id)
    assert job["statut"] == "en_cours"
    assert job["cible"] == "Les Domaines Agricoles"
    assert job["etape"] == "Recherche en cours..."

    store2 = JobStore()
    store2.mettre_a_jour(job_id, statut="en_cours", etape="Encore actif")
    interrompus = store2.reprendre_jobs_interrompus()
    assert job_id in interrompus
    job_apres = store2.lire(job_id)
    assert job_apres["statut"] == "interrompu"


def test_job_store_termine_avec_resultat():
    settings_module.settings.jobs_db = tempfile.mktemp(suffix=".sqlite3")
    from core.jobs import JobStore

    store = JobStore()
    job_id = store.creer("startup", "AgriTech", "large")
    store.mettre_a_jour(job_id, statut="termine", resultat={"nb_entites": 3, "rapport": "# OK"})
    job = store.lire(job_id)
    assert job["resultat"]["nb_entites"] == 3
