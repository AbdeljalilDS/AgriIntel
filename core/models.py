import unicodedata
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

VALEURS_VIDES = {"", "null", "none", "n/a", "na", "non précisé", "non precise", "-"}

def _est_valeur_vide(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in VALEURS_VIDES)

def _aplatir_en_texte(valeur) -> str | None:
    if _est_valeur_vide(valeur):
        return None
    if isinstance(valeur, str):
        return valeur.strip()
    if isinstance(valeur, dict):
        return ", ".join(f"{k}: {v}" for k, v in valeur.items() if not _est_valeur_vide(v))
    if isinstance(valeur, list):
        textes = [_aplatir_en_texte(v) for v in valeur]
        textes = [t for t in textes if t]
        return ", ".join(textes) if textes else None
    return str(valeur)

def _aplatir_liste_en_textes(valeur) -> list[str]:
    if valeur is None:
        return []
    if not isinstance(valeur, list):
        valeur = [valeur]
    resultat = [_aplatir_en_texte(v) for v in valeur]
    return [t for t in resultat if t]

def _nettoyer_score(valeur) -> float | None:
    if _est_valeur_vide(valeur):
        return None
    try:
        score = float(valeur)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))

class DonneeSourcee(BaseModel):
    valeur: str
    source_url: str = ""
    date_collecte: datetime | None = None
    confiance: Optional[float] = None

    @field_validator("valeur", mode="before")
    @classmethod
    def _valider_valeur(cls, v):
        texte = _aplatir_en_texte(v)
        if not texte:
            raise ValueError("valeur vide ou invalide")
        return texte

    @field_validator("confiance", mode="before")
    @classmethod
    def _valider_confiance(cls, v):
        return _nettoyer_score(v)


def valeur_affichage(valeur) -> str:
    """Retourne une valeur lisible pour les tableaux et rapports."""
    if isinstance(valeur, DonneeSourcee):
        return valeur.valeur
    if isinstance(valeur, dict) and "valeur" in valeur:
        return str(valeur["valeur"])
    return str(valeur)


class EntiteAnalysee(BaseModel):
    nom: str
    secteur: Optional[str] = None
    description: Optional[str] = None
    site_web: Optional[str] = None
    annee_creation: Optional[str] = None
    siege_social: Optional[str] = None
    effectif: Optional[str] = None
    chiffre_affaires: Optional[str] = None

    produits_services: list[str] = Field(default_factory=list)
    prix_indicatif: Optional[str] = None
    positionnement: Optional[str] = None

    technologies: list[DonneeSourcee] = Field(default_factory=list)
    competences: list[DonneeSourcee] = Field(default_factory=list)
    investissements: list[DonneeSourcee] = Field(default_factory=list)
    innovations: list[DonneeSourcee] = Field(default_factory=list)
    innovations_recentes: list[DonneeSourcee] = Field(default_factory=list)

    pays_export: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    partenaires: list[str] = Field(default_factory=list)

    presence_digitale: Optional[str] = None
    reseaux_sociaux: list[str] = Field(default_factory=list)

    forces: list[str] = Field(default_factory=list)
    faiblesses: list[str] = Field(default_factory=list)
    opportunites: list[str] = Field(default_factory=list)
    menaces: list[str] = Field(default_factory=list)
    marches_cibles: list[str] = Field(default_factory=list)

    fondateurs: list[str] = Field(default_factory=list)
    annee_fondation: Optional[str] = None
    stade_financement: Optional[str] = None
    financement_leve: Optional[str] = None
    investisseurs: list[str] = Field(default_factory=list)
    incubateurs: list[str] = Field(default_factory=list)

    source_url: str
    score_pertinence: Optional[float] = None
    date_collecte: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("nom", mode="before")
    @classmethod
    def _valider_nom(cls, v):
        if isinstance(v, list):
            v = v[0] if v else None
        texte = _aplatir_en_texte(v)
        if not texte:
            raise ValueError("nom vide ou invalide")
        return texte

    @field_validator(
        "secteur", "description", "site_web", "annee_creation", "siege_social",
        "effectif", "chiffre_affaires", "prix_indicatif", "positionnement",
        "presence_digitale", "annee_fondation", "stade_financement", "financement_leve",
        mode="before",
    )
    @classmethod
    def _valider_texte(cls, v):
        return _aplatir_en_texte(v)

    @field_validator(
        "produits_services", "pays_export",
        "certifications", "partenaires", "reseaux_sociaux", "forces", "faiblesses",
        "opportunites", "menaces", "marches_cibles",
        "fondateurs", "investisseurs", "incubateurs",
        mode="before",
    )
    @classmethod
    def _valider_liste_texte(cls, v):
        return _aplatir_liste_en_textes(v)

    @field_validator("technologies", "competences", "investissements", "innovations", "innovations_recentes", mode="before")
    @classmethod
    def _valider_preuves(cls, v):
        if v is None:
            return []
        valeurs = v if isinstance(v, list) else [v]
        return [{"valeur": item} if not isinstance(item, dict) else item for item in valeurs if not _est_valeur_vide(item)]

    @field_validator("score_pertinence", mode="before")
    @classmethod
    def _valider_score(cls, v):
        return _nettoyer_score(v)

    @model_validator(mode="after")
    def _completer_preuves(self):
        for champ in ("technologies", "competences", "investissements", "innovations", "innovations_recentes"):
            for preuve in getattr(self, champ):
                if not preuve.source_url:
                    preuve.source_url = self.source_url
                if preuve.date_collecte is None:
                    preuve.date_collecte = self.date_collecte
        return self

    def cle_normalisee(self) -> str:
        nom_ascii = unicodedata.normalize("NFKD", self.nom).encode("ascii", "ignore").decode()
        return nom_ascii.strip().lower()