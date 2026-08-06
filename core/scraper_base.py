import io
import json
import random
import re
import time
from urllib.parse import urljoin, urlsplit

import requests
import trafilatura
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings
from core.exceptions import ScrapingError
from core.cache import enregistrer_page, lire_page
from core.logger import get_logger

logger = get_logger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

SEUIL_TEXTE_INSUFFISANT = 200
TAILLE_HTML_MAX = 2_000_000
DOMAINES_SANS_PLAYWRIGHT = ("news.google.com",)

SCORES_SOURCES = {
    "site officiel": 1.0,
    "official": 1.0,
    "company": 0.95,
    "investor": 0.9,
    "press": 0.8,
    "news": 0.75,
    "blog": 0.4,
    "forum": 0.2,
    "social": 0.3,
}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type(requests.RequestException), reraise=True)
def _fetch_html(url: str) -> requests.Response:
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    # Timeout réduit en fast_mode pour ne pas bloquer sur des pages lentes
    timeout = 10 if settings.fast_mode else settings.request_timeout
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response

def _extraction_secours(html: str) -> str | None:
    try:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
            element.decompose()
        texte = soup.get_text(separator="\n", strip=True)
        return texte if len(texte) > SEUIL_TEXTE_INSUFFISANT else None
    except Exception:
        return None

def _extraire_pdf(contenu: bytes) -> str | None:
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(io.BytesIO(contenu)) as pdf:
            pages_texte = [page.extract_text() or "" for page in pdf.pages[:15]]
        texte = "\n".join(pages_texte).strip()
        return texte if len(texte) > SEUIL_TEXTE_INSUFFISANT else None
    except Exception as exc:
        logger.warning(f"Échec d'extraction PDF : {exc}")
        return None


def _detecter_type_source(url: str) -> str:
    domaine = urlsplit(url).netloc.lower()
    chemin = urlsplit(url).path.lower()
    if chemin.endswith(".pdf") or ".pdf" in chemin:
        return "pdf"
    if "linkedin.com" in domaine:
        return "linkedin"
    if any(segment in chemin for segment in ("/news/", "/actualites/", "/blog/", "/press/", "/media/")) or "news" in domaine:
        return "news"
    return "html"


def _extraire_texte_rss(xml: str) -> str | None:
    try:
        soup = BeautifulSoup(xml, "xml")
    except Exception:
        return None
    items = []
    for item in soup.find_all("item"):
        titre = item.find("title")
        description = item.find("description")
        texte = " ".join(part.strip() for part in [titre.get_text(" ", strip=True) if titre else "", description.get_text(" ", strip=True) if description else ""] if part.strip())
        if texte:
            items.append(texte)
    return "\n".join(items) if items else None


def _extraire_metadonnees_html(html: str) -> dict[str, list[str]]:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return {"titles": [], "descriptions": [], "keywords": [], "jsonld": []}

    titres = [t.strip() for t in re.split(r"\s+", soup.title.get_text(" ", strip=True)) if t.strip()] if soup.title else []
    descriptions = []
    for meta in soup.find_all("meta"):
        if meta.get("name", "").lower() in {"description", "keywords"}:
            descriptions.append(meta.get("content", "").strip())
        if meta.get("property", "").lower() in {"og:description", "og:title"}:
            descriptions.append(meta.get("content", "").strip())

    keywords = []
    for meta in soup.find_all("meta"):
        if meta.get("name", "").lower() == "keywords":
            keywords.extend([part.strip() for part in meta.get("content", "").split(",") if part.strip()])

    jsonld = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            donnees = json.loads(tag.string or "{}")
        except Exception:
            continue
        if isinstance(donnees, dict):
            jsonld.append(donnees)
        elif isinstance(donnees, list):
            jsonld.extend([item for item in donnees if isinstance(item, dict)])

    return {
        "titles": titres[:3],
        "descriptions": descriptions[:5],
        "keywords": keywords[:10],
        "jsonld": jsonld[:5],
    }


def _extraire_texte_html(html: str, url: str) -> str | None:
    texte = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
        url=url,
    )
    if texte and len(texte) > SEUIL_TEXTE_INSUFFISANT:
        return texte
    texte_secours = _extraction_secours(html)
    return texte_secours if texte_secours else None


def _extraire_fragment_structure(html: str, url: str) -> dict[str, object]:
    meta = _extraire_metadonnees_html(html)
    texte = _extraire_texte_html(html, url)
    return {
        "url": url,
        "title": " ".join(meta["titles"][:1]) if meta["titles"] else None,
        "description": " | ".join(meta["descriptions"][:3]) if meta["descriptions"] else None,
        "keywords": meta["keywords"],
        "jsonld": meta["jsonld"],
        "text": texte,
    }


def _est_page_valeur_ajoutee(url: str, texte_lien: str) -> bool:
    chemin = urlsplit(url).path.lower()
    if any(segment in chemin for segment in ("/privacy", "/terms", "/legal", "/contact", "/login", "/signup", "/cookie")):
        return False
    if any(mot in texte_lien for mot in ("technology", "technologies", "product", "products", "solution", "solutions", "innovation", "about", "company")):
        return True
    return False


def _score_page(url: str, texte_lien: str) -> float:
    chemin = urlsplit(url).path.lower()
    score = 0.0
    if any(mot in texte_lien for mot in ("technology", "technologies")):
        score += 0.55
    elif any(mot in texte_lien for mot in ("product", "products", "solution", "solutions")):
        score += 0.5
    elif any(mot in texte_lien for mot in ("innovation", "about", "company", "about us", "our company")):
        score += 0.3
    if any(mot in chemin for mot in ("technology", "technologies")):
        score += 0.25
    elif any(mot in chemin for mot in ("product", "products", "solution", "solutions")):
        score += 0.2
    elif any(mot in chemin for mot in ("innovation", "about", "company")):
        score += 0.1
    if any(mot in texte_lien for mot in ("privacy", "cookie", "legal", "terms", "contact", "login", "signup")):
        score -= 0.6
    for nom, poids in SCORES_SOURCES.items():
        if nom in texte_lien:
            score += poids * 0.1
            break
    return score


def _extraire_liens_internes(html: str, url: str) -> list[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    domaine = urlsplit(url).netloc.lower()
    candidats: list[tuple[float, str]] = []
    for lien in soup.find_all("a", href=True):
        href = str(lien.get("href", "")).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        try:
            resolu = urljoin(url, href)
        except Exception:
            continue
        if urlsplit(resolu).netloc.lower() != domaine:
            continue
        cible = resolu.split("#", 1)[0]
        if cible == url.split("#", 1)[0]:
            continue
        if cible in {item[1] for item in candidats}:
            continue

        texte_lien = " ".join(lien.stripped_strings).lower()
        score = _score_page(cible, texte_lien)
        if not _est_page_valeur_ajoutee(cible, texte_lien) and score < 0.2:
            continue
        candidats.append((score, cible))

    candidats.sort(key=lambda item: item[0], reverse=True)
    return [cible for _, cible in candidats]


def _rendu_javascript(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch(headless=True)
            try:
                page = navigateur.new_page(user_agent=random.choice(USER_AGENTS))
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=8000)
                html = page.content()
            finally:
                navigateur.close()
        return html
    except Exception as exc:
        logger.warning(f"Échec du rendu JavaScript pour {url} : {exc}")
        return None


def _extraire_texte_page(url: str, html: str) -> str | None:
    type_source = _detecter_type_source(url)
    if type_source == "news":
        texte_rss = _extraire_texte_rss(html)
        if texte_rss:
            return texte_rss
    fragment = _extraire_fragment_structure(html, url)
    return fragment.get("text")

def fetch_clean_text(url: str) -> str | None:
    texte_cache = lire_page(url)
    if texte_cache:
        logger.info(f"Page servie depuis le cache : {url}")
        return texte_cache

    pages_a_traiter = [url]
    pages_vues: set[str] = set()
    textes: list[str] = []
    # Nombre de pages internes crawlées : 2 en fast_mode, 4 en mode normal
    max_pages = settings.pages_par_site()

    while pages_a_traiter and len(pages_vues) < max_pages:
        page_url = pages_a_traiter.pop(0)
        if page_url in pages_vues:
            continue
        pages_vues.add(page_url)

        try:
            response = _fetch_html(page_url)
        except requests.RequestException as exc:
            logger.warning(f"Échec de récupération de {page_url} : {exc}")
            continue
        finally:
            time.sleep(settings.scrape_delay_seconds)

        content_type = response.headers.get("Content-Type", "")
        type_source = _detecter_type_source(page_url)
        if type_source == "pdf" or "pdf" in content_type.lower() or page_url.lower().endswith(".pdf"):
            texte_pdf = _extraire_pdf(response.content)
            if texte_pdf:
                textes.append(texte_pdf)
            continue

        if type_source == "news" and response.text:
            texte_rss = _extraire_texte_rss(response.text)
            if texte_rss:
                textes.append(texte_rss)
                continue

        html = response.text[:TAILLE_HTML_MAX]
        fragment = _extraire_fragment_structure(html, page_url)
        texte_page = _extraire_texte_page(page_url, html)
        if texte_page:
            if fragment.get("title"):
                textes.append(f"Titre: {fragment['title']}")
            if fragment.get("description"):
                textes.append(f"Description: {fragment['description']}")
            textes.append(texte_page)

        if len(pages_vues) < max_pages:
            for lien in _extraire_liens_internes(html, page_url)[:3]:
                if lien not in pages_vues and lien not in pages_a_traiter:
                    pages_a_traiter.append(lien)

    if textes:
        texte_final = "\n\n".join(textes)
        enregistrer_page(url, texte_final)
        return texte_final

    domaine = urlsplit(url).netloc.lower()
    domaine_bloque = any(d in domaine for d in DOMAINES_SANS_PLAYWRIGHT)
    if settings.playwright_actif() and not domaine_bloque:
        html_rendu = _rendu_javascript(url)
        if html_rendu:
            texte_js = _extraire_texte_page(url, html_rendu)
            if texte_js:
                enregistrer_page(url, texte_js)
                return texte_js

    logger.warning(f"Aucun contenu exploitable extrait de {url}")
    return None
