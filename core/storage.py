import json
from abc import ABC, abstractmethod
from pathlib import Path

from config.settings import settings
from core.exceptions import StorageError
from core.logger import get_logger
from core.models import EntiteAnalysee

logger = get_logger(__name__)

class Storage(ABC):
    @abstractmethod
    def save(self, entites: list[EntiteAnalysee], nom_fichier: str) -> str:
        ...

class JSONStorage(Storage):
    def __init__(self, dossier: str | None = None):
        self.dossier = Path(dossier or settings.output_dir)
        self.dossier.mkdir(parents=True, exist_ok=True)

    def save(self, entites: list[EntiteAnalysee], nom_fichier: str) -> str:
        chemin = self.dossier / f"{nom_fichier}.json"
        try:
            data = [json.loads(entite.model_dump_json()) for entite in entites]
            chemin.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Impossible d'écrire {chemin}") from exc
        logger.info(f"{len(entites)} entités sauvegardées dans {chemin}")
        return str(chemin)
