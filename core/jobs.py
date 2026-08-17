"""Persistance des jobs d'étude — version asynchrone avec aiosqlite.

CORRECTIF : `_connexion()` faisait `await aiosqlite.connect(...)` puis
chaque appelant refaisait `async with await self._connexion() as conn:`.
Le `await` interne démarre déjà le thread aiosqlite ; le `async with`
qui suit rappelle `__aenter__` -> `await self` -> retente de démarrer
le MÊME thread -> `RuntimeError: threads can only be started once`.

Correction : `_connexion()` n'est plus awaitée elle-même — elle retourne
directement l'objet `aiosqlite.connect(...)` NON résolu, exactement comme
si tu écrivais `async with aiosqlite.connect(chemin) as db:` en direct.
Un seul point d'awaiting, celui du `async with`.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from config.settings import settings
from core.logger import get_logger

logger = get_logger(__name__)


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Stockage SQLite des jobs en asynchrone."""

    async def _init_db(self):
        chemin = Path(settings.jobs_db)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(chemin)) as db:
            await db.execute(
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
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_statut ON jobs(statut)")
            await db.commit()

    def _connexion(self):
        """NE PAS mettre `async def` ici, et NE PAS awaiter à l'intérieur.
        On retourne l'objet connectable brut : c'est `async with` qui doit
        faire le SEUL await de tout le cycle de vie de la connexion."""
        chemin = Path(settings.jobs_db)
        return aiosqlite.connect(str(chemin))

    async def creer(self, type_agent: str, cible: str, mode: str = "standard") -> str:
        await self._init_db()
        job_id = str(uuid.uuid4())
        now = _maintenant()
        async with self._connexion() as conn:
            await conn.execute(
                """INSERT INTO jobs (job_id, type_agent, cible, mode, statut, etape, date_creation, date_maj)
                   VALUES (?, ?, ?, ?, 'en_cours', 'Initialisation...', ?, ?)""",
                (job_id, type_agent, cible, mode, now, now),
            )
            await conn.commit()
        logger.info(f"Job créé : {job_id} ({type_agent}, {cible})")
        return job_id

    async def mettre_a_jour(
        self,
        job_id: str,
        statut: str | None = None,
        etape: str | None = None,
        resultat: dict | None = None,
        erreur: str | None = None,
    ) -> None:
        await self._init_db()
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

        async with self._connexion() as conn:
            await conn.execute(f"UPDATE jobs SET {', '.join(champs)} WHERE job_id = ?", valeurs)
            await conn.commit()

    async def lire(self, job_id: str) -> Optional[dict]:
        await self._init_db()
        async with self._connexion() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            ligne = await cursor.fetchone()

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

    async def existe(self, job_id: str) -> bool:
        return await self.lire(job_id) is not None

    async def lister_en_cours(self) -> list[dict]:
        await self._init_db()
        async with self._connexion() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT job_id, type_agent, cible, statut, etape, date_creation FROM jobs WHERE statut = 'en_cours'"
            )
            lignes = await cursor.fetchall()
        return [dict(ligne) for ligne in lignes]

    async def lister_recents(self, limite: int = 20) -> list[dict]:
        await self._init_db()
        async with self._connexion() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """SELECT job_id, type_agent, cible, mode, statut, etape, erreur, date_creation, date_maj
                   FROM jobs ORDER BY date_maj DESC LIMIT ?""",
                (limite,),
            )
            lignes = await cursor.fetchall()
        return [dict(ligne) for ligne in lignes]

    async def reprendre_jobs_interrompus(self) -> list[str]:
        await self._init_db()
        async with self._connexion() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT job_id FROM jobs WHERE statut = 'en_cours'")
            lignes = await cursor.fetchall()
            ids = [ligne["job_id"] for ligne in lignes]
            if ids:
                now = _maintenant()
                await conn.execute(
                    """UPDATE jobs SET statut = 'interrompu', erreur = 'API redémarrée pendant l''exécution',
                       etape = 'Interrompu — relancez l''étude', date_maj = ? WHERE statut = 'en_cours'""",
                    (now,),
                )
                await conn.commit()
                logger.warning(f"{len(ids)} job(s) interrompu(s) au redémarrage")
        return ids


job_store = JobStore()
