"""Tests du JobStore — version async corrigée."""
import pytest

import config.settings as settings_module


@pytest.fixture(autouse=True)
def temp_jobs_db(tmp_path):
    settings_module.settings.jobs_db = str(tmp_path / "test_jobs.sqlite3")


@pytest.mark.asyncio
async def test_job_store_persiste_et_reprend():
    from core.jobs import JobStore

    store = JobStore()
    job_id = await store.creer("benchmark", "Les Domaines Agricoles", "standard")
    await store.mettre_a_jour(job_id, etape="Recherche en cours...")
    job = await store.lire(job_id)

    assert job["statut"] == "en_cours"
    assert job["cible"] == "Les Domaines Agricoles"
    assert job["etape"] == "Recherche en cours..."

    # Simule un redémarrage
    store2 = JobStore()
    interrompus = await store2.reprendre_jobs_interrompus()
    assert job_id in interrompus

    job_apres = await store2.lire(job_id)
    assert job_apres["statut"] == "interrompu"


@pytest.mark.asyncio
async def test_job_store_termine_avec_resultat():
    from core.jobs import JobStore

    store = JobStore()
    job_id = await store.creer("startup", "AgriTech", "large")
    await store.mettre_a_jour(job_id, statut="termine", resultat={"nb_entites": 3, "rapport": "# OK"})
    job = await store.lire(job_id)

    assert job["resultat"]["nb_entites"] == 3
    assert job["statut"] == "termine"


@pytest.mark.asyncio
async def test_job_store_lister_recents():
    from core.jobs import JobStore

    store = JobStore()
    id1 = await store.creer("benchmark", "Cible A", "standard")
    id2 = await store.creer("startup", "Cible B", "large")

    recents = await store.lister_recents(limite=10)
    assert len(recents) == 2
    ids_recents = [j["job_id"] for j in recents]
    assert id1 in ids_recents
    assert id2 in ids_recents
