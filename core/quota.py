"""Garde-fou de quota pour les API externes à plan gratuit limité (Tavily :
1000 requêtes/mois). Rien n'empêchait avant qu'une seule étude un peu
gourmande épuise le quota mensuel d'un coup — ce compteur persiste sur
disque (survit aux redémarrages) et bloque proprement avant le dépassement,
au lieu de laisser Tavily renvoyer des erreurs 429 en pleine étude."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
 
from config.settings import settings
from core.logger import get_logger
 
logger = get_logger(__name__)
_verrou = threading.Lock()
_CHEMIN = Path("data/quota_usage.json")
 
 
def _mois_courant() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")
 
 
def _lire() -> dict:
    if not _CHEMIN.exists():
        return {}
    try:
        return json.loads(_CHEMIN.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
 
 
def _ecrire(donnees: dict) -> None:
    _CHEMIN.parent.mkdir(parents=True, exist_ok=True)
    _CHEMIN.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
 
 
def quota_disponible(service: str, limite: int) -> bool:
    """True si le service peut encore être appelé ce mois-ci."""
    with _verrou:
        donnees = _lire()
        mois = _mois_courant()
        compte = donnees.get(service, {}).get(mois, 0)
        return compte < limite
 
 
def consommer(service: str, limite: int) -> None:
    """Incrémente le compteur du mois courant pour ce service, et prévient
    dès qu'on approche la limite (80%) pour anticiper plutôt que subir."""
    with _verrou:
        donnees = _lire()
        mois = _mois_courant()
        donnees.setdefault(service, {})
        # Nettoie les mois précédents — pas besoin de les garder
        donnees[service] = {mois: donnees[service].get(mois, 0) + 1}
        compte = donnees[service][mois]
        _ecrire(donnees)
    if compte == int(limite * 0.8):
        logger.warning(f"Quota {service} : {compte}/{limite} utilisés ce mois-ci (80%) — pense à surveiller.")
    elif compte >= limite:
        logger.warning(f"Quota {service} : limite mensuelle atteinte ({compte}/{limite}).")
 
 
def compte_actuel(service: str) -> int:
    with _verrou:
        return _lire().get(service, {}).get(_mois_courant(), 0)