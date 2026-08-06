from types import SimpleNamespace

import core.scraper_base as scraper_base


class FakeResponse:
    def __init__(self, text: str, content_type: str = "text/html"):
        self.text = text
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None


def test_fetch_clean_text_collects_internal_pages(monkeypatch):
    pages = {
        "https://example.com/": "<html><body><h1>Home</h1><p>Welcome to the site.</p><a href='/about'>About</a></body></html>",
        "https://example.com/about": "<html><body><h1>About</h1><p>Detailed about section.</p></body></html>",
    }

    def fake_fetch_html(url: str):
        return FakeResponse(pages[url])

    def fake_extract_html(html: str, url: str):
        if "Detailed about section" in html:
            return "Detailed about section."
        if "Welcome to the site" in html:
            return "Welcome to the site."
        return None

    monkeypatch.setattr(scraper_base, "lire_page", lambda url: None)
    monkeypatch.setattr(scraper_base, "enregistrer_page", lambda url, text: None)
    monkeypatch.setattr(scraper_base, "_fetch_html", fake_fetch_html)
    monkeypatch.setattr(scraper_base, "_extraire_texte_html", fake_extract_html)

    texte = scraper_base.fetch_clean_text("https://example.com/")

    assert "Welcome to the site" in texte
    assert "Detailed about section" in texte


def test_extraire_liens_internes_priorise_pages_utiles():
    html = """
    <html><body>
        <a href='/about'>About us</a>
        <a href='/products'>Products</a>
        <a href='/privacy'>Privacy policy</a>
        <a href='/technology'>Technology</a>
    </body></html>
    """

    liens = scraper_base._extraire_liens_internes(html, "https://example.com/")

    assert liens[0].endswith("/technology")
    assert all(not lien.endswith("/privacy") for lien in liens)


def test_detecter_type_source_recognizes_pdf_news_and_linkedin():
    assert scraper_base._detecter_type_source("https://example.com/report.pdf") == "pdf"
    assert scraper_base._detecter_type_source("https://example.com/news/tech") == "news"
    assert scraper_base._detecter_type_source("https://www.linkedin.com/company/acme") == "linkedin"


def test_extraire_texte_rss_extracts_items():
    rss = """<rss version='2.0'><channel><title>Tech News</title><item><title>New release</title><description>Launch announced</description></item></channel></rss>"""

    texte = scraper_base._extraire_texte_rss(rss)

    assert "New release" in texte
    assert "Launch announced" in texte
