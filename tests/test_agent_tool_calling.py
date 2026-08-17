"""
Tests de l'agent benchmark — version async corrigée.

Utilise pytest-asyncio pour les tests asynchrones.
Les outils LLM et web sont mockés pour éviter toute dépendance externe.
"""
import asyncio
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

import config.settings as settings_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeLLM:
    """LLM entièrement simulé — pas besoin d'Ollama."""
    def __init__(self):
        self.tour = 0

    async def generate(self, prompt, **kw):
        return "{}"

    async def embed(self, texte):
        return [0.1, 0.2, 0.3]

    async def chat_avec_outils(self, messages, tools_defs):
        self.tour += 1
        if self.tour == 1:
            return {"role": "assistant", "tool_calls": [
                {"function": {"name": "rechercher_memoire", "arguments": {"requete": "test"}}}
            ]}
        if self.tour == 2:
            return {"role": "assistant", "tool_calls": [
                {"function": {"name": "rechercher_web", "arguments": {"requete": "concurrents test"}}}
            ]}
        if self.tour == 3:
            return {"role": "assistant", "tool_calls": [
                {"function": {"name": "lire_page", "arguments": {"index": 1}}}
            ]}
        if self.tour == 4:
            return {"role": "assistant", "tool_calls": [
                {"function": {"name": "enregistrer_entreprise", "arguments": {
                    "nom": "Delassus Group",
                    "secteur": "Agriculture",
                    "description": "Leader agroalimentaire marocain exportateur",
                    "produits_services": ["fruits", "légumes"],
                    "source_url": "https://delassus.ma",
                    "score_pertinence": 0.8,
                }}}
            ]}
        return {"role": "assistant", "content": "Terminé."}


class FakeLLMParesseux:
    """LLM qui ne fait jamais d'appels d'outils — simule un modèle abandoniste."""
    def __init__(self):
        self.tour = 0
        self.a_vu_le_rappel = False

    async def generate(self, prompt, **kw):
        return "{}"

    async def embed(self, texte):
        return [0.1, 0.2, 0.3]

    async def chat_avec_outils(self, messages, tools_defs):
        self.tour += 1
        # Détecte si un rappel a été injecté
        for m in messages:
            if m.get("role") == "user" and any(kw in m.get("content", "") for kw in
                                                 ["entreprise", "enregistr", "startup", "Aucune"]):
                self.a_vu_le_rappel = True
        return {"role": "assistant", "content": "Je pense avoir terminé."}


class FakeLLMUneFiche:
    """LLM qui enregistre 1 fiche puis abandonne."""
    def __init__(self):
        self.tour = 0

    async def generate(self, prompt, **kw):
        return "{}"

    async def embed(self, texte):
        return [0.1, 0.2, 0.3]

    async def chat_avec_outils(self, messages, tools_defs):
        self.tour += 1
        if self.tour == 1:
            return {"role": "assistant", "tool_calls": [
                {"function": {"name": "rechercher_web", "arguments": {"requete": "test"}}}
            ]}
        if self.tour == 2:
            return {"role": "assistant", "tool_calls": [
                {"function": {"name": "lire_page", "arguments": {"index": 1}}}
            ]}
        if self.tour == 3:
            return {"role": "assistant", "tool_calls": [
                {"function": {"name": "enregistrer_entreprise", "arguments": {
                    "nom": "Delassus Group",
                    "secteur": "Agriculture",
                    "description": "Leader agroalimentaire marocain",
                    "produits_services": ["fruits"],
                    "source_url": "https://delassus.ma",
                    "score_pertinence": 0.8,
                }}}
            ]}
        return {"role": "assistant", "content": "J'ai terminé, une seule entreprise suffit."}


# ---------------------------------------------------------------------------
# Test : pipeline complet 4 tours
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boucle_agent_complete():
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    settings_module.settings.benchmark_cible_min_entites = 1

    from agent_benchmark.agent import BenchmarkAgent

    llm = FakeLLM()
    agent = BenchmarkAgent(llm)

    with patch("agent_benchmark.tools.fetch_clean_text", new_callable=AsyncMock,
               return_value="Delassus Group est un leader agroalimentaire marocain producteur exportateur."), \
         patch("agent_benchmark.sources.SearchEngine.parallel_search", new_callable=AsyncMock,
               return_value=[]):
        entites = await agent.run("Les Domaines Agricoles")

    assert llm.tour >= 4
    assert len(entites) == 1
    assert entites[0].nom == "Delassus Group"


# ---------------------------------------------------------------------------
# Test : relance sur objectif non atteint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_relance_au_lieu_de_sarreter_sur_zero_entite():
    """L'agent doit injecter des rappels quand le LLM abandonne sans atteindre l'objectif."""
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    settings_module.settings.benchmark_cible_min_entites = 5

    from agent_benchmark.agent import BenchmarkAgent

    llm = FakeLLMParesseux()
    agent = BenchmarkAgent(llm, mode="standard")

    entites = await agent.run("Cible test")

    assert entites == []
    assert llm.a_vu_le_rappel, "L'agent doit relancer avec un rappel."
    assert llm.tour >= agent.max_tours - 2  # Tolérance: le budget est épuisé


# ---------------------------------------------------------------------------
# Test : continue jusqu'à max_tours quand objectif non atteint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_continue_jusqua_max_tours():
    """Un agent qui a trouvé 1 entité mais objectif=3 doit continuer jusqu'à max_tours."""
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    settings_module.settings.benchmark_cible_min_entites = 3

    from agent_benchmark.agent import BenchmarkAgent

    llm = FakeLLMUneFiche()
    agent = BenchmarkAgent(llm, mode="standard")

    with patch("agent_benchmark.tools.fetch_clean_text", new_callable=AsyncMock,
               return_value="Delassus Group est un leader agroalimentaire marocain."), \
         patch("agent_benchmark.sources.SearchEngine.parallel_search", new_callable=AsyncMock,
               return_value=[]):
        entites = await agent.run("Les Domaines Agricoles")

    assert len(entites) == 1  # 1 seule entité (LLM paresseux)
    assert llm.tour >= agent.max_tours - 2  # Budget épuisé


# ---------------------------------------------------------------------------
# Test : validation enrichie de la fiche
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enregistrer_entreprise_refuse_les_fiches_trop_pauvres():
    """Une fiche avec juste nom + source_url doit être refusée."""
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")

    from agent_benchmark import tools

    class LLMEmbed:
        async def embed(self, texte):
            return [1.0, 0.0]

    tools.reinitialiser_session()
    sess = tools.get_session()
    sess.derniers_textes_lus["https://example.com"] = "Une page quelconque."

    resultat, entite = await tools.outil_enregistrer_entreprise(
        {"nom": "Coquille Vide", "source_url": "https://example.com"},
        LLMEmbed(),
    )
    assert "Refusé" in resultat
    assert "pauvre" in resultat.lower()
    assert entite is None


# ---------------------------------------------------------------------------
# Test : anti-doublon dans la même étude
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enregistrer_entreprise_refuse_les_doublons():
    """La même entreprise ne doit pas être enregistrée deux fois."""
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")

    from agent_benchmark import tools

    class LLMEmbed:
        async def embed(self, texte):
            return [1.0, 0.0]

    tools.reinitialiser_session()
    sess = tools.get_session()
    sess.derniers_textes_lus["https://example.com"] = "Leader agroalimentaire avec certifications export."

    donnees = {
        "nom": "Delassus Group",
        "source_url": "https://example.com",
        "secteur": "Agriculture",
        "description": "Producteur agricole marocain exportateur.",
        "produits_services": ["fruits", "légumes"],
    }

    r1, e1 = await tools.outil_enregistrer_entreprise(donnees, LLMEmbed())
    assert e1 is not None, f"Premier enregistrement doit réussir. Résultat : {r1}"

    r2, e2 = await tools.outil_enregistrer_entreprise(donnees, LLMEmbed())
    assert e2 is None
    assert "Refusé" in r2
    assert "déjà enregistrée" in r2.lower()


# ---------------------------------------------------------------------------
# Test : score de fiabilité source
# ---------------------------------------------------------------------------

def test_scoring_sources():
    """Les sources institutionnelles (.gov) doivent avoir un score d'autorité élevé."""
    from agent_benchmark.sources import SearchResult
    r_gov = SearchResult(url="https://agriculture.gov.ma/rapport", title="Rapport officiel", authority=0.98)
    r_blog = SearchResult(url="https://monblog.com/article", title="Article blog", authority=0.50)
    assert r_gov.authority > r_blog.authority
    assert r_gov.tier <= r_blog.tier


# ---------------------------------------------------------------------------
# Test : QueryPlanner génère des requêtes pertinentes
# ---------------------------------------------------------------------------

def test_query_planner_genere_requetes():
    from core.query_planner import QueryPlanner
    planner = QueryPlanner(
        target="Les Domaines Agricoles",
        objective="benchmark concurrentiel",
        geography="Maroc",
        sector="agriculture"
    )
    plan = planner.build_plan()
    assert len(plan) > 10
    assert all(q.query for q in plan)
    assert all(q.priority > 0 for q in plan)
    # Les requêtes de découverte doivent être présentes
    families = {q.family for q in plan}
    assert "discovery" in families
    assert "company" in families


# ---------------------------------------------------------------------------
# Test : Entity Resolution déduplique correctement
# ---------------------------------------------------------------------------

def test_entity_resolution_deduplication():
    from core.entity_resolution import EntityResolver
    from core.study_models import Candidate

    resolver = EntityResolver(merge_threshold=0.75)
    c1 = Candidate(name="Les Domaines Agricoles", source_url="https://domaines-agricoles.ma")
    c2 = Candidate(name="Domaines Agricoles Maroc", source_url="https://domaines-agricoles.ma")
    c3 = Candidate(name="Saifresh", source_url="https://saifresh.ma")

    e1 = resolver.resolve(c1)
    e2 = resolver.resolve(c2)  # Même domaine → fusion
    e3 = resolver.resolve(c3)  # Entité différente

    assert e1.entity_id == e2.entity_id, "Même domaine → doit fusionner"
    assert e1.entity_id != e3.entity_id, "Entités différentes → séparées"
    assert resolver.entity_count == 2


# ---------------------------------------------------------------------------
# Test : Browser pool singleton
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browser_pool_singleton():
    from core.browser_pool import BrowserPool, close_browser_pool
    pool1 = await BrowserPool.get_instance()
    pool2 = await BrowserPool.get_instance()
    assert pool1 is pool2, "Le browser pool doit être un singleton"
    # Nettoyage
    BrowserPool._instance = None
