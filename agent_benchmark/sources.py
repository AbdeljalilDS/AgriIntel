import feedparser
import requests
from urllib.parse import urlencode, urlsplit

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


def rechercher_tavily(requete: str, nb_resultats: int | None = None) -> list[dict]:
    if not settings.tavily_api_key:
        logger.warning(f"Tavily non configuré — requête ignorée : '{requete}'")
        return []
    nb = nb_resultats or settings.max_results_per_query
    try:
        response = requests.post(
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
    except requests.RequestException as exc:
        raise SearchAPIError(f"Échec de la recherche Tavily pour '{requete}'") from exc

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


def rechercher_google(requete: str, nb_resultats: int | None = None) -> list[dict]:
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
    try:
        response = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=settings.request_timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SearchAPIError(f"Échec de la recherche Google pour '{requete}'") from exc
    data = response.json()
    return [
        {"titre": item.get("title", ""), "url": item["link"], "contenu": item.get("snippet", ""), "moteur": "google"}
        for item in data.get("items", [])
        if item.get("link")
    ]


def rechercher_google_news(requete: str, langue: str = "fr", pays: str = "MA") -> list[dict]:
    url = "https://news.google.com/rss/search?" + urlencode({"q": requete, "hl": langue, "gl": pays, "ceid": f"{pays}:{langue}"})
    try:
        flux = feedparser.parse(url)
    except Exception as exc:
        raise SearchAPIError(f"Échec de la lecture du flux Google News pour '{requete}'") from exc
    return [{"titre": entry.title, "url": entry.link, "contenu": getattr(entry, "summary", ""), "moteur": "news"} for entry in flux.entries[:5]]


def rechercher_duckduckgo(requete: str, nb_resultats: int | None = None) -> list[dict]:
    """Repli gratuit sans clé API — fonctionne même sans Tavily ni Google CSE."""
    if not settings.enable_duckduckgo:
        return []
    nb = nb_resultats or settings.max_results_per_query
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            items = list(ddgs.text(requete, region="ma-fr", max_results=min(nb, 10)))
    except ImportError:
        logger.warning("duckduckgo-search absent — pip install duckduckgo-search")
        return _rechercher_duckduckgo_html(requete, nb)
    except Exception as exc:
        logger.warning(f"DuckDuckGo API échouée pour '{requete}' : {exc}")
        return _rechercher_duckduckgo_html(requete, nb)

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


def _rechercher_duckduckgo_html(requete: str, nb: int) -> list[dict]:
    """Repli HTML si le package duckduckgo-search est indisponible."""
    try:
        response = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": requete, "kl": "ma-fr"},
            headers={"User-Agent": settings.user_agent},
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

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


def rechercher_sites_sectoriels(requete: str) -> list[dict]:
    """Recherche ciblée sur les sites agricoles marocains connus."""
    resultats = []
    mots = [mot for mot in requete.split() if len(mot) > 3][:4]
    if not mots:
        return []
    for site in SITES_SECTORIELS[:6]:
        domaine = urlsplit(site).netloc
        requete_site = f"{' '.join(mots)} site:{domaine}"
        try:
            resultats.extend(rechercher_duckduckgo(requete_site, nb_resultats=3))
        except Exception as exc:
            logger.warning(str(exc))
    return resultats


def rechercher_avec_repli(requete: str, nb_resultats: int | None = None) -> list[dict]:
    """Chaîne de repli : Tavily → Google CSE → DuckDuckGo → Google News → sites sectoriels."""
    resultats: list[dict] = []
    for fonction in (rechercher_tavily, rechercher_google, rechercher_duckduckgo, rechercher_google_news):
        try:
            trouves = fonction(requete, nb_resultats) if nb_resultats else fonction(requete)
        except SearchAPIError as exc:
            logger.warning(str(exc))
            trouves = []
        except Exception as exc:
            logger.warning(str(exc))
            trouves = []
        if trouves:
            resultats.extend(trouves)
            if len(resultats) >= (nb_resultats or settings.max_results_per_query):
                return resultats
    if not resultats:
        resultats.extend(rechercher_sites_sectoriels(requete))
    return resultats


def etendre_requete(requete: str) -> list[str]:
    """Explore plusieurs angles documentaires sans multiplier les agents."""
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
    """Filtre les liens non HTTP ou manifestement inutiles avant collecte."""
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
    """Estime la fiabilite d'une source avant validation par le LLM."""
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
