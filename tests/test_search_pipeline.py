from unittest.mock import patch

from agent_benchmark.sources import etendre_requete, rechercher_avec_repli, url_scrapable
from agent_benchmark.tools import outil_rechercher_web
from core.models import EntiteAnalysee


def test_requete_et_filtre_url():
    variantes = etendre_requete("Les Domaines Agricoles")
    assert len(variantes) >= 6
    assert url_scrapable("https://example.com/article")
    assert not url_scrapable("https://www.linkedin.com/company/demo")


def test_recherche_fusionne_et_classe_les_resultats():
    resultats = [
        {"titre": "Resultat faible", "url": "https://example.com/faible", "contenu": "agriculture", "score": 0.1},
        {"titre": "Startup agritech Maroc", "url": "https://example.com/fort", "contenu": "startup agritech Maroc financement", "score": 0.8},
    ]
    with patch("agent_benchmark.tools.rechercher_avec_repli", return_value=resultats):
        texte = outil_rechercher_web("startup agritech Maroc")
    assert texte.index("fort") < texte.index("faible")


def test_rechercher_avec_repli_utilise_duckduckgo_sans_tavily():
    with patch("agent_benchmark.sources.rechercher_tavily", return_value=[]), \
         patch("agent_benchmark.sources.rechercher_google", return_value=[]), \
         patch("agent_benchmark.sources.rechercher_duckduckgo", return_value=[{"titre": "Test", "url": "https://example.com/x", "contenu": "agriculture Maroc"}]), \
         patch("agent_benchmark.sources.rechercher_google_news", return_value=[]):
        resultats = rechercher_avec_repli("agriculture Maroc")
    assert len(resultats) >= 1
    assert resultats[0]["url"] == "https://example.com/x"


def test_ancien_format_enrichi_avec_preuve():
    entite = EntiteAnalysee(
        nom="Startup historique",
        source_url="https://example.com/source",
        technologies=["irrigation connectee"],
    )
    assert entite.technologies[0].valeur == "irrigation connectee"
    assert entite.technologies[0].source_url == entite.source_url
    assert entite.technologies[0].date_collecte == entite.date_collecte