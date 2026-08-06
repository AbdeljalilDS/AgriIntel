"""Vérifie que la boucle agent (tool-calling) s'enchaîne correctement, avec
un LLM entièrement simulé (pas besoin d'Ollama pour ce test)."""
import tempfile
from unittest.mock import patch

import config.settings as settings_module


def test_boucle_agent_complete():
    settings_module.settings.memoire_db = tempfile.mktemp(suffix=".sqlite3")
    from agent_benchmark.agent import BenchmarkAgent
    from core.llm_client import LLMClient

    class FakeLLM(LLMClient):
        def __init__(self):
            self.tour = 0

        def generate(self, prompt, **kw):
            return "{}"

        def embed(self, texte):
            return [0.1, 0.2, 0.3]

        def chat_avec_outils(self, messages, tools_defs):
            self.tour += 1
            if self.tour == 1:
                return {"role": "assistant", "tool_calls": [{"function": {"name": "rechercher_memoire", "arguments": {"requete": "test"}}}]}
            if self.tour == 2:
                return {"role": "assistant", "tool_calls": [{"function": {"name": "rechercher_web", "arguments": {"requete": "test"}}}]}
            if self.tour == 3:
                return {"role": "assistant", "tool_calls": [{"function": {"name": "lire_page", "arguments": {"url": "https://delassus.ma"}}}]}
            if self.tour == 4:
                return {"role": "assistant", "tool_calls": [{"function": {"name": "enregistrer_entreprise", "arguments": {
                    "nom": "Delassus Group", "secteur": "Agriculture", "source_url": "https://delassus.ma", "score_pertinence": 0.8
                }}}]}
            return {"role": "assistant", "content": "Terminé."}

    llm = FakeLLM()
    agent = BenchmarkAgent(llm)

    with patch("agent_benchmark.tools.fetch_clean_text", return_value="Delassus Group est un leader agroalimentaire."), \
         patch("agent_benchmark.tools.rechercher_avec_repli", return_value=[{"titre": "Delassus", "url": "https://delassus.ma", "contenu": "agriculture"}]):
        entites = agent.run("Les Domaines Agricoles")

    assert llm.tour == 5
    assert len(entites) == 1
    assert entites[0].nom == "Delassus Group"


def test_validation_embedding_refuse_une_page_non_pertinente():
    from agent_benchmark import tools

    class LLMEmbeddings:
        def embed(self, texte):
            return [1.0, 0.0] if "Delassus" in texte or "leader" in texte else [0.0, 1.0]

    tools._derniers_textes_lus.clear()
    tools._derniers_textes_lus["https://example.com"] = "Une page sans rapport avec la fiche."
    resultat = tools.outil_enregistrer_entreprise(
        {"nom": "Delassus Group", "source_url": "https://example.com"}, LLMEmbeddings()
    )
    assert resultat.startswith("Refusé : preuve sémantique")
