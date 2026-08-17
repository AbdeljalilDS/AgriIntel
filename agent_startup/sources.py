import asyncio
import re
from urllib.parse import urlencode, urlsplit

import feedparser
import httpx

from config.settings import settings
from core.exceptions import SearchAPIError
from core.logger import get_logger

logger = get_logger(__name__)

SITES_SECTORIELS = [
    "https://www.agriculture.gov.ma",
    "https://www.onssa.gov.ma",
    "https://www.onca.gov.ma",
    "https://www.onicl.org.ma",
    "https://www.comader.ma",
    "https://www.fenagri.org",
    "https://www.agrimaroc.ma",
    "https://www.leconomiste.com",
    "https://medias24.com",
    "https://www.challenge.ma",
    "https://lematin.ma/economie",
    "https://leseco.ma",
]

async def rechercher_tavily(requete: str, nb_resultats: int | None = None, client: httpx.AsyncClient | None = None) -> list[dict]:
    if not settings.tavily_api_key:
        logger.warning(f"Tavily non configuré — requête ignorée : '{requete}'")
        return []
    nb = nb_resultats or settings.max_results_per_query
    local_client = client or httpx.AsyncClient()
    try:
        response = await local_client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": requete,
                "max_results": min(nb, 10),
                "search_depth": "advanced",
                "include_answer": False,
                "include_raw_content": True,
            },
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
    except httpx.RequestError as exc:
        logger.warning(f"Échec Tavily pour '{requete}': {exc}")
        return []
    finally:
        if not client:
            await local_client.aclose()

    data = response.json()
    resultats = [
        {
            "titre": item.get("title", ""),
            "url": item["url"],
            "contenu": item.get("raw_content") or item.get("content", ""),
            "date_publication": item.get("published_date"),
            "score": item.get("score"),
            "moteur": "tavily",
        }
        for item in data.get("results", [])
        if item.get("url")
    ]
    logger.info(f"Tavily : {len(resultats)} résultat(s) pour '{requete}'")
    return resultats


async def rechercher_google(requete: str, nb_resultats: int | None = None, client: httpx.AsyncClient | None = None) -> list[dict]:
    if not settings.google_api_key or not settings.google_cse_id:
        return []
    nb = nb_resultats or settings.max_results_per_query
    params = {
        "key": settings.google_api_key,
        "cx": settings.google_cse_id,
        "q": requete,
        "num": min(nb, 10),
        "lr": "lang_fr",
        "gl": "ma",
        "cr": "countryMA",
    }
    local_client = client or httpx.AsyncClient()
    try:
        response = await local_client.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=settings.request_timeout)
        response.raise_for_status()
    except httpx.RequestError as exc:
        logger.warning(f"Échec Google pour '{requete}': {exc}")
        return []
    finally:
        if not client:
            await local_client.aclose()
            
    data = response.json()
    return [
        {"titre": item.get("title", ""), "url": item["link"], "contenu": item.get("snippet", ""), "moteur": "google"}
        for item in data.get("items", [])
        if item.get("link")
    ]


async def rechercher_google_news(requete: str, langue: str = "fr", pays: str = "MA") -> list[dict]:
    url = "https://news.google.com/rss/search?" + urlencode({"q": requete, "hl": langue, "gl": pays, "ceid": f"{pays}:{langue}"})
    try:
        flux = await asyncio.to_thread(feedparser.parse, url)
    except Exception as exc:
        logger.warning(f"Échec Google News pour '{requete}': {exc}")
        return []
    return [{"titre": entry.title, "url": entry.link, "contenu": getattr(entry, "summary", ""), "moteur": "news"} for entry in flux.entries[:5]]


def _sync_ddg(requete: str, nb: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        try:
            from ddgs import DDGS
        except ImportError:
            return []
    with DDGS() as ddgs:
        return list(ddgs.text(requete, region="ma-fr", max_results=min(nb, 10)))

async def _rechercher_duckduckgo_html(requete: str, nb: int, client: httpx.AsyncClient) -> list[dict]:
    try:
        response = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": requete, "kl": "ma-fr"},
            headers={"User-Agent": settings.user_agent},
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
    except httpx.RequestError:
        return []
        
    def _parse():
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")
        resultats = []
        for bloc in soup.select(".result")[:nb]:
            lien = bloc.select_one("a.result__a")
            extrait = bloc.select_one(".result__snippet")
            if not lien or not lien.get("href"):
                continue
            url = lien["href"]
            if url.startswith("//duckduckgo.com/l/?"):
                import urllib.parse as up
                params = up.parse_qs(up.urlparse("https:" + url).query)
                url = params.get("uddg", [url])[0]
            resultats.append({
                "titre": lien.get_text(strip=True),
                "url": url,
                "contenu": extrait.get_text(strip=True) if extrait else "",
                "score": 0.4,
                "moteur": "duckduckgo-html",
            })
        return resultats
        
    return await asyncio.to_thread(_parse)


async def rechercher_duckduckgo(requete: str, nb_resultats: int | None = None, client: httpx.AsyncClient | None = None) -> list[dict]:
    if not settings.enable_duckduckgo:
        return []
    nb = nb_resultats or settings.max_results_per_query
    try:
        items = await asyncio.to_thread(_sync_ddg, requete, nb)
    except Exception as exc:
        logger.warning(f"DuckDuckGo API échouée pour '{requete}' : {exc}")
        local_client = client or httpx.AsyncClient()
        try:
            return await _rechercher_duckduckgo_html(requete, nb, local_client)
        finally:
            if not client:
                await local_client.aclose()
                
    if not items:
        return []
        
    resultats = [
        {
            "titre": item.get("title", ""),
            "url": item.get("href", ""),
            "contenu": item.get("body", ""),
            "score": 0.5,
            "moteur": "duckduckgo",
        }
        for item in items
        if item.get("href")
    ]
    logger.info(f"DuckDuckGo : {len(resultats)} résultat(s) pour '{requete}'")
    return resultats


async def rechercher_sites_sectoriels(requete: str, client: httpx.AsyncClient | None = None) -> list[dict]:
    resultats = []
    mots = [mot for mot in requete.split() if len(mot) > 3][:4]
    if not mots:
        return []
        
    local_client = client or httpx.AsyncClient()
    try:
        tasks = []
        for site in SITES_SECTORIELS[:6]:
            domaine = urlsplit(site).netloc
            requete_site = f"{' '.join(mots)} site:{domaine}"
            tasks.append(rechercher_duckduckgo(requete_site, nb_resultats=3, client=local_client))
            
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results_list:
            if isinstance(r, list):
                resultats.extend(r)
    finally:
        if not client:
            await local_client.aclose()
            
    return resultats


async def rechercher_wikipedia(requete: str, langue: str = "fr", client: httpx.AsyncClient | None = None) -> list[dict]:
    local_client = client or httpx.AsyncClient()
    try:
        for lang in (langue, "en") if langue != "en" else ("en",):
            try:
                response = await local_client.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "query", "list": "search", "srsearch": requete,
                        "format": "json", "srlimit": 3,
                    },
                    headers={"User-Agent": settings.user_agent},
                    timeout=settings.request_timeout,
                )
                response.raise_for_status()
                hits = response.json().get("query", {}).get("search", [])
            except httpx.RequestError as exc:
                logger.warning(f"Wikipedia ({lang}) indisponible pour '{requete}' : {exc}")
                continue
                
            if hits:
                import re as _re
                return [
                    {
                        "titre": h["title"],
                        "url": f"https://{lang}.wikipedia.org/wiki/{h['title'].replace(' ', '_')}",
                        "contenu": _re.sub(r"<[^>]+>", "", h.get("snippet", "")),
                        "moteur": f"wikipedia-{lang}",
                    }
                    for h in hits
                ]
        return []
    finally:
        if not client:
            await local_client.aclose()


async def rechercher_avec_repli(requete: str, nb_resultats: int | None = None) -> list[dict]:
    resultats: list[dict] = []
    
    async with httpx.AsyncClient(verify=False) as client:
        appels = [
            rechercher_tavily(requete, nb_resultats, client),
            rechercher_google(requete, nb_resultats, client),
            rechercher_google_news(requete),
            rechercher_duckduckgo(requete, nb_resultats, client),
            rechercher_wikipedia(requete, client=client),
        ]
        
        batch_results = await asyncio.gather(*appels, return_exceptions=True)
        for res in batch_results:
            if isinstance(res, list):
                resultats.extend(res)
                
        if not resultats:
            sites_sec = await rechercher_sites_sectoriels(requete, client)
            resultats.extend(sites_sec)
            
    return resultats


def etendre_requete(requete: str) -> list[str]:
    base = requete.strip()
    variantes = [
        base,
        f"{base} site officiel activités produits Maroc",
        f"{base} concurrents production export fruits légumes Maroc",
        f"{base} financement investisseurs chiffre affaires rapport annuel",
        f"{base} technologie innovation agriculture chaîne de valeur",
        f"{base} presse spécialisée agriculture Maroc interview",
        f"{base} réglementation certification partenariat Maroc",
        f"{base} site:ma -facebook -linkedin -instagram",
    ]
    return list(dict.fromkeys(variantes))


def url_scrapable(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return False
    domaine = parts.netloc.lower()
    domaines_exclus = ("facebook.com", "instagram.com", "linkedin.com", "youtube.com", "twitter.com", "x.com")
    return not any(domaine == exclu or domaine.endswith(f".{exclu}") for exclu in domaines_exclus)


def score_fiabilite_source(url: str, titre: str = "", contenu: str = "") -> float:
    domaine = urlsplit(url).netloc.lower().split(":")[0]
    score = 0.35 if url.lower().startswith("https://") else 0.15
    if domaine.endswith(".gov.ma") or domaine.endswith(".ac.ma"):
        score += 0.35
    elif domaine.endswith(".ma"):
        score += 0.15
    elif domaine in {"reuters.com", "bloomberg.com", "lesechos.fr", "lemonde.fr"}:
        score += 0.2
    if any(mot in domaine for mot in ("official", "entreprise", "company")):
        score += 0.1
    if titre.strip() and contenu.strip():
        score += 0.1
    return round(min(score, 1.0), 2)