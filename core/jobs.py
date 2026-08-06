"""Persistance des jobs d'étude — survit aux redémarrages de l'API."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import settings
from core.logger import get_logger

logger = get_logger(__name__)


def _connexion() -> sqlite3.Connection:
    chemin = Path(settings.jobs_db)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(chemin), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            type_agent TEXT NOT NULL,
            cible TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'standard',
            statut TEXT NOT NULL,
            etape TEXT,
            resultat_json TEXT,
            erreur TEXT,
            date_creation TEXT NOT NULL,
            date_maj TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_statut ON jobs(statut)")
    conn.commit()
    return conn


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Stockage SQLite des jobs — remplace le dict en mémoire."""

    def creer(self, type_agent: str, cible: str, mode: str = "standard") -> str:
        job_id = str(uuid.uuid4())
        now = _maintenant()
        conn = _connexion()
        conn.execute(
            """INSERT INTO jobs (job_id, type_agent, cible, mode, statut, etape, date_creation, date_maj)
               VALUES (?, ?, ?, ?, 'en_cours', 'Initialisation...', ?, ?)""",
            (job_id, type_agent, cible, mode, now, now),
        )
        conn.commit()
        conn.close()
        logger.info(f"Job créé : {job_id} ({type_agent}, {cible})")
        return job_id

    def mettre_a_jour(
        self,
        job_id: str,
        statut: str | None = None,
        etape: str | None = None,
        resultat: dict | None = None,
        erreur: str | None = None,
    ) -> None:
        champs = ["date_maj = ?"]
        valeurs: list = [_maintenant()]
        if statut is not None:
            champs.append("statut = ?")
            valeurs.append(statut)
        if etape is not None:
            champs.append("etape = ?")
            valeurs.append(etape)
        if resultat is not None:
            champs.append("resultat_json = ?")
            valeurs.append(json.dumps(resultat, ensure_ascii=False))
        if erreur is not None:
            champs.append("erreur = ?")
            valeurs.append(erreur)
        valeurs.append(job_id)
        conn = _connexion()
        conn.execute(f"UPDATE jobs SET {', '.join(champs)} WHERE job_id = ?", valeurs)
        conn.commit()
        conn.close()

    def lire(self, job_id: str) -> Optional[dict]:
        conn = _connexion()
        ligne = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        conn.close()
        if not ligne:
            return None
        resultat = None
        if ligne["resultat_json"]:
            try:
                resultat = json.loads(ligne["resultat_json"])
            except json.JSONDecodeError:
                resultat = None
        return {
            "job_id": ligne["job_id"],
            "statut": ligne["statut"],
            "etape": ligne["etape"],
            "resultat": resultat,
            "erreur": ligne["erreur"],
            "type_agent": ligne["type_agent"],
            "cible": ligne["cible"],
            "mode": ligne["mode"],
            "date_creation": ligne["date_creation"],
            "date_maj": ligne["date_maj"],
        }

    def existe(self, job_id: str) -> bool:
        return self.lire(job_id) is not None

    def lister_en_cours(self) -> list[dict]:
        conn = _connexion()
        lignes = conn.execute(
            "SELECT job_id, type_agent, cible, statut, etape, date_creation FROM jobs WHERE statut = 'en_cours'"
        ).fetchall()
        conn.close()
        return [dict(ligne) for ligne in lignes]

    def lister_recents(self, limite: int = 20) -> list[dict]:
        conn = _connexion()
        lignes = conn.execute(
            """SELECT job_id, type_agent, cible, mode, statut, etape, erreur, date_creation, date_maj
               FROM jobs ORDER BY date_maj DESC LIMIT ?""",
            (limite,),
        ).fetchall()
        conn.close()
        return [dict(ligne) for ligne in lignes]

    def reprendre_jobs_interrompus(self) -> list[str]:
        """Marque les jobs 'en_cours' comme interrompus au redémarrage."""
        conn = _connexion()
        lignes = conn.execute("SELECT job_id FROM jobs WHERE statut = 'en_cours'").fetchall()
        ids = [ligne["job_id"] for ligne in lignes]
        if ids:
            now = _maintenant()
            conn.execute(
                """UPDATE jobs SET statut = 'interrompu', erreur = 'API redémarrée pendant l''exécution',
                   etape = 'Interrompu — relancez l''étude', date_maj = ? WHERE statut = 'en_cours'""",
                (now,),
            )
            conn.commit()
            logger.warning(f"{len(ids)} job(s) interrompu(s) au redémarrage")
        conn.close()
        return ids


job_store = JobStore()
