import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings
from core.exceptions import LLMError
from core.logger import get_logger

logger = get_logger(__name__)


class LLMClient(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        ...

    async def generate_json(self, prompt: str, system: str | None = None) -> dict:
        raw = await self.generate(prompt, system=system, json_mode=True)
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
    async def chat_avec_outils(self, messages: list[dict], tools: list[dict]) -> dict:
        """Envoie une conversation + une liste d'outils disponibles. Le LLM
        décide lui-même s'il répond directement ou s'il veut utiliser un
        outil (retourne alors un 'tool_calls' dans le message)."""
        ...

    @abstractmethod
    async def embed(self, texte: str) -> list[float] | None:
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
        retry=retry_if_exception_type(httpx.RequestError),
        reraise=True,
    )
    async def generate(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
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
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_timeout)) as client:
            response = await client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            duree = time.perf_counter() - debut
            logger.info(f"LLM generate : {duree:.1f}s (json_mode={json_mode})")
            return response.json().get("response", "")

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=3, max=15),
        retry=retry_if_exception_type(httpx.RequestError),
        reraise=True,
    )
    async def chat_avec_outils(self, messages: list[dict], tools: list[dict]) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": self._options_agent(),
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_timeout)) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            return response.json().get("message", {})

    async def embed(self, texte: str) -> list[float] | None:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": settings.embedding_model, "prompt": texte[:2000]},
                )
                response.raise_for_status()
                return response.json().get("embedding")
        except httpx.RequestError as exc:
            logger.warning(
                f"Embedding indisponible (modèle '{settings.embedding_model}' installé ? "
                f"`ollama pull {settings.embedding_model}`) — repli sur recherche mot-clé. Détail : {exc}"
            )
            return None


class GroqClient(LLMClient):
    """Inférence cloud sur LPU Groq."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.groq_model
        self.api_key = api_key or settings.groq_api_key
        if not self.api_key:
            raise LLMError(
                "GROQ_API_KEY manquante — crée une clé gratuite sur "
                "https://console.groq.com et ajoute-la à ton .env"
            )
        self.base_url = "https://api.groq.com/openai/v1"
        self._embed_client = OllamaClient(model=settings.embedding_model)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _normaliser_pour_groq(messages: list[dict]) -> list[dict]:
        normalises: list[dict] = []
        ids_en_attente: list[str] = []
        total_msgs = len(messages)
        
        for i, m in enumerate(messages):
            m = dict(m)
            is_recent = (total_msgs - i) <= 6
            
            # Compresser le contenu des outils anciens pour éviter 413 Payload Too Large
            if m.get("role") == "tool":
                content = str(m.get("content") or "")
                if not is_recent and len(content) > 600:
                    m["content"] = content[:600] + "\n... [extrait résumé]"
                elif len(content) > 4000:
                    m["content"] = content[:4000] + "\n... [tronqué]"

            if m.get("role") == "assistant" and m.get("tool_calls"):
                tool_calls = []
                ids_en_attente = []
                for j, appel in enumerate(m["tool_calls"]):
                    appel = dict(appel)
                    tool_id = appel.get("id") or f"call_{i}_{j}"
                    appel["id"] = tool_id
                    appel.setdefault("type", "function")
                    fonction = dict(appel.get("function") or {})
                    if not isinstance(fonction.get("arguments"), str):
                        fonction["arguments"] = json.dumps(fonction.get("arguments", {}), ensure_ascii=False)
                    appel["function"] = fonction
                    tool_calls.append(appel)
                    ids_en_attente.append(tool_id)
                m["tool_calls"] = tool_calls
                m.setdefault("content", None)
            elif m.get("role") == "tool" and not m.get("tool_call_id") and ids_en_attente:
                m["tool_call_id"] = ids_en_attente.pop(0)
            normalises.append(m)
            
        # Si encore trop long au total, garder system + user initial + messages récents
        if len(normalises) > 12:
            system_msg = [m for m in normalises[:2] if m.get("role") in ("system", "user")]
            recent_msgs = normalises[-8:]
            normalises = system_msg + recent_msgs

        return normalises

    async def generate(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        models_to_try = [self.model, "llama-3.1-8b-instant", "llama3-70b-8192", "mixtral-8x7b-32768"]
        if self.model in models_to_try:
            models_to_try.remove(self.model)
        models_to_try.insert(0, self.model)

        derniere_erreur = None
        for model_name in models_to_try:
            payload: dict = {"model": model_name, "messages": messages, "temperature": 0.1}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            for tentative in range(3):
                debut = time.perf_counter()
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_timeout)) as client:
                        response = await client.post(
                            f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                        )
                        if response.status_code == 429:
                            logger.warning(f"Groq 429 sur {model_name} (tentative {tentative+1}) -> attente {2 * (tentative+1)}s...")
                            await asyncio.sleep(2.0 * (tentative + 1))
                            continue
                        response.raise_for_status()
                        duree = time.perf_counter() - debut
                        logger.info(f"Groq generate : {duree:.1f}s ({model_name})")
                        return response.json()["choices"][0]["message"].get("content", "") or ""
                except httpx.HTTPStatusError as exc:
                    derniere_erreur = exc
                    if exc.response.status_code == 429:
                        await asyncio.sleep(2.0)
                        continue
                    break
                except httpx.RequestError as exc:
                    derniere_erreur = exc
                    logger.warning(f"Tentative réseau échouée ({model_name}, tentative {tentative+1}) : {exc}")
                    await asyncio.sleep(1.0)
                    continue

        # Tentative de secours automatique vers Ollama local si disponible
        try:
            logger.info("Tentative de repli d'urgence sur Ollama local...")
            local_client = OllamaClient()
            return await local_client.generate(prompt, system=system, json_mode=json_mode)
        except Exception:
            pass

        err_str = str(derniere_erreur)
        if "getaddrinfo" in err_str or "11001" in err_str or "Connect" in err_str:
            raise LLMError(f"Problème de connexion réseau / DNS vers Groq ({err_str}). Vérifiez votre accès internet.")
        raise LLMError(f"Quota Groq temporairement atteint sur les modèles disponibles : {derniere_erreur}")

    async def chat_avec_outils(self, messages: list[dict], tools: list[dict]) -> dict:
        models_to_try = [self.model, "llama-3.1-8b-instant", "llama3-70b-8192"]
        if self.model in models_to_try:
            models_to_try.remove(self.model)
        models_to_try.insert(0, self.model)

        msgs_normalises = self._normaliser_pour_groq(messages)
        derniere_erreur = None

        for model_name in models_to_try:
            payload = {
                "model": model_name,
                "messages": msgs_normalises,
                "tools": tools,
                "temperature": 0.1,
            }
            for tentative in range(3):
                debut = time.perf_counter()
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_timeout)) as client:
                        response = await client.post(
                            f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                        )
                        if response.status_code == 429:
                            logger.warning(f"Groq 429 sur {model_name} (tentative {tentative+1}) -> attente {2 * (tentative+1)}s...")
                            await asyncio.sleep(2.0 * (tentative + 1))
                            continue
                        response.raise_for_status()
                        duree = time.perf_counter() - debut
                        message = response.json()["choices"][0]["message"]
                        logger.info(f"Groq chat_avec_outils : {duree:.1f}s ({model_name})")
                        return message
                except httpx.HTTPStatusError as exc:
                    derniere_erreur = exc
                    if exc.response.status_code == 429:
                        await asyncio.sleep(2.0)
                        continue
                    break
                except httpx.RequestError as exc:
                    derniere_erreur = exc
                    logger.warning(f"Erreur réseau outil ({model_name}, tentative {tentative+1}) : {exc}")
                    await asyncio.sleep(1.0)
                    continue

        # Secours Ollama local
        try:
            logger.info("Secours outil sur Ollama local...")
            local_client = OllamaClient()
            return await local_client.chat_avec_outils(messages, tools)
        except Exception:
            pass

        err_str = str(derniere_erreur)
        if "getaddrinfo" in err_str or "11001" in err_str or "Connect" in err_str:
            raise LLMError(f"Problème de connexion réseau / DNS vers Groq ({err_str}). Vérifiez votre accès internet.")
        raise LLMError(f"Quota Groq temporairement atteint pour les outils : {derniere_erreur}")

    async def embed(self, texte: str) -> list[float] | None:
        return await self._embed_client.embed(texte)


_global_llm_instance: LLMClient | None = None


def get_llm_client(force_new: bool = False) -> LLMClient:
    """Client singleton avec support de réinitialisation dynamique."""
    global _global_llm_instance
    if _global_llm_instance is None or force_new:
        if settings.llm_provider == "groq":
            _global_llm_instance = GroqClient()
        elif settings.llm_provider == "ollama":
            _global_llm_instance = OllamaClient()
        else:
            raise LLMError(f"Fournisseur LLM inconnu : {settings.llm_provider}")
    return _global_llm_instance