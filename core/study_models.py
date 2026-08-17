"""
Modèles centraux de l'étude de recherche — Enterprise AI Research Engine.

Architecture :
  ResearchStudy         — étude complète 
  ResearchPlan          — plan structuré avant exécution
  Candidate             — entreprise potentielle avant résolution
  ResolvedEntity        — entité validée et déduplicatée
  Fact                  — donnée atomique avec provenance
  Source                — source avec qualité, tier, fraîcheur
  Evidence              — preuve liant un fait à une source
  Contradiction         — conflit entre deux faits
  CoverageReport        — matrice de couverture
  Finding               — insight / conclusion
  Recommendation        — recommandation actionnée
  ResearchEvent         — événement d'observabilité
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------

class StudyStatus(str, Enum):
    PLANNING         = "planning"
    RUNNING          = "running"
    COMPLETE         = "complete"
    PARTIALLY_COMPLETE = "partially_complete"
    INSUFFICIENT_DATA = "insufficient_data"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT          = "timeout"
    FAILED           = "failed"


class StudyType(str, Enum):
    BENCHMARK  = "benchmark"
    STARTUP    = "startup"
    MARKET     = "market"
    CUSTOM     = "custom"


class BenchmarkType(str, Enum):
    COMPETITIVE   = "competitive"
    FUNCTIONAL    = "functional"
    STRATEGIC     = "strategic"
    PERFORMANCE   = "performance"
    PROCESS       = "process"
    GENERIC       = "generic"


class SourceTier(int, Enum):
    TIER_1 = 1   # gouvernement, régulateur, site officiel, rapport annuel
    TIER_2 = 2   # universités, associations pro, banques, organismes int.
    TIER_3 = 3   # presse spécialisée, presse économique
    TIER_4 = 4   # annuaires, agrégateurs, plateformes secondaires
    TIER_5 = 5   # réseaux sociaux, forums, sources non vérifiées


class FactStatus(str, Enum):
    VERIFIED           = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    CONFLICTING        = "conflicting"
    UNVERIFIED         = "unverified"
    STALE              = "stale"


class EntityRelationType(str, Enum):
    DIRECT_COMPETITOR   = "direct_competitor"
    INDIRECT_COMPETITOR = "indirect_competitor"
    SUPPLIER            = "supplier"
    PARTNER             = "partner"
    CUSTOMER            = "customer"
    INVESTOR            = "investor"
    INCUBATOR           = "incubator"
    ACCELERATOR         = "accelerator"
    IRRELEVANT          = "irrelevant"
    UNKNOWN             = "unknown"


class ResearchPhase(str, Enum):
    PLANNING   = "planning"
    BREADTH    = "breadth"
    FILTER     = "filter"
    DEPTH      = "depth"
    VERIFY     = "verify"
    ENRICH     = "enrich"
    COMPARE    = "compare"
    ANALYZE    = "analyze"
    REPORT     = "report"
    COMPLETE   = "complete"


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

class Source(BaseModel):
    source_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:        str = ""
    url:             str
    domain:          str = ""
    title:           str = ""
    snippet:         str = ""
    provider:        str = ""          # tavily, google, bing, duckduckgo, rss, …
    source_type:     str = "html"      # html, pdf, rss, api, sitemap
    tier:            SourceTier = SourceTier.TIER_4
    authority:       float = 0.0       # 0-1
    relevance:       float = 0.0       # 0-1
    freshness:       float = 0.0       # 0-1
    officiality:     float = 0.0       # 0-1
    credibility:     float = 0.0       # 0-1
    reliability:     float = 0.0       # score global 0-1
    published_at:    Optional[datetime] = None
    collected_at:    datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    accessible:      bool = True
    content_length:  int = 0

    @property
    def quality_score(self) -> float:
        """Score de qualité global pondéré."""
        return round(
            0.30 * self.authority +
            0.25 * self.relevance +
            0.20 * self.freshness +
            0.15 * self.officiality +
            0.10 * self.credibility,
            3
        )


# ---------------------------------------------------------------------------
# Fact
# ---------------------------------------------------------------------------

class Fact(BaseModel):
    fact_id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:     str = ""
    entity_id:    str = ""
    fact_type:    str = ""             # description, revenue, technology, certification, …
    dimension:    str = ""             # identity, products, finance, export, tech, cert, news
    value:        str = ""
    raw_value:    str = ""             # valeur brute avant nettoyage
    unit:         str = ""
    source_id:    str = ""
    source_url:   str = ""
    page_number:  Optional[int] = None
    excerpt:      str = ""             # extrait exact de la source
    published_at: Optional[datetime] = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence:   float = 0.0
    status:       FactStatus = FactStatus.UNVERIFIED
    verified_by:  str = ""
    notes:        str = ""


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------

class Contradiction(BaseModel):
    contradiction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:         str = ""
    entity_id:        str = ""
    fact_type:        str = ""
    fact_a_id:        str = ""
    fact_b_id:        str = ""
    value_a:          str = ""
    value_b:          str = ""
    source_a:         str = ""
    source_b:         str = ""
    description:      str = ""
    possible_cause:   str = ""    # year_difference, currency, scope, approximation
    resolved:         bool = False
    resolution:       str = ""
    confidence_a:     float = 0.0
    confidence_b:     float = 0.0
    detected_at:      datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Candidate (avant résolution d'entité)
# ---------------------------------------------------------------------------

class Candidate(BaseModel):
    candidate_id:   str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:       str = ""
    name:           str
    raw_name:       str = ""
    domain:         str = ""
    country:        str = ""
    source_url:     str = ""
    snippet:        str = ""
    relation_type:  EntityRelationType = EntityRelationType.UNKNOWN
    relevance:      float = 0.0
    resolved:       bool = False
    resolved_to:    str = ""          # entity_id si résolu
    aliases:        list[str] = Field(default_factory=list)
    discovered_at:  datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# ResolvedEntity (entité principale validée)
# ---------------------------------------------------------------------------

class ResolvedEntity(BaseModel):
    entity_id:          str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:           str = ""
    canonical_name:     str
    normalized_name:    str = ""
    domain:             str = ""
    country:            str = ""
    sector:             str = ""
    description:        str = ""
    website:            str = ""
    founded_year:       str = ""
    headquarters:       str = ""
    employees:          str = ""
    revenue:            str = ""
    relation_type:      EntityRelationType = EntityRelationType.UNKNOWN
    aliases:            list[str] = Field(default_factory=list)
    products:           list[str] = Field(default_factory=list)
    services:           list[str] = Field(default_factory=list)
    technologies:       list[str] = Field(default_factory=list)
    certifications:     list[str] = Field(default_factory=list)
    export_countries:   list[str] = Field(default_factory=list)
    target_markets:     list[str] = Field(default_factory=list)
    partners:           list[str] = Field(default_factory=list)
    investors:          list[str] = Field(default_factory=list)
    founders:           list[str] = Field(default_factory=list)
    funding_stage:      str = ""
    funding_amount:     str = ""
    incubators:         list[str] = Field(default_factory=list)
    accelerators:       list[str] = Field(default_factory=list)
    strengths:          list[str] = Field(default_factory=list)
    weaknesses:         list[str] = Field(default_factory=list)
    opportunities:      list[str] = Field(default_factory=list)
    threats:            list[str] = Field(default_factory=list)
    social_media:       list[str] = Field(default_factory=list)
    news_signals:       list[str] = Field(default_factory=list)
    traction_signals:   list[str] = Field(default_factory=list)
    # Scores
    coverage_score:     float = 0.0   # 0-1 : proportion de dimensions documentées
    confidence_score:   float = 0.0   # 0-1 : qualité des preuves
    relevance_score:    float = 0.0   # 0-1 : pertinence par rapport à l'objectif
    # Provenance
    source_urls:        list[str] = Field(default_factory=list)
    fact_ids:           list[str] = Field(default_factory=list)
    candidate_ids:      list[str] = Field(default_factory=list)
    # Timestamps
    first_seen:         datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated:       datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verified:           bool = False

    def cle_normalisee(self) -> str:
        import unicodedata
        return unicodedata.normalize("NFKD", self.canonical_name)\
            .encode("ascii", "ignore").decode().strip().lower()


# ---------------------------------------------------------------------------
# CoverageDimension
# ---------------------------------------------------------------------------

DIMENSIONS = [
    "identity",       # nom, siège, date création
    "products",       # produits / services
    "finance",        # CA, financement, investisseurs
    "technology",     # technologies, R&D, brevets
    "certifications", # ISO, GlobalGAP, Bio, HACCP
    "export",         # pays export, marchés
    "team",           # fondateurs, équipe clé
    "news",           # actualités, signaux
    "partners",       # partenaires, clients
    "sustainability", # ESG, environnement
]


class DimensionStatus(str, Enum):
    COMPLETE   = "complete"
    PARTIAL    = "partial"
    MISSING    = "missing"


class EntityCoverage(BaseModel):
    entity_id:    str
    entity_name:  str
    dimensions:   dict[str, DimensionStatus] = Field(default_factory=dict)

    @property
    def score(self) -> float:
        if not self.dimensions:
            return 0.0
        weights = {
            "identity": 0.20,
            "products": 0.15,
            "finance": 0.10,
            "technology": 0.10,
            "certifications": 0.10,
            "export": 0.10,
            "team": 0.05,
            "news": 0.05,
            "partners": 0.10,
            "sustainability": 0.05,
        }
        total = 0.0
        for dim, w in weights.items():
            status = self.dimensions.get(dim, DimensionStatus.MISSING)
            if status == DimensionStatus.COMPLETE:
                total += w
            elif status == DimensionStatus.PARTIAL:
                total += w * 0.5
        return round(total, 3)


class CoverageReport(BaseModel):
    study_id:           str = ""
    entities:           list[EntityCoverage] = Field(default_factory=list)
    overall_score:      float = 0.0
    critical_gaps:      list[str] = Field(default_factory=list)
    questions_covered:  list[str] = Field(default_factory=list)
    questions_missing:  list[str] = Field(default_factory=list)
    source_count:       int = 0
    fact_count:         int = 0
    evidence_density:   float = 0.0
    computed_at:        datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_overall(self) -> None:
        if self.entities:
            self.overall_score = round(
                sum(e.score for e in self.entities) / len(self.entities), 3
            )


# ---------------------------------------------------------------------------
# StopCriteria
# ---------------------------------------------------------------------------

class StopCriteria(BaseModel):
    """Critères d'arrêt multi-dimensionnels — remplace len(entities) >= min."""
    min_coverage_score:          float = 0.55   # couverture globale min
    min_entities:                int   = 3       # nb minimum absolu
    min_source_quality:          float = 0.40   # qualité source moyenne
    min_evidence_density:        float = 0.30   # preuves par entité
    max_budget_tokens:           int   = 50_000  # tokens LLM approximatifs
    max_search_queries:          int   = 40      # requêtes web max
    max_pages_scraped:           int   = 80      # pages scrappées max
    max_tours:                   int   = 12      # tours agent max
    diminishing_returns_threshold: float = 0.02 # gain minimal par recherche

    def should_stop(
        self,
        coverage: CoverageReport,
        entities_count: int,
        queries_used: int,
        pages_scraped: int,
        tour: int,
        last_gain: float = 0.10,
    ) -> tuple[bool, str]:
        """Retourne (stop, raison)."""
        if tour >= self.max_tours:
            return True, f"max_tours atteint ({self.max_tours})"
        if queries_used >= self.max_search_queries:
            return True, f"budget_queries épuisé ({self.max_search_queries})"
        if pages_scraped >= self.max_pages_scraped:
            return True, f"budget_pages épuisé ({self.max_pages_scraped})"
        if entities_count == 0:
            return False, "aucune entité — continuer"
        if entities_count < self.min_entities:
            return False, f"entités insuffisantes ({entities_count}/{self.min_entities})"
        if coverage.overall_score < self.min_coverage_score:
            return False, f"couverture insuffisante ({coverage.overall_score:.2f}/{self.min_coverage_score})"
        if last_gain < self.diminishing_returns_threshold and tour > 4:
            return True, f"rendements décroissants ({last_gain:.3f} < {self.diminishing_returns_threshold})"
        return True, "objectifs atteints"


# ---------------------------------------------------------------------------
# ResearchPlan
# ---------------------------------------------------------------------------

class ResearchSubQuestion(BaseModel):
    question:   str
    priority:   int = 1           # 1=critique, 2=important, 3=optionnel
    dimension:  str = ""
    answered:   bool = False
    answer:     str = ""


class ResearchPlan(BaseModel):
    plan_id:           str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:          str = ""
    objective:         str = ""
    main_question:     str = ""
    sub_questions:     list[ResearchSubQuestion] = Field(default_factory=list)
    scope:             str = ""
    geography:         str = ""
    sector:            str = ""
    period:            str = ""
    benchmark_types:   list[BenchmarkType] = Field(default_factory=list)
    criteria:          list[str] = Field(default_factory=list)
    metrics:           list[str] = Field(default_factory=list)
    search_strategies: list[str] = Field(default_factory=list)
    priority_sources:  list[str] = Field(default_factory=list)
    secondary_sources: list[str] = Field(default_factory=list)
    stop_criteria:     StopCriteria = Field(default_factory=StopCriteria)
    created_at:        datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved:          bool = False


# ---------------------------------------------------------------------------
# Finding & Recommendation
# ---------------------------------------------------------------------------

class Finding(BaseModel):
    finding_id:   str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:     str = ""
    category:     str = ""           # market_trend, technology, gap, opportunity, threat
    title:        str = ""
    description:  str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    confidence:   float = 0.0
    importance:   int = 1            # 1=critique, 2=important, 3=informatif
    created_at:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Recommendation(BaseModel):
    rec_id:           str = Field(default_factory=lambda: str(uuid.uuid4()))
    study_id:         str = ""
    action:           str = ""
    reason:           str = ""
    evidence_ids:     list[str] = Field(default_factory=list)
    priority:         int = 1        # 1=haute, 2=moyenne, 3=basse
    impact:           str = "medium" # high, medium, low
    risk:             str = "low"    # high, medium, low
    confidence:       float = 0.0
    created_at:       datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# ResearchStudy — objet central
# ---------------------------------------------------------------------------

class ResearchStudy(BaseModel):
    study_id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id:        str = "default"
    run_id:         str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Paramètres de l'étude
    target:         str = ""
    objective:      str = ""
    geography:      str = ""
    industry:       str = ""
    research_type:  StudyType = StudyType.BENCHMARK
    depth:          str = "standard"   # standard | deep | quick

    # Plan
    plan:           Optional[ResearchPlan] = None

    # Résultats
    candidates:     list[Candidate] = Field(default_factory=list)
    entities:       list[ResolvedEntity] = Field(default_factory=list)
    sources:        list[Source] = Field(default_factory=list)
    facts:          list[Fact] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    findings:       list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    coverage:       Optional[CoverageReport] = None

    # Rapport
    report_markdown: str = ""
    executive_summary: str = ""

    # Métriques
    queries_used:   int = 0
    pages_scraped:  int = 0
    tokens_used:    int = 0
    elapsed_seconds: float = 0.0

    # Statut
    status:         StudyStatus = StudyStatus.PLANNING
    current_phase:  ResearchPhase = ResearchPhase.PLANNING
    status_reason:  str = ""

    # Timestamps
    created_at:     datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at:     Optional[datetime] = None
    completed_at:   Optional[datetime] = None

    # Événements (journal opérationnel)
    events:         list[dict[str, Any]] = Field(default_factory=list)

    def add_event(self, event_type: str, message: str, data: dict | None = None) -> None:
        self.events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "message": message,
            "phase": self.current_phase.value,
            "data": data or {},
        })

    def get_entity_by_name(self, name: str) -> ResolvedEntity | None:
        nl = name.strip().lower()
        return next((e for e in self.entities if e.canonical_name.lower() == nl), None)

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def fact_count(self) -> int:
        return len(self.facts)
