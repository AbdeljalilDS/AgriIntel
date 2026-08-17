"""
Browser Pool — gestion d'un pool singleton de browsers Playwright.

Principes (8 Go RAM) :
- 1 seul browser Chromium lancé (pas N browsers)
- N BrowserContext isolés (légers) pour la concurrence
- Semaphore pour limiter le parallélisme
- Réutilisation du browser entre les requêtes
- Fermeture propre en fin d'étude
- Fallback HTTP si Playwright indisponible

Architecture inspirée de Perplexity / Gemini Deep Research browser agents.
"""
from __future__ import annotations

import asyncio
import random
from urllib.parse import urlsplit

from core.logger import get_logger

logger = get_logger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

DOMAINS_NO_BROWSER = frozenset({
    "news.google.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "tiktok.com", "youtube.com",
    "linkedin.com", "pinterest.com", "reddit.com",
})


class BrowserPool:
    """
    Pool singleton de browser Playwright.
    - 1 browser Chromium partagé
    - max_contexts contextes simultanés (configurables, défaut 2 pour 8 Go RAM)
    - Semaphore pour limiter la concurrence
    """

    _instance: "BrowserPool | None" = None
    _lock: asyncio.Lock | None = None

    def __init__(self, max_contexts: int = 2, timeout_ms: int = 25_000):
        self._max_contexts = max_contexts
        self._timeout_ms   = timeout_ms
        self._browser      = None
        self._playwright   = None
        self._semaphore    = asyncio.Semaphore(max_contexts)
        self._initialized  = False
        self._available    = True  # False si Playwright non installé

    @classmethod
    async def get_instance(cls, max_contexts: int = 2) -> "BrowserPool":
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(max_contexts=max_contexts)
            return cls._instance

    async def _ensure_browser(self) -> bool:
        """Lance le browser si pas encore démarré. Retourne False si Playwright indisponible."""
        if self._initialized:
            return self._available
        self._initialized = True
        try:
            from playwright.async_api import async_playwright
            self._playwright_ctx = async_playwright()
            self._playwright = await self._playwright_ctx.__aenter__()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--disable-gpu",
                    "--memory-pressure-off",
                    "--max_old_space_size=512",
                ],
            )
            self._available = True
            logger.info(f"Browser Pool initialisé (max_contexts={self._max_contexts})")
        except ImportError:
            logger.warning("Playwright non installé — browser désactivé")
            self._available = False
        except Exception as exc:
            logger.warning(f"Browser Pool échec init : {exc}")
            self._available = False
        return self._available

    async def fetch(
        self,
        url: str,
        timeout_ms: int | None = None,
        wait_for: str = "domcontentloaded",
        scroll: bool = True,
    ) -> str | None:
        """
        Récupère le HTML d'une URL via Playwright.
        Retourne None si la page est inaccessible ou si Playwright est désactivé.
        """
        domain = urlsplit(url).netloc.lower().replace("www.", "")
        if any(d in domain for d in DOMAINS_NO_BROWSER):
            return None

        if not await self._ensure_browser():
            return None

        async with self._semaphore:
            context = None
            page = None
            try:
                context = await self._browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=True,
                )
                page = await context.new_page()

                # Bloquer ressources inutiles pour économiser RAM/bande passante
                await page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot}",
                    lambda route: route.abort()
                )

                ms = timeout_ms or self._timeout_ms
                await page.goto(url, timeout=ms, wait_until=wait_for)

                # Attendre networkidle si possible
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass

                # Scroll pour charger le contenu lazy
                if scroll:
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                        await asyncio.sleep(0.3)
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(0.2)
                    except Exception:
                        pass

                html = await page.content()
                logger.debug(f"Browser fetch OK : {url[:60]} ({len(html)} chars)")
                return html

            except Exception as exc:
                logger.warning(f"Browser fetch échec {url[:60]} : {exc}")
                return None
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass

    async def fetch_with_network(self, url: str) -> tuple[str | None, list[dict]]:
        """
        Récupère le HTML ET les appels réseau JSON (XHR/fetch).
        Utile pour les pages qui chargent leurs données via API.
        Retourne (html, [{"url": ..., "body": ...}])
        """
        if not await self._ensure_browser():
            return None, []

        async with self._semaphore:
            context = None
            page = None
            api_responses: list[dict] = []

            try:
                context = await self._browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    ignore_https_errors=True,
                )
                page = await context.new_page()

                # Intercepter les réponses JSON
                async def handle_response(response):
                    try:
                        ct = response.headers.get("content-type", "")
                        if "json" in ct and response.status == 200:
                            body = await response.text()
                            if len(body) < 100_000:  # limite 100 Ko
                                api_responses.append({"url": response.url, "body": body})
                    except Exception:
                        pass

                page.on("response", handle_response)

                await page.goto(url, timeout=self._timeout_ms, wait_until="networkidle")
                html = await page.content()
                return html, api_responses

            except Exception as exc:
                logger.warning(f"Browser network fetch échec {url[:60]} : {exc}")
                return None, []
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass

    async def close(self) -> None:
        """Ferme proprement le browser."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        self._browser    = None
        self._playwright = None
        self._initialized = False
        self._available   = True
        BrowserPool._instance = None
        logger.info("Browser Pool fermé")


# ---------------------------------------------------------------------------
# Helper public
# ---------------------------------------------------------------------------

async def browser_fetch(url: str, max_contexts: int = 2) -> str | None:
    """Raccourci pour utiliser le pool singleton."""
    pool = await BrowserPool.get_instance(max_contexts=max_contexts)
    return await pool.fetch(url)


async def close_browser_pool() -> None:
    """Ferme le pool singleton."""
    if BrowserPool._instance:
        await BrowserPool._instance.close()
