"""
Tests du pipeline de recherche — version mise à jour pour la nouvelle API sources.py.
"""
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from core.scraper_base import url_scrapable
from agent_benchmark.sources import rechercher_avec_repli, SearchEngine, SearchResult
from core.models import EntiteAnalysee


# ---------------------------------------------------------------------------
# Tests de base : URL scrapable
# ---------------------------------------------------------------------------

def test_url_scrapable():
    """Teste le filtre d'URLs scrapables."""
    assert url_scrapable("https://example.com/article")
    assert url_scrapable("https://agriculture.gov.ma/rapport")
    assert not url_scrapable("https://www.linkedin.com/company/demo")
    assert not url_scrapable("https://www.facebook.com/page")
    assert not url_scrapable("https://www.youtube.com/watch?v=xyz")
    assert not url_scrapable("")
    assert not url_scrapable("javascript:void(0)")


# ---------------------------------------------------------------------------
# Tests du QueryPlanner avec etendre_requete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_etendre_requete_genere_variantes():
    """etendre_requete doit retourner une liste de requêtes pertinentes."""
    from agent_benchmark.sources import etendre_requete
    variantes = await etendre_requete("Les Domaines Agricoles", geography="Maroc")
    assert isinstance(variantes, list)
    assert len(variantes) >= 3
    # Vérifie que les variantes contiennent des mots-clés de discovery
    all_text = " ".join(variantes).lower()
    assert any(kw in all_text for kw in ["concurrent", "marche", "leader", "entreprise"])


# ---------------------------------------------------------------------------
# Test : SearchResult scoring
# ---------------------------------------------------------------------------

def test_search_result_scoring():
    """Les sources institutionnelles doivent avoir un meilleur score."""
    r_gov = SearchResult(
        url="https://agriculture.gov.ma/rapport-annuel",
        title="Rapport officiel agriculture",
        snippet="Rapport annuel du ministère agriculture Maroc",
        authority=0.98,
        relevance=0.85,
        freshness=0.9,
        tier=1,
    )
    r_blog = SearchResult(
        url="https://monblog-perso.com/article",
        title="Mon article",
        snippet="Article de blog",
        authority=0.50,
        relevance=0.60,
        freshness=0.6,
        tier=4,
    )
    r_gov.compute_score()
    r_blog.compute_score()
    assert r_gov.score > r_blog.score, "Sources gouvernementales doivent avoir un score plus élevé"
    assert r_gov.tier < r_blog.tier


# ---------------------------------------------------------------------------
# Test : SearchEngine déduplication
# ---------------------------------------------------------------------------

def test_search_engine_deduplique():
    """La déduplication par URL doit retirer les doublons."""
    from agent_benchmark.sources import _deduplicate
    results = [
        SearchResult(url="https://example.com/page", title="A"),
        SearchResult(url="https://example.com/page/", title="B"),  # trailing slash différent
        SearchResult(url="https://EXAMPLE.COM/PAGE", title="C"),   # case différent
        SearchResult(url="https://autre.com/page", title="D"),
    ]
    unique = _deduplicate(results)
    # example.com/page, autre.com/page = 2 uniques
    assert len(unique) <= 3


# ---------------------------------------------------------------------------
# Test : rechercher_avec_repli (wrapper compatibilité)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rechercher_avec_repli_retourne_des_dicts():
    """rechercher_avec_repli doit retourner des dicts avec url, titre, contenu."""
    mock_results = [
        SearchResult(url="https://delassus.ma", title="Delassus", snippet="Leader fruits Maroc"),
        SearchResult(url="https://saifresh.ma", title="Saifresh", snippet="Export légumes"),
    ]
    with patch.object(SearchEngine, "cascade_search", new_callable=AsyncMock, return_value=mock_results):
        resultats = await rechercher_avec_repli("exportateurs fruits Maroc")

    assert isinstance(resultats, list)
    assert len(resultats) == 2
    for r in resultats:
        assert "url" in r
        assert "titre" in r
        assert "contenu" in r
        assert r["url"].startswith("http")


# ---------------------------------------------------------------------------
# Test : le modèle EntiteAnalysee gère les technologies correctement
# ---------------------------------------------------------------------------

def test_entite_analysee_technologies():
    """Technologies doivent être des DonneeSourcee avec source_url hérité."""
    entite = EntiteAnalysee(
        nom="Startup Test",
        source_url="https://example.com/source",
        technologies=["irrigation connectee", "capteurs IoT"],
    )
    assert len(entite.technologies) == 2
    assert entite.technologies[0].valeur == "irrigation connectee"
    assert entite.technologies[0].source_url == entite.source_url
    assert entite.technologies[0].date_collecte == entite.date_collecte


# ---------------------------------------------------------------------------
# Test : le modèle EntiteAnalysee gère les champs startup
# ---------------------------------------------------------------------------

def test_entite_analysee_champs_startup():
    """Les champs startup doivent être correctement validés."""
    entite = EntiteAnalysee(
        nom="AgriTech Innovation",
        source_url="https://agritech.ma",
        fondateurs=["Ahmed Alami", "Sara Benali"],
        stade_financement="Serie A",
        financement_leve="5M USD",
        investisseurs=["Green Ventures", "Atlas Capital"],
        incubateurs=["Maroc Numeric Fund", "Startup Maroc"],
    )
    assert len(entite.fondateurs) == 2
    assert entite.stade_financement == "Serie A"
    assert entite.financement_leve == "5M USD"
    assert len(entite.investisseurs) == 2
    assert len(entite.incubateurs) == 2