"""
Entity Resolution — déduplication et résolution d'identité des entités.

Principes :
- Une même entreprise peut apparaître sous plusieurs formes : "ABC", "ABC Maroc", "ABC Agriculture SARL"
- On construit une identité canonique basée sur : nom normalisé + domaine + pays
- On ne fusionne que si la confiance est suffisante
- On ne rejette pas deux entités différentes avec un nom similaire
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from core.logger import get_logger
from core.study_models import Candidate, ResolvedEntity, EntityRelationType

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Normalisation de texte
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = re.compile(
    r"\b(sarl|sa|sas|sasu|eurl|snc|sci|sca|scop|llc|ltd|inc|corp|gmbh|bv|nv|plc|ag|oy|ab|as|spa|srl|sl|ou|aps)\b",
    re.IGNORECASE
)

_NOISE_WORDS = {
    "groupe", "group", "holding", "international", "maroc", "morocco",
    "algerie", "tunisie", "senegal", "afrique", "africa", "est", "ouest",
    "nord", "sud", "centre", "regional", "national", "global",
}


def normalize_name(name: str) -> str:
    """
    Normalise un nom d'entreprise pour comparaison :
    1. Lowercase
    2. Suppression des accents
    3. Suppression des suffixes légaux
    4. Suppression des mots parasites
    5. Nettoyage des espaces
    """
    if not name:
        return ""
    # Lowercase + déaccentation
    name = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    # Supprimer les caractères spéciaux (garder alphanumérique et espace)
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    # Supprimer les suffixes légaux
    name = _LEGAL_SUFFIXES.sub("", name)
    # Supprimer les mots parasites
    tokens = name.split()
    tokens = [t for t in tokens if t not in _NOISE_WORDS and len(t) > 1]
    return " ".join(tokens).strip()


def extract_domain(url: str) -> str:
    """Extrait le domaine sans www ni TLD."""
    try:
        netloc = urlsplit(url).netloc.lower().replace("www.", "")
        # Garder seulement le domaine principal
        parts = netloc.split(".")
        if len(parts) >= 2:
            return parts[-2]  # ex: "delassus" depuis "delassus.ma"
        return parts[0]
    except Exception:
        return ""


def _levenshtein(s1: str, s2: str) -> int:
    """Distance de Levenshtein simple."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            ins = prev[j + 1] + 1
            del_ = curr[j] + 1
            sub = prev[j] + (c1 != c2)
            curr.append(min(ins, del_, sub))
        prev = curr
    return prev[-1]


def name_similarity(n1: str, n2: str) -> float:
    """
    Similarité 0-1 entre deux noms normalisés.
    Combine : tokens communs + distance d'édition.
    """
    if not n1 or not n2:
        return 0.0
    # Similarité par tokens
    t1 = set(n1.split())
    t2 = set(n2.split())
    if not t1 or not t2:
        return 0.0
    jaccard = len(t1 & t2) / len(t1 | t2)
    # Similarité par édition sur la version concaténée
    max_len = max(len(n1), len(n2))
    if max_len == 0:
        return 1.0
    edit_sim = 1.0 - _levenshtein(n1, n2) / max_len
    return round(0.6 * jaccard + 0.4 * edit_sim, 3)


# ---------------------------------------------------------------------------
# Fingerprint d'entité
# ---------------------------------------------------------------------------

def entity_fingerprint(name: str, domain: str = "", country: str = "") -> str:
    """
    Construit un identifiant unique basé sur :
    - nom normalisé (sans suffixes légaux, sans bruit)
    - domaine (si disponible)
    - pays (optionnel)
    """
    parts = [normalize_name(name)]
    if domain:
        parts.append(domain.lower().strip())
    if country:
        parts.append(country.lower().strip()[:2])
    return "_".join(parts)


# ---------------------------------------------------------------------------
# EntityResolver
# ---------------------------------------------------------------------------

class EntityResolver:
    """
    Résout et déduplique des candidats en entités canoniques.

    Seuils (configurables) :
    - merge_threshold : similarité min pour fusionner (défaut 0.80)
    - domain_match_merge : si même domaine, on fusionne immédiatement
    """

    def __init__(
        self,
        merge_threshold: float = 0.80,
        domain_match_merge: bool = True,
    ):
        self.merge_threshold     = merge_threshold
        self.domain_match_merge  = domain_match_merge
        self._entities: dict[str, ResolvedEntity] = {}  # fingerprint → entity

    def _find_existing(
        self, name: str, domain: str = ""
    ) -> ResolvedEntity | None:
        """Cherche une entité existante qui correspond au candidat."""
        norm = normalize_name(name)

        # 1. Match exact sur domaine (si domaine connu)
        if domain and self.domain_match_merge:
            for fp, entity in self._entities.items():
                if entity.domain and entity.domain == domain:
                    logger.debug(f"Domain match: '{name}' → '{entity.canonical_name}'")
                    return entity

        # 2. Match par similarité de nom normalisé
        for fp, entity in self._entities.items():
            entity_norm = normalize_name(entity.canonical_name)
            sim = name_similarity(norm, entity_norm)
            if sim >= self.merge_threshold:
                logger.info(
                    f"Name match ({sim:.2f}): '{name}' -> '{entity.canonical_name}'"
                )
                return entity

        return None

    def resolve(self, candidate: Candidate) -> ResolvedEntity:
        """
        Résout un candidat :
        - Si une entité existante correspond → enrichit et retourne l'existante
        - Sinon → crée une nouvelle entité
        """
        domain = extract_domain(candidate.source_url) if candidate.source_url else candidate.domain
        existing = self._find_existing(candidate.name, domain)

        if existing:
            # Enrichir l'entité existante
            if candidate.candidate_id not in existing.candidate_ids:
                existing.candidate_ids.append(candidate.candidate_id)
            if candidate.source_url and candidate.source_url not in existing.source_urls:
                existing.source_urls.append(candidate.source_url)
            for alias in candidate.aliases:
                if alias not in existing.aliases:
                    existing.aliases.append(alias)
            # Améliorer le nom si le nouveau est plus court / plus propre
            if len(candidate.name) < len(existing.canonical_name):
                existing.aliases.append(existing.canonical_name)
                existing.canonical_name = candidate.name
            candidate.resolved = True
            candidate.resolved_to = existing.entity_id
            logger.info(f"Resolu : '{candidate.name}' -> entite existante '{existing.canonical_name}'")
            return existing

        # Créer une nouvelle entité
        entity = ResolvedEntity(
            canonical_name = candidate.name,
            normalized_name= normalize_name(candidate.name),
            domain         = domain,
            country        = candidate.country,
            aliases        = list(candidate.aliases),
            relation_type  = candidate.relation_type,
            source_urls    = [candidate.source_url] if candidate.source_url else [],
            candidate_ids  = [candidate.candidate_id],
        )
        fp = entity_fingerprint(entity.canonical_name, entity.domain, entity.country)
        self._entities[fp] = entity
        candidate.resolved = True
        candidate.resolved_to = entity.entity_id
        logger.info(f"Nouvelle entité : '{entity.canonical_name}' (fp={fp})")
        return entity

    def resolve_all(self, candidates: list[Candidate]) -> list[ResolvedEntity]:
        """Résout une liste de candidats et retourne les entités uniques."""
        for c in candidates:
            self.resolve(c)
        return list(self._entities.values())

    def merge_entity(
        self,
        entity: ResolvedEntity,
        update: dict,
    ) -> None:
        """Enrichit une entité avec de nouvelles données (ne remplace pas les valeurs existantes)."""
        for key, value in update.items():
            if not hasattr(entity, key):
                continue
            current = getattr(entity, key)
            if isinstance(current, list) and isinstance(value, list):
                for item in value:
                    if item and item not in current:
                        current.append(item)
            elif isinstance(current, str) and not current and value:
                setattr(entity, key, value)
            elif isinstance(current, float) and current == 0.0 and value:
                setattr(entity, key, value)

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    def get_all(self) -> list[ResolvedEntity]:
        return list(self._entities.values())
