import json
import re
import time
from abc import ABC, abstractmethod
from functools import lru_cache

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings
from core.exceptions import LLMError
from core.logger import get_logger

logger = get_logger(__name__)


class LLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        ...

    def generate_json(self, prompt: str, system: str | None = None) -> dict:
        raw = self.generate(prompt, system=system, json_mode=True)
        cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            raise LLMError(f"Réponse LLM non parsable en JSON : {raw[:300]}") from exc

    @abstractmethod
    def chat_avec_outils(self, messages: list[dict], tools: list[dict]) -> dict:
        """Envoie une conversation + une liste d'outils disponibles. Le LLM
        décide lui-même s'il répond directement ou s'il veut utiliser un
        outil (retourne alors un 'tool_calls' dans le message)."""
        ...

    @abstractmethod
    def embed(self, texte: str) -> list[float] | None:
        """Transforme un texte en vecteur numérique (pour la mémoire par
        similarité). Retourne None si le modèle d'embedding n'est pas
        disponible — l'appelant doit alors se rabattre sur une recherche
        par mot-clé plutôt que planter."""
        ...


class OllamaClient(LLMClient):
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or settings.ollama_model
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    def _options_chat(self) -> dict:
        opts: dict = {
            "num_predict": settings.ollama_num_predict_chat,
            "temperature": 0.1,
            "num_ctx": settings.ollama_num_ctx_chat,
        }
        if settings.ollama_num_thread > 0:
            opts["num_thread"] = settings.ollama_num_thread
        return opts

    def _options_agent(self) -> dict:
        opts: dict = {
            "num_predict": settings.ollama_num_predict_agent,
            "temperature": 0.1,
            "num_ctx": settings.ollama_num_ctx_agent,
        }
        if settings.ollama_num_thread > 0:
            opts["num_thread"] = settings.ollama_num_thread
        return opts

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=3, max=15),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        options = self._options_chat()
        if json_mode:
            options["num_predict"] = settings.ollama_num_predict_json
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": options,
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        debut = time.perf_counter()
        response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=settings.llm_timeout)
        response.raise_for_status()
        duree = time.perf_counter() - debut
        logger.info(f"LLM generate : {duree:.1f}s (json_mode={json_mode})")
        return response.json().get("response", "")

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=3, max=15),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def chat_avec_outils(self, messages: list[dict], tools: list[dict]) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": self._options_agent(),
        }
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=settings.llm_timeout)
        response.raise_for_status()
        return response.json().get("message", {})

    def embed(self, texte: str) -> list[float] | None:
        try:
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": settings.embedding_model, "prompt": texte[:2000]},
                timeout=60,
            )
            response.raise_for_status()
            return response.json().get("embedding")
        except requests.RequestException as exc:
            logger.warning(
                f"Embedding indisponible (modèle '{settings.embedding_model}' installé ? "
                f"`ollama pull {settings.embedding_model}`) — repli sur recherche mot-clé. Détail : {exc}"
            )
            return None


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """Client singleton — évite de recharger le modèle Ollama à chaque requête."""
    if settings.llm_provider == "ollama":
        return OllamaClient()
    raise LLMError(f"Fournisseur LLM inconnu : {settings.llm_provider}")
