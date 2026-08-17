"""
Scraper profond — Enterprise AI Research Engine.

Architecture multi-couche (par ordre de préférence, économie de ressources) :
  1. Cache disque             → gratuit, instantané
  2. HTTP + Trafilatura       → léger, rapide
  3. BeautifulSoup fallback   → si Trafilatura insuffisant
  4. PDF extraction           → pdfplumber si Content-Type PDF
  5. Playwright (browser pool)→ seulement si JS requis
  6. Schema.org / JSON-LD     → données structurées à toute étape

Spécificités 8 Go RAM :
  - 1 seul browser Chromium partagé (browser_pool.py)
  - Limite max_pages configurable
  - Texte tronqué après TAILLE_EXTRACTION_MAX
  - Pages en cache disque pour éviter re-scraping

Inspiration : Perplexity, Gemini Deep Research, OpenAI Deep Research
"""
from __future__ import annotations

import asyncio
import io
import json
import random
import re
from urllib.parse import urljoin, urlsplit, urlencode

import httpx
import trafilatura
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import settings
from core.cache import enregistrer_page, lire_page
from core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

SEUIL_TEXTE_MIN    = 80
TAILLE_HTML_MAX    = 3_000_000
TAILLE_EXTRACTION_MAX = 20_000
PDF_PAGES_MAX      = 15

DOMAINES_SANS_BROWSER = frozenset({
    "news.google.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "tiktok.com", "youtube.com", "reddit.com",
})

DOMAINES_EXCLUS_SCRAPING = frozenset({
    "facebook.com", "instagram.com", "linkedin.com",
    "youtube.com", "twitter.com", "x.com", "tiktok.com",
    "pinterest.com", "reddit.com", "quora.com",
})

# Patterns URL de pages utiles pour le crawl interne
MOTS_PAGES_UTILES = (
    "about", "a-propos", "presentation", "profil", "company", "entreprise",
    "qui-sommes", "notre-histoire", "gouvernance", "overview",
    "product", "produit", "produits", "service", "services", "offre",
    "solution", "solutions", "catalogue", "gamme", "portfolio",
    "export", "international", "marche", "market", "client", "clients",
    "certification", "certifications", "qualite", "iso", "bio", "global-gap",
    "haccp", "quality", "standards",
    "technology", "technologie", "innovation", "r-d", "recherche", "research",
    "partenaire", "partner", "fournisseur", "supplier",
    "finance", "rapport", "annual-report", "investors", "investisseurs",
    "news", "press", "media", "actualites", "blog",
    "sustainability", "esg", "environnement",
    "careers", "jobs", "equipe", "team",
)

# Patterns URL à exclure
PATTERNS_EXCLUS = frozenset({
    "/privacy", "/terms", "/legal", "/cookie", "/login", "/signup",
    "/cart", "/checkout", "/account", "/search", "/tag/", "/category/",
    "/wp-admin", "/wp-content", "/wp-includes",
    "/auth", "/register", "/404", "/error",
})


# ---------------------------------------------------------------------------
# Fetch HTTP de base
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.RequestError),
    reraise=True,
)
async def _fetch_html(url: str, client: httpx.AsyncClient) -> httpx.Response:
    timeout = 10 if settings.fast_mode else settings.request_timeout
    response = await client.get(
        url,
        headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8,ar;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
        },
        timeout=timeout,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# Extraction de texte
# ---------------------------------------------------------------------------

def _nettoyer_texte(texte: str) -> str:
    lignes = [l.strip() for l in texte.splitlines() if l.strip() and len(l.strip()) > 2]
    texte = "\n".join(lignes)
    return re.sub(r" {2,}", " ", texte)


def _extraction_bs(html: str) -> str | None:
    """Fallback BeautifulSoup si Trafilatura insuffisant."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for el in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "iframe"]):
            el.decompose()
        for sel in ("main", "article", '[role="main"]', ".content", "#content",
                    ".main-content", ".entry-content", ".page-content"):
            tag = soup.select_one(sel)
            if tag:
                t = _nettoyer_texte(tag.get_text(separator="\n", strip=True))
                if len(t) > SEUIL_TEXTE_MIN:
                    return t[:TAILLE_EXTRACTION_MAX]
        body = soup.find("body")
        if body:
            t = _nettoyer_texte(body.get_text(separator="\n", strip=True))
            return t[:TAILLE_EXTRACTION_MAX] if len(t) > SEUIL_TEXTE_MIN else None
    except Exception:
        pass
    return None


async def _extraire_texte_html(html: str, url: str) -> str | None:
    """Extraction texte HTML (trafilatura en thread pour ne pas bloquer)."""
    def _extract():
        texte = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            include_images=False,
            include_links=False,
            favor_precision=False,
            favor_recall=True,
            url=url,
        )
        if texte and len(texte) > SEUIL_TEXTE_MIN:
            return _nettoyer_texte(texte)[:TAILLE_EXTRACTION_MAX]
        return _extraction_bs(html)
    return await asyncio.to_thread(_extract)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

async def extraire_pdf(contenu: bytes, url: str = "") -> str | None:
    """Extrait texte + tableaux d'un PDF (max PDF_PAGES_MAX pages)."""
    def _extract():
        try:
            import pdfplumber
        except ImportError:
            return None
        try:
            with pdfplumber.open(io.BytesIO(contenu)) as pdf:
                pages_txt: list[str] = []
                for i, page in enumerate(pdf.pages[:PDF_PAGES_MAX]):
                    txt = page.extract_text() or ""
                    try:
                        for table in page.extract_tables() or []:
                            for row in table or []:
                                cells = [str(c).strip() for c in (row or []) if c]
                                if cells:
                                    txt += "\n" + " | ".join(cells)
                    except Exception:
                        pass
                    if txt.strip():
                        pages_txt.append(f"[Page {i+1}] {txt}")
                texte = "\n\n".join(pages_txt).strip()
                return texte if len(texte) > SEUIL_TEXTE_MIN else None
        except Exception as exc:
            logger.warning(f"PDF extraction échec {url}: {exc}")
            return None
    return await asyncio.to_thread(_extract)


# ---------------------------------------------------------------------------
# Schema.org / JSON-LD
# ---------------------------------------------------------------------------

def _extraire_schema_org(html: str) -> dict:
    out: dict = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                types = item.get("@type", "")
                if isinstance(types, str):
                    types = [types]
                if not any(
                    t in {"Organization", "Corporation", "LocalBusiness",
                           "Enterprise", "Person", "Product", "WebSite"}
                    for t in types
                ):
                    continue
                for field, key in [
                    ("nom", "name"), ("site_web", "url"), ("description", "description"),
                    ("telephone", "telephone"), ("annee_creation", "foundingDate"),
                ]:
                    if item.get(key) and field not in out:
                        out[field] = str(item[key])[:500]
                addr = item.get("address", {})
                if isinstance(addr, dict):
                    parts = [str(addr.get(k, "")) for k in
                             ("streetAddress", "addressLocality", "addressRegion", "addressCountry")
                             if addr.get(k)]
                    if parts:
                        out["siege_social"] = ", ".join(parts)
                same = item.get("sameAs", [])
                if isinstance(same, str):
                    same = [same]
                out["reseaux_sociaux"] = [
                    s for s in same
                    if any(x in s.lower() for x in ("facebook", "linkedin", "twitter", "instagram"))
                ][:5]
    except Exception as exc:
        logger.debug(f"schema.org: {exc}")
    return out


# ---------------------------------------------------------------------------
# Sitemap & Robots
# ---------------------------------------------------------------------------

async def fetch_sitemap_urls(base_url: str, client: httpx.AsyncClient, max_urls: int = 50) -> list[str]:
    """Récupère les URLs depuis sitemap.xml."""
    urls: list[str] = []
    parsed = urlsplit(base_url)
    sitemap_candidates = [
        f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap-index.xml",
    ]

    for sitemap_url in sitemap_candidates:
        try:
            r = await client.get(sitemap_url, timeout=8, follow_redirects=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "xml")
            # Sitemap index
            for loc in soup.find_all("sitemap")[:5]:
                child_url = loc.find("loc")
                if child_url:
                    try:
                        r2 = await client.get(child_url.text.strip(), timeout=8)
                        if r2.status_code == 200:
                            soup2 = BeautifulSoup(r2.text, "xml")
                            for u in soup2.find_all("url")[:max_urls]:
                                l = u.find("loc")
                                if l:
                                    urls.append(l.text.strip())
                    except Exception:
                        pass
            # Sitemap simple
            for u in soup.find_all("url")[:max_urls]:
                l = u.find("loc")
                if l:
                    urls.append(l.text.strip())
            if urls:
                logger.debug(f"Sitemap trouvé : {len(urls)} URLs depuis {sitemap_url}")
                return urls[:max_urls]
        except Exception:
            pass
    return []


async def check_robots(base_url: str, client: httpx.AsyncClient) -> set[str]:
    """Récupère les chemins disallowed depuis robots.txt."""
    disallowed: set[str] = set()
    parsed = urlsplit(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        r = await client.get(robots_url, timeout=5, follow_redirects=True)
        if r.status_code == 200:
            for line in r.text.splitlines():
                line = line.strip().lower()
                if line.startswith("disallow:"):
                    path = line[len("disallow:"):].strip()
                    if path and path != "/":
                        disallowed.add(path)
    except Exception:
        pass
    return disallowed


# ---------------------------------------------------------------------------
# Liens internes
# ---------------------------------------------------------------------------

def _extraire_liens_internes(html: str, url: str, disallowed: set[str] | None = None) -> list[str]:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []
    domaine = urlsplit(url).netloc.lower().replace("www.", "")
    candidats: list[tuple[int, str]] = []
    vus: set[str] = set()
    disallowed = disallowed or set()

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", "")).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        try:
            resolu = urljoin(url, href)
        except Exception:
            continue
        netloc = urlsplit(resolu).netloc.lower().replace("www.", "")
        if netloc != domaine:
            continue
        cible = resolu.split("#")[0].rstrip("/")
        if cible == url.split("#")[0].rstrip("/") or cible in vus:
            continue
        path = urlsplit(cible).path.lower()
        if any(x in path for x in PATTERNS_EXCLUS):
            continue
        if any(path.startswith(d) for d in disallowed):
            continue
        vus.add(cible)
        texte_lien = " ".join(a.stripped_strings).lower()[:100]
        score = sum(1 for m in MOTS_PAGES_UTILES if m in texte_lien or m in path)
        if score > 0:
            candidats.append((score, cible))

    candidats.sort(key=lambda x: x[0], reverse=True)
    return [u for _, u in candidats[:10]]


# ---------------------------------------------------------------------------
# Détection JS
# ---------------------------------------------------------------------------

def _necessite_browser(html: str, texte: str | None) -> bool:
    if not texte or len(texte) < 400:
        return True
    markers = (
        "__NEXT_DATA__", "ng-version", "data-reactroot",
        'id="root"', 'id="app"', "webpackJsonp", "vue-app",
        "__nuxt__", "data-vue-app",
    )
    low = (html or "")[:8000].lower()
    return any(m.lower() in low for m in markers)


# ---------------------------------------------------------------------------
# Fetch principal multi-couche
# ---------------------------------------------------------------------------

async def fetch_clean_text(url: str, use_browser: bool | None = None) -> str | None:
    """
    Récupère et nettoie le contenu textuel d'une URL.

    Stratégie :
    1. Cache → si trouvé, retourne immédiatement
    2. HTTP + extraction → si texte suffisant, retourne
    3. Browser (si JS nécessaire) → extraction depuis HTML rendu
    4. Si PDF → extraction PDF

    Retourne None si impossible d'extraire du contenu utile.
    """
    from core.exceptions import ScrapingError

    # 1. Cache
    texte_cache = await asyncio.to_thread(lire_page, url)
    if texte_cache:
        logger.debug(f"Cache hit : {url[:60]}")
        return texte_cache

    # Vérifier si scrapable
    domaine = urlsplit(url).netloc.lower().replace("www.", "")
    if any(d in domaine for d in DOMAINES_EXCLUS_SCRAPING):
        logger.debug(f"Domaine exclu : {domaine}")
        return None

    max_pages = settings.pages_par_site()
    pages_a_traiter = [url]
    urls_vues: set[str] = set()
    textes: list[str] = []
    schema_data: dict = {}
    disallowed: set[str] = set()

    async with httpx.AsyncClient(verify=False, timeout=settings.request_timeout) as client:

        # Robots.txt (seulement pour la page principale)
        try:
            disallowed = await check_robots(url, client)
        except Exception:
            pass

        while pages_a_traiter and len(urls_vues) < max_pages:
            page_url = pages_a_traiter.pop(0)
            if page_url in urls_vues:
                continue
            urls_vues.add(page_url)

            # Délai poli
            if len(urls_vues) > 1:
                await asyncio.sleep(settings.scrape_delay_seconds)

            # Fetch HTTP
            try:
                response = await _fetch_html(page_url, client)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in (403, 429):
                    logger.warning(f"HTTP {code} : {page_url[:50]} — skip")
                elif code == 404:
                    logger.debug(f"HTTP 404 : {page_url[:50]}")
                else:
                    logger.warning(f"HTTP {code} : {page_url[:50]}")
                continue
            except httpx.RequestError as exc:
                logger.warning(f"HTTP Request error : {page_url[:50]} : {exc}")
                continue

            ctype = (response.headers.get("Content-Type") or "").lower()

            # PDF
            if "pdf" in ctype or page_url.lower().endswith(".pdf"):
                pdf_txt = await extraire_pdf(response.content, page_url)
                if pdf_txt:
                    textes.append(f"[PDF: {page_url}]\n{pdf_txt[:TAILLE_EXTRACTION_MAX]}")
                continue

            html = response.text[:TAILLE_HTML_MAX]

            # Schema.org (une seule fois)
            if not schema_data:
                schema_data = await asyncio.to_thread(_extraire_schema_org, html)

            # Extraction texte
            texte_page = await _extraire_texte_html(html, page_url)

            # Browser si JS requis
            pw_ok = settings.playwright_actif()
            sans_browser = any(d in domaine for d in DOMAINES_SANS_BROWSER)
            if not sans_browser and pw_ok and _necessite_browser(html, texte_page):
                try:
                    from core.browser_pool import BrowserPool
                    pool = await BrowserPool.get_instance(
                        max_contexts=getattr(settings, "browser_max_contexts", 2)
                    )
                    html_js = await pool.fetch(page_url)
                    if html_js:
                        if not schema_data:
                            schema_data = await asyncio.to_thread(_extraire_schema_org, html_js)
                        t_js = await _extraire_texte_html(html_js, page_url)
                        if t_js and (not texte_page or len(t_js) > len(texte_page)):
                            texte_page = t_js
                            html = html_js
                except Exception as exc:
                    logger.warning(f"Browser fallback échec : {exc}")

            if texte_page:
                textes.append(f"[PAGE: {page_url}]\n{texte_page}")

            # Liens internes pour crawl multi-pages
            if len(urls_vues) < max_pages:
                liens = await asyncio.to_thread(_extraire_liens_internes, html, page_url, disallowed)
                for lien in liens:
                    if lien not in urls_vues and lien not in pages_a_traiter:
                        pages_a_traiter.append(lien)

        # Dernier recours : browser si aucun texte
        if not textes and settings.playwright_actif():
            sans_browser = any(d in domaine for d in DOMAINES_SANS_BROWSER)
            if not sans_browser:
                try:
                    from core.browser_pool import BrowserPool
                    pool = await BrowserPool.get_instance()
                    html_js = await pool.fetch(url)
                    if html_js:
                        schema_data = await asyncio.to_thread(_extraire_schema_org, html_js)
                        t = await _extraire_texte_html(html_js, url)
                        if t:
                            textes.append(f"[PAGE JS: {url}]\n{t}")
                except Exception as exc:
                    logger.warning(f"Browser last resort échec : {exc}")

    if not textes:
        logger.debug(f"Aucun contenu : {url[:60]}")
        return None

    # Assemblage
    blocs: list[str] = []
    if schema_data:
        lines = ["=== DONNÉES STRUCTURÉES (schema.org) ==="]
        for k, v in schema_data.items():
            if isinstance(v, list):
                lines.append(f"{k}: {', '.join(str(x) for x in v)}")
            else:
                lines.append(f"{k}: {v}")
        blocs.append("\n".join(lines))
    blocs.extend(textes)

    texte_final = "\n\n---\n\n".join(blocs)
    await asyncio.to_thread(enregistrer_page, url, texte_final)
    logger.info(f"Extrait {len(texte_final):,} chars depuis {url[:50]} ({len(urls_vues)} pages)")
    return texte_final


# ---------------------------------------------------------------------------
# Crawl ciblé d'un site
# ---------------------------------------------------------------------------

async def crawl_site(
    url: str,
    objective: str = "",
    max_pages: int = 6,
    max_depth: int = 2,
    use_sitemap: bool = True,
) -> dict:
    """
    Crawl intelligent d'un site pour extraire des informations ciblées.

    Retourne :
    {
        "text": str,           # Texte combiné de toutes les pages
        "pages_found": int,
        "documents": list,     # PDFs trouvés
        "schema_data": dict,
        "sitemap_urls": list,
    }
    """
    result = {
        "text": "",
        "pages_found": 0,
        "documents": [],
        "schema_data": {},
        "sitemap_urls": [],
    }

    # Mots-clés de l'objectif pour scorer les pages
    objective_words = set(re.findall(r"[\w\u00C0-\u024F]+", objective.lower())) if objective else set()

    textes: list[str] = []
    urls_vues: set[str] = set()
    schema_data: dict = {}

    async with httpx.AsyncClient(verify=False, timeout=15) as client:

        # Sitemap
        if use_sitemap:
            sitemap_urls = await fetch_sitemap_urls(url, client)
            if sitemap_urls:
                result["sitemap_urls"] = sitemap_urls
                # Scorer les URLs du sitemap par rapport à l'objectif
                if objective_words:
                    scored = []
                    for su in sitemap_urls:
                        path = urlsplit(su).path.lower()
                        score = sum(1 for w in objective_words if w in path)
                        scored.append((score, su))
                    scored.sort(reverse=True)
                    priority_urls = [su for _, su in scored[:max_pages]]
                else:
                    priority_urls = sitemap_urls[:max_pages]
            else:
                priority_urls = [url]
        else:
            priority_urls = [url]

        queue = list(priority_urls)
        depth_map: dict[str, int] = {u: 0 for u in queue}

        while queue and len(urls_vues) < max_pages:
            page_url = queue.pop(0)
            if page_url in urls_vues:
                continue
            current_depth = depth_map.get(page_url, 0)
            if current_depth > max_depth:
                continue
            urls_vues.add(page_url)

            if len(urls_vues) > 1:
                await asyncio.sleep(settings.scrape_delay_seconds)

            try:
                response = await _fetch_html(page_url, client)
            except Exception as exc:
                logger.debug(f"crawl_site skip {page_url[:40]}: {exc}")
                continue

            ctype = (response.headers.get("Content-Type") or "").lower()

            if "pdf" in ctype or page_url.lower().endswith(".pdf"):
                pdf_txt = await extraire_pdf(response.content, page_url)
                if pdf_txt:
                    textes.append(f"[PDF: {page_url}]\n{pdf_txt[:8000]}")
                    result["documents"].append({"url": page_url, "type": "pdf"})
                continue

            html = response.text[:TAILLE_HTML_MAX]
            if not schema_data:
                schema_data = await asyncio.to_thread(_extraire_schema_org, html)
            texte_page = await _extraire_texte_html(html, page_url)

            if texte_page:
                textes.append(f"[PAGE: {page_url}]\n{texte_page}")

            # Chercher PDFs dans les liens
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = str(a.get("href", ""))
                if ".pdf" in href.lower():
                    pdf_url = urljoin(page_url, href)
                    result["documents"].append({"url": pdf_url, "type": "pdf_link"})

            # Liens internes pour crawl
            if current_depth < max_depth:
                liens = await asyncio.to_thread(_extraire_liens_internes, html, page_url)
                for lien in liens:
                    if lien not in urls_vues and lien not in queue:
                        queue.append(lien)
                        depth_map[lien] = current_depth + 1

    result["schema_data"] = schema_data
    result["pages_found"] = len(urls_vues)
    result["text"] = "\n\n---\n\n".join(textes)[:TAILLE_EXTRACTION_MAX * 3]

    if schema_data:
        schema_lines = ["=== DONNÉES STRUCTURÉES ==="]
        for k, v in schema_data.items():
            schema_lines.append(f"{k}: {v}")
        result["text"] = "\n".join(schema_lines) + "\n\n" + result["text"]

    return result


# ---------------------------------------------------------------------------
# Helpers compatibilité
# ---------------------------------------------------------------------------

def _detecter_type_source(url: str) -> str:
    chemin = urlsplit(url).path.lower()
    domaine = urlsplit(url).netloc.lower()
    if chemin.endswith(".pdf") or ".pdf" in chemin:
        return "pdf"
    if "linkedin.com" in domaine:
        return "linkedin"
    if any(s in chemin for s in ("/news/", "/actualites/", "/blog/", "/press/")) or "news" in domaine:
        return "news"
    return "html"


def url_scrapable(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    domaine = urlsplit(url).netloc.lower()
    return not any(
        domaine == e or domaine.endswith("." + e)
        for e in DOMAINES_EXCLUS_SCRAPING
    )