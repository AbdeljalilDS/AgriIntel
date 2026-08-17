"""
Query Planner — génère des familles de requêtes structurées pour chaque étude.

Principes :
- Les requêtes sont organisées par DIMENSION (discovery, company, financial, tech, etc.)
- Chaque dimension a une priorité et un budget de requêtes
- Le SearchFeedbackLoop mesure l'information_gain pour prioriser les prochaines requêtes
- Aucune requête hardcodée sur un secteur/pays spécifique — tout est paramétrable

Architecture inspirée de systèmes comme Perplexity Deep Research et Gemini Deep Research.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterator

from core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Familles de requêtes
# ---------------------------------------------------------------------------

QUERY_FAMILY_WEIGHTS = {
    "discovery":      1.0,   # chercher les acteurs
    "company":        0.9,   # approfondir les entreprises
    "financial":      0.7,   # données financières
    "technology":     0.7,   # technologies
    "certifications": 0.6,   # certifications qualité
    "news":           0.6,   # actualités
    "export":         0.6,   # export / international
    "documents":      0.5,   # PDF, rapports
    "domain_search":  0.5,   # recherches site:
    "academic":       0.3,   # sources académiques
    "startup":        0.8,   # écosystème startup
}


@dataclass
class PlannedQuery:
    query:        str
    family:       str
    priority:     float = 1.0
    dimension:    str = ""
    entity_name:  str = ""
    angle:        str = ""
    used:         bool = False
    results_count: int = 0
    new_entities:  int = 0
    new_facts:     int = 0
    information_gain: float = 0.0
    executed_at:   float = 0.0

    @property
    def query_hash(self) -> str:
        return hashlib.md5(self.query.strip().lower().encode()).hexdigest()[:8]


class QueryPlanner:
    """
    Génère des plans de requêtes adaptés à l'objectif de recherche.
    Totalement générique — pas de référence à un secteur ou pays fixe.
    """

    def __init__(
        self,
        target: str,
        objective: str,
        geography: str = "",
        sector: str = "",
        research_type: str = "benchmark",
        language: str = "fr",
    ):
        self.target        = target
        self.objective     = objective
        self.geography     = geography
        self.sector        = sector
        self.research_type = research_type
        self.language      = language
        self._queries: list[PlannedQuery] = []
        self._used_hashes: set[str] = set()

    # ------------------------------------------------------------------
    # Génération des requêtes par famille
    # ------------------------------------------------------------------

    def _geo_suffix(self) -> str:
        return f" {self.geography}" if self.geography else ""

    def _sector_suffix(self) -> str:
        return f" {self.sector}" if self.sector else ""

    def generate_discovery_queries(self) -> list[PlannedQuery]:
        """Requêtes pour trouver les acteurs du marché."""
        geo = self._geo_suffix()
        sec = self._sector_suffix()
        queries = [
            PlannedQuery(f"concurrents {self.target}{geo}", "discovery", 1.0, "identity", angle="competitors"),
            PlannedQuery(f"leaders marché{sec}{geo}", "discovery", 0.95, "identity", angle="market_leaders"),
            PlannedQuery(f"principales entreprises{sec}{geo}", "discovery", 0.90, "identity", angle="main_players"),
            PlannedQuery(f"alternatives {self.target}{geo}", "discovery", 0.85, "identity", angle="alternatives"),
            PlannedQuery(f"acteurs secteur{sec}{geo} liste", "discovery", 0.80, "identity", angle="sector_actors"),
            PlannedQuery(f"nouveaux entrants{sec}{geo}", "discovery", 0.70, "identity", angle="new_entrants"),
            PlannedQuery(f"{self.target} concurrent direct indirect{geo}", "discovery", 0.90, "identity", angle="direct_indirect"),
        ]
        if self.geography:
            queries += [
                PlannedQuery(f"top entreprises {self.geography}{sec}", "discovery", 0.85, "identity", angle="top_geo"),
                PlannedQuery(f"market map{sec} {self.geography}", "discovery", 0.75, "identity", angle="market_map"),
            ]
        return queries

    def generate_company_queries(self, entity_name: str) -> list[PlannedQuery]:
        """Requêtes pour approfondir une entreprise spécifique."""
        geo = self._geo_suffix()
        return [
            PlannedQuery(f"{entity_name} activités produits services", "company", 0.90, "products", entity_name, "products"),
            PlannedQuery(f"{entity_name} présentation profil entreprise", "company", 0.85, "identity", entity_name, "profile"),
            PlannedQuery(f"{entity_name} site officiel about", "company", 0.80, "identity", entity_name, "official_site"),
            PlannedQuery(f"{entity_name} fondateurs équipe dirigeante", "company", 0.70, "team", entity_name, "team"),
            PlannedQuery(f"{entity_name} marchés ciblés clients", "company", 0.70, "export", entity_name, "markets"),
        ]

    def generate_financial_queries(self, entity_name: str = "") -> list[PlannedQuery]:
        """Requêtes pour données financières."""
        base = entity_name or self.target
        geo = self._geo_suffix()
        return [
            PlannedQuery(f"{base} chiffre d'affaires revenus", "financial", 0.80, "finance", base, "revenue"),
            PlannedQuery(f"{base} financement investissement levée fonds", "financial", 0.75, "finance", base, "funding"),
            PlannedQuery(f"{base} rapport annuel bilan", "financial", 0.70, "finance", base, "annual_report"),
            PlannedQuery(f"{base} investisseurs actionnaires capital", "financial", 0.65, "finance", base, "investors"),
            PlannedQuery(f"{base} acquisition rachat fusion", "financial", 0.60, "finance", base, "ma"),
        ]

    def generate_technology_queries(self, entity_name: str = "") -> list[PlannedQuery]:
        """Requêtes pour technologies et innovation."""
        base = entity_name or self.target
        sec = self._sector_suffix()
        return [
            PlannedQuery(f"{base} technologies innovation R&D", "technology", 0.80, "technology", base, "tech"),
            PlannedQuery(f"{base} intelligence artificielle digital transformation", "technology", 0.70, "technology", base, "ai"),
            PlannedQuery(f"{base} plateforme système IoT", "technology", 0.65, "technology", base, "iot"),
            PlannedQuery(f"innovation technologique{sec} brevets", "technology", 0.60, "technology", angle="innovation"),
            PlannedQuery(f"{base} recherche développement laboratoire", "technology", 0.55, "technology", base, "rd"),
        ]

    def generate_certification_queries(self, entity_name: str = "") -> list[PlannedQuery]:
        """Requêtes pour certifications et qualité."""
        base = entity_name or self.target
        sec = self._sector_suffix()
        return [
            PlannedQuery(f"{base} certifications ISO qualité", "certifications", 0.75, "certifications", base, "iso"),
            PlannedQuery(f"{base} GlobalG.A.P. Bio organique label", "certifications", 0.70, "certifications", base, "globalgap"),
            PlannedQuery(f"{base} HACCP BRC IFS sécurité alimentaire", "certifications", 0.65, "certifications", base, "haccp"),
            PlannedQuery(f"certifications standards qualité{sec}{self._geo_suffix()}", "certifications", 0.60, "certifications", angle="standards"),
            PlannedQuery(f"{base} ESG durabilité RSE", "certifications", 0.55, "certifications", base, "esg"),
        ]

    def generate_news_queries(self, entity_name: str = "") -> list[PlannedQuery]:
        """Requêtes pour actualités et signaux de croissance."""
        base = entity_name or self.target
        geo = self._geo_suffix()
        return [
            PlannedQuery(f"{base} actualités news 2024 2025", "news", 0.80, "news", base, "recent_news"),
            PlannedQuery(f"{base} partenariat accord deal", "news", 0.70, "news", base, "partnership"),
            PlannedQuery(f"{base} expansion croissance nouveaux marchés", "news", 0.70, "news", base, "growth"),
            PlannedQuery(f"{base} recrutement embauche effectif", "news", 0.55, "news", base, "hiring"),
            PlannedQuery(f"{base} lancement produit service nouveau", "news", 0.65, "news", base, "product_launch"),
            PlannedQuery(f"actualités secteur{self._sector_suffix()}{geo} 2024 2025", "news", 0.65, "news", angle="sector_news"),
        ]

    def generate_export_queries(self, entity_name: str = "") -> list[PlannedQuery]:
        """Requêtes pour export et international."""
        base = entity_name or self.target
        geo = self._geo_suffix()
        return [
            PlannedQuery(f"{base} export international pays", "export", 0.80, "export", base, "export_countries"),
            PlannedQuery(f"{base} Europe Afrique Moyen-Orient marchés", "export", 0.70, "export", base, "regions"),
            PlannedQuery(f"exportateurs{self._sector_suffix()}{geo} liste", "export", 0.75, "export", angle="exporters"),
            PlannedQuery(f"{base} import export volume", "export", 0.60, "export", base, "volume"),
        ]

    def generate_document_queries(self, entity_name: str = "") -> list[PlannedQuery]:
        """Requêtes pour trouver des documents PDF."""
        base = entity_name or self.target
        sec = self._sector_suffix()
        geo = self._geo_suffix()
        return [
            PlannedQuery(f"{base} rapport annuel filetype:pdf", "documents", 0.75, "finance", base, "annual_report_pdf"),
            PlannedQuery(f"{base} brochure catalogue filetype:pdf", "documents", 0.65, "products", base, "brochure"),
            PlannedQuery(f"étude marché{sec}{geo} filetype:pdf", "documents", 0.70, "identity", angle="market_study"),
            PlannedQuery(f"rapport sectoriel{sec}{geo} 2024 2025 filetype:pdf", "documents", 0.65, "identity", angle="sector_report"),
            PlannedQuery(f"{base} présentation investisseurs pitch deck", "documents", 0.60, "finance", base, "pitch"),
        ]

    def generate_domain_search_queries(self, sites: list[str], keywords: str = "") -> list[PlannedQuery]:
        """Requêtes site: pour les domaines sectoriels."""
        kw = keywords or self.target
        queries = []
        for site in sites[:8]:
            queries.append(
                PlannedQuery(
                    f"{kw} site:{site}",
                    "domain_search",
                    0.65,
                    "identity",
                    angle=f"site_{site}",
                )
            )
        return queries

    def generate_startup_queries(self) -> list[PlannedQuery]:
        """Requêtes spécialisées pour les startups."""
        geo = self._geo_suffix()
        sec = self._sector_suffix()
        return [
            PlannedQuery(f"startups{sec}{geo} liste 2024 2025", "startup", 1.0, "identity", angle="startup_list"),
            PlannedQuery(f"startups innovantes{sec}{geo}", "startup", 0.90, "identity", angle="innovative_startups"),
            PlannedQuery(f"incubateurs accélérateurs{sec}{geo}", "startup", 0.85, "identity", angle="incubators"),
            PlannedQuery(f"financement startup levée fonds{sec}{geo}", "startup", 0.80, "finance", angle="funding"),
            PlannedQuery(f"écosystème entrepreneuriat{geo}", "startup", 0.75, "identity", angle="ecosystem"),
            PlannedQuery(f"investisseurs venture capital{sec}{geo}", "startup", 0.75, "finance", angle="vc"),
            PlannedQuery(f"programme startup gouvernement{geo}", "startup", 0.70, "identity", angle="gov_program"),
            PlannedQuery(f"demo day pitch startup{sec}{geo}", "startup", 0.65, "identity", angle="events"),
            PlannedQuery(f"tech{sec} entrepreneur{geo}", "startup", 0.60, "identity", angle="entrepreneurs"),
        ]

    def generate_recovery_queries(
        self,
        found_entity: str = "",
        low_result_reason: str = "unknown",
    ) -> list[PlannedQuery]:
        """
        Requêtes de RECOVERY quand peu de résultats sont trouvés.
        Génère de nouveaux angles totalement différents.
        """
        geo = self._geo_suffix()
        sec = self._sector_suffix()
        base = found_entity or self.target
        recovery = []

        if low_result_reason in ("too_broad", "unknown"):
            recovery += [
                PlannedQuery(f"\"{self.target}\" concurrent benchmark", "discovery", 0.85, angle="quoted_search"),
                PlannedQuery(f"who competes with {self.target}", "discovery", 0.80, angle="english_search"),
            ]

        if low_result_reason in ("language", "unknown"):
            recovery += [
                PlannedQuery(f"{self.target} competitors market{geo}", "discovery", 0.80, angle="english"),
                PlannedQuery(f"{base} منافسون سوق", "discovery", 0.70, angle="arabic"),  # arabique si pertinent
            ]

        if found_entity:
            recovery += [
                PlannedQuery(f"concurrent de {found_entity}{geo}", "discovery", 0.85, found_entity, "peer_of"),
                PlannedQuery(f"similaire à {found_entity}{sec}", "discovery", 0.80, found_entity, "similar_to"),
                PlannedQuery(f"{found_entity} partenaires clients fournisseurs", "company", 0.75, found_entity, "ecosystem"),
            ]

        recovery += [
            PlannedQuery(f"association professionnelle{sec}{geo}", "discovery", 0.70, angle="association"),
            PlannedQuery(f"chambre commerce{sec}{geo}", "discovery", 0.65, angle="chamber"),
            PlannedQuery(f"rapport marché{sec}{geo} acteurs", "discovery", 0.70, angle="market_report"),
            PlannedQuery(f"annuaire entreprises{sec}{geo}", "discovery", 0.65, angle="directory"),
        ]

        return recovery

    # ------------------------------------------------------------------
    # Plan complet
    # ------------------------------------------------------------------

    def build_plan(
        self,
        domain_sites: list[str] | None = None,
        include_startup: bool = False,
    ) -> list[PlannedQuery]:
        """Construit le plan complet de requêtes, trié par priorité."""
        all_queries: list[PlannedQuery] = []

        # Phase BREADTH — trouver les acteurs
        all_queries += self.generate_discovery_queries()
        if include_startup or self.research_type == "startup":
            all_queries += self.generate_startup_queries()

        # Phase DEPTH — approfondir la cible
        all_queries += self.generate_company_queries(self.target)
        all_queries += self.generate_financial_queries(self.target)
        all_queries += self.generate_technology_queries(self.target)
        all_queries += self.generate_certification_queries(self.target)
        all_queries += self.generate_news_queries(self.target)
        all_queries += self.generate_export_queries(self.target)
        all_queries += self.generate_document_queries(self.target)

        # Domaines sectoriels
        if domain_sites:
            all_queries += self.generate_domain_search_queries(domain_sites, self.target)

        # Tri par priorité
        all_queries.sort(key=lambda q: q.priority, reverse=True)

        # Dédupliquer
        seen: set[str] = set()
        unique: list[PlannedQuery] = []
        for q in all_queries:
            h = q.query_hash
            if h not in seen:
                seen.add(h)
                unique.append(q)

        self._queries = unique
        logger.info(f"QueryPlanner: {len(unique)} requêtes planifiées pour '{self.target}'")
        return unique

    def next_query(self) -> PlannedQuery | None:
        """Retourne la prochaine requête non utilisée avec la meilleure priorité."""
        for q in self._queries:
            if not q.used:
                return q
        return None

    def mark_used(self, query: PlannedQuery, results: int, new_entities: int, new_facts: int) -> None:
        """Marque une requête comme utilisée et enregistre les gains."""
        query.used = True
        query.results_count = results
        query.new_entities = new_entities
        query.new_facts = new_facts
        query.information_gain = (new_entities * 0.6 + new_facts * 0.4) / max(results, 1)
        query.executed_at = time.time()

    def add_entity_queries(self, entity_name: str) -> None:
        """Ajoute des requêtes pour une entité nouvellement découverte."""
        new_queries = (
            self.generate_company_queries(entity_name) +
            self.generate_financial_queries(entity_name) +
            self.generate_technology_queries(entity_name) +
            self.generate_news_queries(entity_name) +
            self.generate_export_queries(entity_name) +
            self.generate_certification_queries(entity_name)
        )
        seen_hashes = {q.query_hash for q in self._queries}
        for q in new_queries:
            if q.query_hash not in seen_hashes:
                seen_hashes.add(q.query_hash)
                self._queries.append(q)
        # Re-trier
        self._queries.sort(key=lambda q: (q.used, -q.priority))
        logger.info(f"Requêtes ajoutées pour '{entity_name}': {len(new_queries)}")

    @property
    def remaining_count(self) -> int:
        return sum(1 for q in self._queries if not q.used)

    @property
    def average_gain(self) -> float:
        used = [q for q in self._queries if q.used]
        if not used:
            return 0.0
        return sum(q.information_gain for q in used) / len(used)

    def get_stats(self) -> dict:
        used = [q for q in self._queries if q.used]
        return {
            "total": len(self._queries),
            "used": len(used),
            "remaining": self.remaining_count,
            "avg_gain": round(self.average_gain, 4),
            "total_results": sum(q.results_count for q in used),
            "total_new_entities": sum(q.new_entities for q in used),
            "total_new_facts": sum(q.new_facts for q in used),
        }


# ---------------------------------------------------------------------------
# SearchFeedbackLoop
# ---------------------------------------------------------------------------

class SearchFeedbackLoop:
    """
    Suit l'information_gain de chaque requête pour guider les prochaines.
    Pénalise les requêtes redondantes, favorise les angles à fort gain.
    """

    def __init__(self, planner: QueryPlanner):
        self.planner = planner
        self._gains_by_family: dict[str, list[float]] = defaultdict(list)
        self._consecutive_low_gain = 0
        self.low_gain_threshold = 0.02

    def record(self, query: PlannedQuery) -> None:
        self._gains_by_family[query.family].append(query.information_gain)
        if query.information_gain < self.low_gain_threshold:
            self._consecutive_low_gain += 1
        else:
            self._consecutive_low_gain = 0

    def family_gain(self, family: str) -> float:
        gains = self._gains_by_family.get(family, [])
        return sum(gains) / len(gains) if gains else 0.5  # 0.5 par défaut = neutre

    def is_diminishing(self, window: int = 3) -> bool:
        return self._consecutive_low_gain >= window

    def recommend_next_family(self) -> str:
        """Retourne la famille avec le meilleur gain potentiel."""
        best = max(
            QUERY_FAMILY_WEIGHTS.keys(),
            key=lambda f: QUERY_FAMILY_WEIGHTS[f] * (1 + self.family_gain(f)),
        )
        return best
