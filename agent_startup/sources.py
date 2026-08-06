from agent_benchmark.sources import etendre_requete, rechercher_avec_repli

SITES_STARTUP = [
    "https://www.start-up.ma/liste-de-startups-par-secteur/foodtech-agritech/",
    "https://www.agtechcenter.ma/en",
    "https://medias24.com/sujet/agritech/",
    "https://leseco.ma",
    "https://www.agrimaroc.ma",
]

STARTUPS_CONNUES = ["Agri 4.0", "Green Watech", "Arwa Solutions", "Fila7a.com"]


def generer_requetes_startup(cible: str) -> list[str]:
    base = f"startup agritech Maroc {cible}".strip()
    return etendre_requete(base) + [
        f"{cible} startup incubateur accélérateur Maroc",
        f"{cible} startup agriculture financement investisseurs Maroc",
    ]


def rechercher_principal(requete: str) -> list[dict]:
    """Tavily → Google → DuckDuckGo → News → sites sectoriels."""
    return rechercher_avec_repli(requete)
