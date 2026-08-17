"""
Moteur de recherche multi-providers — Enterprise AI Research Engine.

Providers disponibles (par ordre de priorité / qualité) :
  1. Tavily API         → résultats frais + extraits de contenu
  2. Google CSE         → résultats Google via API officielle
  3. Bing Web Search    → résultats Bing via API officielle
  4. Brave Search API   → API sans traçage, bons résultats
  5. DuckDuckGo         → fallback gratuit sans clé
  6. DuckDuckGo News    → actualités fraîches
  7. Common Crawl Index → index Open Web (institutionnel)
  8. Google News (RSS)  → flux RSS Google News
  9. Sites sectoriels   → domaines spécialisés via DuckDuckGo
 10. Repli en cascade   → essaie tous les providers jusqu'à résultat

Architecture :
  - Résultats normalisés dans SearchResult
  - Déduplication par URL
  - Scoring multi-critères (relevance, authority, freshness, tier)
  - Parallel search avec semaphore (respecte les rate limits)
  - Quota manager Tavily
  - Cache de recherches

Inspiré de : Perplexity, Gemini Deep Research, OpenAI Deep Research.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlsplit

import httpx

from config.settings import settings
from core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Modèle de résultat normalisé
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    url:        str
    title:      str = ""
    snippet:    str = ""
    domain:     str = ""
    provider:   str = ""
    # Score de qualité composite
    relevance:  float = 0.0
    authority:  float = 0.0
    freshness:  float = 0.0
    tier:       int   = 4         # 1=gouvernement/officiel → 5=forum
    score:      float = 0.0       # score global calculé
    # Métadonnées
    published_at: str = ""
    language:   str = ""
    # Accès
    accessible: bool = True

    def __post_init__(self):
        if not self.domain:
            try:
                self.domain = urlsplit(self.url).netloc.lower().replace("www.", "")
            except Exception:
                self.domain = ""
        if self.score == 0.0:
            self.compute_score()

    def compute_score(self) -> None:
        self.score = round(
            0.35 * self.relevance +
            0.30 * self.authority +
            0.20 * self.freshness +
            0.15 * (1.0 - (self.tier - 1) / 4),
            4,
        )


# ---------------------------------------------------------------------------
# Scoring des sources
# ---------------------------------------------------------------------------

# Domaines haute autorité par secteur
HIGH_AUTHORITY_DOMAINS: dict[str, float] = {
    # Gouvernement + régulateurs
    "gov.ma": 0.95, "agriculture.gov.ma": 0.98, "mapmdref.gov.ma": 0.98,
    "eacce.gov.ma": 0.95, "anpme.gov.ma": 0.90,
    "gov.tn": 0.92, "gov.dz": 0.92, "onssa.gov.ma": 0.95,
    "hcp.ma": 0.95, "cmpe.gov.ma": 0.90,
    # Institutions internationales
    "worldbank.org": 0.95, "fao.org": 0.95, "ifad.org": 0.90,
    "ifc.org": 0.90, "imf.org": 0.92, "unctad.org": 0.90,
    # Presse économique
    "ledesk.ma": 0.80, "le360.ma": 0.78, "telquel.ma": 0.78,
    "medias24.com": 0.80, "usine-nouvelle.com": 0.82, "les-echos.fr": 0.85,
    "reuters.com": 0.90, "bloomberg.com": 0.90,
    # Plateformes pro
    "linkedin.com": 0.75, "crunchbase.com": 0.85, "glassdoor.com": 0.72,
    # Bases de données entreprises
    "societe.com": 0.80, "pappers.fr": 0.80, "opencorporates.com": 0.80,
    "kompass.com": 0.82, "europages.com": 0.78, "dnb.com": 0.82,
}

# Domaines toujours à exclure
EXCLUDED_DOMAINS: frozenset = frozenset({
    "youtube.com", "facebook.com", "instagram.com", "tiktok.com",
    "pinterest.com", "twitter.com", "x.com", "reddit.com",
    "quora.com", "stackoverflow.com", "answers.yahoo.com",
    "amazon.com", "ebay.com", "aliexpress.com",
    "wikipedia.org",  # on garde Wikipedia comme source secondaire seulement
})

TIER_1_PATTERNS = ("gov.", ".gouv.", "agriculture.", "ministere.", "ministry.", "fao.", "worldbank.")
TIER_2_PATTERNS = ("worldbank", "imf.org", "unctad", "university.", "univ.", ".edu", ".ac.")
TIER_3_PATTERNS = ("reuters", "bloomberg", "les-echos", "ft.com", "economist.com",
                    "medias24", "ledesk", "le360", "telquel", "businessnews")


def _tier(domain: str, url: str) -> int:
    u = (domain + url).lower()
    if any(p in u for p in TIER_1_PATTERNS):
        return 1
    if any(p in u for p in TIER_2_PATTERNS):
        return 2
    if any(p in u for p in TIER_3_PATTERNS):
        return 3
    return 4


def _authority(domain: str) -> float:
    for suffix, score in HIGH_AUTHORITY_DOMAINS.items():
        if domain == suffix or domain.endswith("." + suffix):
            return score
    # Heuristic : .gov, .edu, .int = haute autorité
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    if tld in ("gov", "edu", "int", "org"):
        return 0.80
    return 0.50


def _freshness(published_at: str) -> float:
    if not published_at:
        return 0.40  # neutre si date inconnue
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        jours = (datetime.now(timezone.utc) - dt).days
        if jours < 30:
            return 1.0
        if jours < 90:
            return 0.85
        if jours < 180:
            return 0.70
        if jours < 365:
            return 0.55
        return 0.35
    except Exception:
        return 0.40


def _normaliser(resultats_bruts: list[dict]) -> list[SearchResult]:
    """Normalise des résultats bruts en SearchResult."""
    resultats: list[SearchResult] = []
    for r in resultats_bruts:
        url = r.get("url") or r.get("href") or r.get("link") or ""
        if not url or not url.startswith("http"):
            continue
        domain = urlsplit(url).netloc.lower().replace("www.", "")
        if any(d in domain for d in EXCLUDED_DOMAINS):
            continue
        auth = _authority(domain)
        tier = _tier(domain, url)
        pub = r.get("published_date") or r.get("date") or r.get("published_at") or ""
        fresh = _freshness(pub)
        rel = float(r.get("score") or r.get("relevance") or 0.65)
        sr = SearchResult(
            url         = url,
            title       = (r.get("title") or "")[:200],
            snippet     = (r.get("content") or r.get("snippet") or r.get("body") or "")[:500],
            domain      = domain,
            provider    = r.get("provider", ""),
            relevance   = rel,
            authority   = auth,
            freshness   = fresh,
            tier        = tier,
            published_at= pub,
        )
        sr.compute_score()
        resultats.append(sr)
    return resultats


def _deduplicate(results: list[SearchResult]) -> list[SearchResult]:
    """Déduplique par URL exacte + URL normalisée."""
    vues: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        key = r.url.rstrip("/").lower().split("?")[0]
        if key not in vues:
            vues.add(key)
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class SearchProvider:
    name = "base"
    default_max = 8

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        raise NotImplementedError


class TavilyProvider(SearchProvider):
    name = "tavily"
    default_max = 8

    def __init__(self):
        self.api_key = settings.tavily_api_key
        self._client = httpx.AsyncClient(timeout=20)

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        if not self.api_key:
            return []
        from core.quota import quota_disponible, consommer
        if not quota_disponible("tavily", settings.tavily_monthly_limit):
            logger.warning("Quota Tavily épuisé")
            return []
        n = max_results or self.default_max
        try:
            r = await self._client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": n,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            consommer("tavily", settings.tavily_monthly_limit)
            resultats = []
            for item in data.get("results", []):
                item["provider"] = self.name
                resultats.append(item)
            return _normaliser(resultats)
        except Exception as exc:
            logger.warning(f"Tavily error: {exc}")
            return []


class GoogleCSEProvider(SearchProvider):
    name = "google_cse"
    default_max = 8

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        if not settings.google_api_key or not settings.google_cse_id:
            return []
        n = min(max_results or self.default_max, 10)
        params = {
            "key": settings.google_api_key,
            "cx": settings.google_cse_id,
            "q": query,
            "num": n,
            "lr": "lang_fr",
            "gl": "ma",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params,
                )
                r.raise_for_status()
                data = r.json()
            items = data.get("items", [])
            bruts = []
            for it in items:
                bruts.append({
                    "url": it.get("link", ""),
                    "title": it.get("title", ""),
                    "snippet": it.get("snippet", ""),
                    "provider": self.name,
                })
            return _normaliser(bruts)
        except Exception as exc:
            logger.warning(f"Google CSE error: {exc}")
            return []


class BraveSearchProvider(SearchProvider):
    name = "brave"
    default_max = 8

    def __init__(self):
        self.api_key = getattr(settings, "brave_api_key", "") or ""

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        if not self.api_key:
            return []
        n = max_results or self.default_max
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    params={"q": query, "count": n, "lang": "fr"},
                )
                r.raise_for_status()
                data = r.json()
            bruts = []
            for item in data.get("web", {}).get("results", []):
                bruts.append({
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "snippet": item.get("description", ""),
                    "published_at": item.get("age", ""),
                    "provider": self.name,
                })
            return _normaliser(bruts)
        except Exception as exc:
            logger.debug(f"Brave error: {exc}")
            return []


_ddg_semaphore = asyncio.Semaphore(1)

class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo Search (HTML/Text)."""
    name = "duckduckgo"
    default_max = 10

    @staticmethod
    def _ddg_search(query: str, max_results: int) -> list[SearchResult]:
        from ddgs import DDGS
        bruts = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, region="ma-ar"):
                r["provider"] = "duckduckgo"
                bruts.append(r)
        return _normaliser(bruts)

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        async with _ddg_semaphore:
            try:
                res = await asyncio.to_thread(self._ddg_search, query, max_results or self.default_max)
                await asyncio.sleep(1.0) # Pause pour éviter le ratelimit
                return res
            except Exception as exc:
                logger.debug(f"DDG Search error: {exc}")
                return []


class DuckDuckGoNewsProvider(SearchProvider):
    """DuckDuckGo News."""
    name = "duckduckgo_news"
    default_max = 5

    @staticmethod
    def _ddg_news(query: str, max_results: int) -> list[SearchResult]:
        try:
            from ddgs import DDGS
        except ImportError:
            return []
        bruts = []
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results, region="ma-ar"):
                r["provider"] = "duckduckgo_news"
                bruts.append(r)
        return _normaliser(bruts)

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        async with _ddg_semaphore:
            try:
                res = await asyncio.to_thread(self._ddg_news, query, max_results or self.default_max)
                await asyncio.sleep(1.0)
                return res
            except Exception as exc:
                logger.debug(f"DDG News error: {exc}")
                return []


class BingWebProvider(SearchProvider):
    name = "bing"
    default_max = 8

    def __init__(self):
        self.api_key = getattr(settings, "bing_api_key", "") or ""

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        if not self.api_key:
            return []
        n = max_results or self.default_max
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.bing.microsoft.com/v7.0/search",
                    headers={"Ocp-Apim-Subscription-Key": self.api_key},
                    params={"q": query, "count": n, "mkt": "fr-MA"},
                )
                r.raise_for_status()
                data = r.json()
            bruts = []
            for item in data.get("webPages", {}).get("value", []):
                bruts.append({
                    "url": item.get("url", ""),
                    "title": item.get("name", ""),
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("dateLastCrawled", ""),
                    "provider": self.name,
                })
            return _normaliser(bruts)
        except Exception as exc:
            logger.debug(f"Bing error: {exc}")
            return []


class SerperProvider(SearchProvider):
    """Google Search via Serper.dev (1000 requêtes/mois gratuit)."""
    name = "serper"
    default_max = 8

    def __init__(self):
        self.api_key = getattr(settings, "serper_api_key", "") or ""

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        if not self.api_key:
            return []
        n = max_results or self.default_max
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": n, "hl": "fr", "gl": "ma"},
                )
                r.raise_for_status()
                data = r.json()
            bruts = []
            for item in data.get("organic", []):
                bruts.append({
                    "url": item.get("link", ""),
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("date", ""),
                    "provider": self.name,
                })
            return _normaliser(bruts)
        except Exception as exc:
            logger.debug(f"Serper error: {exc}")
            return []


class SerpApiProvider(SearchProvider):
    """Google Search via SerpApi."""
    name = "serpapi"
    default_max = 8

    def __init__(self):
        self.api_key = getattr(settings, "serpapi_key", "") or ""

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        if not self.api_key:
            return []
        n = max_results or self.default_max
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://serpapi.com/search",
                    params={
                        "q": query,
                        "api_key": self.api_key,
                        "num": n,
                        "hl": "fr",
                        "gl": "ma",
                    },
                )
                r.raise_for_status()
                data = r.json()
            bruts = []
            for item in data.get("organic_results", []):
                bruts.append({
                    "url": item.get("link", ""),
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "published_at": item.get("date", ""),
                    "provider": self.name,
                })
            return _normaliser(bruts)
        except Exception as exc:
            logger.debug(f"SerpApi error: {exc}")
            return []


class GoogleNewsRSSProvider(SearchProvider):
    """RSS Google News — gratuit, fresh, sans clé."""
    name = "google_news_rss"
    default_max = 10

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        n = max_results or self.default_max
        encoded = quote_plus(query)
        feed_url = f"https://news.google.com/rss/search?q={encoded}&hl=fr&gl=MA&ceid=MA:fr"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(feed_url, follow_redirects=True)
                r.raise_for_status()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "xml")
            bruts = []
            for item in soup.find_all("item")[:n]:
                url = item.find("link")
                title = item.find("title")
                desc = item.find("description")
                pub = item.find("pubDate")
                if url:
                    bruts.append({
                        "url": url.text.strip(),
                        "title": title.text.strip() if title else "",
                        "snippet": desc.text.strip() if desc else "",
                        "published_at": pub.text.strip() if pub else "",
                        "provider": self.name,
                    })
            return _normaliser(bruts)
        except Exception as exc:
            logger.debug(f"Google News RSS error: {exc}")
            return []


class CommonCrawlProvider(SearchProvider):
    """Index Common Crawl — utile pour trouver des URLs d'entreprises moins connues."""
    name = "common_crawl"
    default_max = 10

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        n = max_results or self.default_max
        encoded = quote_plus(query)
        index_url = f"https://index.commoncrawl.org/CC-MAIN-2024-18-index?url=*.ma&matchType=domain&output=json&limit={n}&q={encoded}"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(index_url)
                if r.status_code != 200:
                    return []
            bruts = []
            for line in r.text.strip().splitlines()[:n]:
                try:
                    data = json.loads(line)
                    url = data.get("url", "")
                    if url:
                        bruts.append({
                            "url": f"https://{url}",
                            "title": data.get("filename", ""),
                            "snippet": "",
                            "provider": self.name,
                        })
                except Exception:
                    pass
            return _normaliser(bruts)
        except Exception as exc:
            logger.debug(f"CommonCrawl error: {exc}")
            return []


class SectorDomainsProvider(SearchProvider):
    """Recherche sur des domaines sectoriels spécialisés via DuckDuckGo site:."""
    name = "sector_domains"
    default_max = 6

    # Domaines par secteur/contexte — extensible
    DOMAIN_GROUPS: dict[str, list[str]] = {
        "agriculture": [
            "mapmdref.gov.ma", "eacce.gov.ma", "apefel.com", "fao.org",
            "onssa.gov.ma", "anpma.ma", "maroc-agro.com", "agricool.com",
            "agrilink.ma", "anpme.gov.ma", "atlas-mag.net",
        ],
        "startup": [
            "startupbrics.com", "disrupt-africa.com", "wamda.com",
            "magnitt.com", "techcrunch.com", "crunchbase.com",
            "africa.com", "ventureburn.com", "techafrique.com",
            "techinnov.ma", "moroccostartupszone.ma",
        ],
        "finance": [
            "casablancafinancecity.com", "cfcmaroc.com",
            "bkam.ma", "ammc.ma",
        ],
        "general": [
            "kompass.com", "europages.com", "societe.com",
            "opencorporates.com", "dnb.com", "pappers.fr",
        ],
    }

    def __init__(self, sector: str = "general"):
        self.sector = sector
        self.domains = (
            self.DOMAIN_GROUPS.get(sector, []) +
            self.DOMAIN_GROUPS.get("general", [])
        )[:8]

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        resultats: list[SearchResult] = []
        semaphore = asyncio.Semaphore(3)

        async def search_one(domain: str):
            async with semaphore:
                site_query = f"{query} site:{domain}"
                
                def _do_search():
                    try:
                        from ddgs import DDGS
                        bruts = []
                        with DDGS() as ddgs:
                            for r in ddgs.text(site_query, max_results=3):
                                r["provider"] = f"sector:{domain}"
                                bruts.append(r)
                        return _normaliser(bruts)
                    except Exception as exc:
                        logger.debug(f"SectorDomains {domain}: {exc}")
                        return []

                res = await asyncio.to_thread(_do_search)
                resultats.extend(res)
                await asyncio.sleep(0.3)

        await asyncio.gather(*[search_one(d) for d in self.domains])
        return resultats[:max_results or self.default_max]


class PDFSearchProvider(SearchProvider):
    """Cherche spécifiquement des documents PDF (rapports, études, catalogues)."""
    name = "pdf_search"
    default_max = 5

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        pdf_query = f"{query} filetype:pdf"
        n = max_results or self.default_max
        bruts: list[SearchResult] = []

        # Essayer plusieurs providers pour les PDFs
        providers: list[SearchProvider] = []
        if settings.tavily_api_key:
            providers.append(TavilyProvider())
        if getattr(settings, "enable_duckduckgo", True):
            providers.append(DuckDuckGoProvider())

        for provider in providers:
            try:
                results = await provider.search(pdf_query, max_results=n)
                for r in results:
                    if ".pdf" in r.url.lower() or "pdf" in r.snippet.lower():
                        bruts.append(r)
            except Exception:
                pass
            if bruts:
                break

        return bruts[:n]


# ---------------------------------------------------------------------------
# Moteur principal
# ---------------------------------------------------------------------------

class SearchEngine:
    """
    Moteur de recherche multi-provider avec fallback en cascade.
    Gère la déduplication, le scoring et le quota.
    """

    def __init__(
        self,
        sector: str = "agriculture",
        geography: str = "",
        providers_override: list[SearchProvider] | None = None,
    ):
        self.sector = sector
        self.geography = geography
        self._providers: list[SearchProvider] = providers_override or self._build_providers()
        self._semaphore = asyncio.Semaphore(settings.search_parallel_workers)
        self._query_cache: dict[str, list[SearchResult]] = {}

    def _build_providers(self) -> list[SearchProvider]:
        providers: list[SearchProvider] = []
        # Priorité 1 : APIs payantes (meilleure qualité)
        if settings.tavily_api_key:
            providers.append(TavilyProvider())
        if settings.google_api_key and settings.google_cse_id:
            providers.append(GoogleCSEProvider())
        # Priorité 2 : APIs optionnelles
        brave_key = getattr(settings, "brave_api_key", "")
        if brave_key:
            providers.append(BraveSearchProvider())
        bing_key = getattr(settings, "bing_api_key", "")
        if bing_key:
            providers.append(BingWebProvider())
        serper_key = getattr(settings, "serper_api_key", "")
        if serper_key:
            providers.append(SerperProvider())
        serpapi_key = getattr(settings, "serpapi_key", "")
        if serpapi_key:
            providers.append(SerpApiProvider())
        # Priorité 3 : Gratuits
        if getattr(settings, "enable_duckduckgo", True):
            providers.append(DuckDuckGoProvider())
            providers.append(DuckDuckGoNewsProvider())
        providers.append(GoogleNewsRSSProvider())
        providers.append(PDFSearchProvider())
        providers.append(SectorDomainsProvider(sector=self.sector))
        return providers

    async def search(
        self,
        query: str,
        max_results: int | None = None,
        providers: list[str] | None = None,
    ) -> list[SearchResult]:
        """Recherche sur tous les providers disponibles."""
        cache_key = hashlib.md5(query.strip().lower().encode()).hexdigest()
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        n = max_results or settings.max_results_per_query
        active_providers = [
            p for p in self._providers
            if providers is None or p.name in providers
        ]

        async with self._semaphore:
            tasks = [p.search(query, max_results=n) for p in active_providers]
            results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[SearchResult] = []
        for i, res in enumerate(results_lists):
            if isinstance(res, Exception):
                logger.warning(f"Provider {active_providers[i].name} error: {res}")
                continue
            all_results.extend(res)

        # Déduplication + tri par score
        unique = _deduplicate(all_results)
        unique.sort(key=lambda r: r.score, reverse=True)
        final = unique[:n]

        self._query_cache[cache_key] = final
        logger.info(f"Search '{query[:50]}': {len(all_results)} → {len(final)} (uniq, triés)")
        return final

    async def cascade_search(
        self,
        query: str,
        min_results: int = 3,
        max_results: int | None = None,
    ) -> list[SearchResult]:
        """
        Recherche en cascade : essaie les providers un par un jusqu'à avoir min_results.
        Économique en quota.
        """
        n = max_results or settings.max_results_per_query
        all_results: list[SearchResult] = []

        for provider in self._providers:
            if len(all_results) >= min_results:
                break
            try:
                results = await provider.search(query, max_results=n)
                all_results.extend(results)
                if results:
                    logger.debug(f"Cascade: {provider.name} → {len(results)} résultats")
            except Exception as exc:
                logger.debug(f"Cascade provider {provider.name}: {exc}")

        unique = _deduplicate(all_results)
        unique.sort(key=lambda r: r.score, reverse=True)
        return unique[:n]

    async def parallel_search(
        self,
        queries: list[str],
        max_results_each: int = 6,
        max_workers: int | None = None,
    ) -> list[SearchResult]:
        """
        Lance plusieurs requêtes en parallèle et fusionne les résultats.
        Utile pour la phase BREADTH de découverte.
        """
        workers = max_workers or settings.search_parallel_workers
        semaphore = asyncio.Semaphore(workers)
        all_results: list[SearchResult] = []

        async def _search_one(q: str):
            async with semaphore:
                res = await self.search(q, max_results=max_results_each)
                all_results.extend(res)
                if len(queries) > 3:
                    await asyncio.sleep(settings.scrape_delay_seconds * 0.5)

        await asyncio.gather(*[_search_one(q) for q in queries])
        unique = _deduplicate(all_results)
        unique.sort(key=lambda r: r.score, reverse=True)
        logger.info(f"Parallel search ({len(queries)} queries): {len(all_results)} → {len(unique)} résultats uniques")
        return unique


# ---------------------------------------------------------------------------
# Recherche avec repli — compatibilité avec code existant
# ---------------------------------------------------------------------------

async def rechercher_avec_repli(
    requete: str,
    max_resultats: int | None = None,
    sector: str = "agriculture",
) -> list[dict]:
    """
    Wrapper de compatibilité qui retourne la liste de dicts comme avant.
    Utilisable sans refactoring des outils existants.
    """
    engine = SearchEngine(sector=sector)
    resultats = await engine.cascade_search(
        requete,
        min_results=3,
        max_results=max_resultats or settings.max_results_per_query,
    )
    return [
        {
            "url": r.url,
            "titre": r.title,
            "contenu": r.snippet,
            "provider": r.provider,
            "score": r.score,
            "authority": r.authority,
            "tier": r.tier,
        }
        for r in resultats
    ]


async def etendre_requete(requete: str, geography: str = "", sector: str = "") -> list[str]:
    """
    Génère des variantes de requêtes génériques (non hardcodées sur un secteur).
    Utilise les patterns du QueryPlanner.
    """
    from core.query_planner import QueryPlanner
    planner = QueryPlanner(
        target=requete,
        objective=f"trouver des entreprises et informations sur : {requete}",
        geography=geography,
        sector=sector,
    )
    discovery_queries = planner.generate_discovery_queries()
    return [q.query for q in discovery_queries[:settings.max_variantes_recherche]]