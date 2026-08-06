"""Caches legers et persistants pour limiter les appels web et LLM."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config.settings import settings


def _connexion() -> sqlite3.Connection:
    chemin = Path(settings.memoire_db)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(chemin))
    conn.execute("CREATE TABLE IF NOT EXISTS cache_pages (url TEXT PRIMARY KEY, texte TEXT NOT NULL, date_maj TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS cache_reponses (cle TEXT PRIMARY KEY, data_json TEXT NOT NULL, date_maj TEXT NOT NULL)")
    return conn


def _expire(date_maj: str, ttl: int) -> bool:
    date = datetime.fromisoformat(date_maj)
    return (datetime.now(timezone.utc) - date).total_seconds() > ttl


def lire_page(url: str) -> str | None:
    conn = _connexion()
    ligne = conn.execute("SELECT texte, date_maj FROM cache_pages WHERE url = ?", (url,)).fetchone()
    conn.close()
    if not ligne or _expire(ligne[1], settings.page_cache_ttl):
        return None
    return ligne[0]


def enregistrer_page(url: str, texte: str) -> None:
    conn = _connexion()
    conn.execute("INSERT OR REPLACE INTO cache_pages(url, texte, date_maj) VALUES (?, ?, ?)", (url, texte, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def cle_reponse(question: str, historique: list, documents: list, nb_entites: int) -> str:
    contenu = json.dumps({"question": question.strip().casefold(), "historique": historique[-3:], "documents": documents, "nb_entites": nb_entites}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(contenu.encode("utf-8")).hexdigest()


def lire_reponse(cle: str) -> dict | None:
    conn = _connexion()
    ligne = conn.execute("SELECT data_json, date_maj FROM cache_reponses WHERE cle = ?", (cle,)).fetchone()
    conn.close()
    if not ligne or _expire(ligne[1], settings.response_cache_ttl):
        return None
    return json.loads(ligne[0])


def enregistrer_reponse(cle: str, data: dict) -> None:
    conn = _connexion()
    conn.execute("INSERT OR REPLACE INTO cache_reponses(cle, data_json, date_maj) VALUES (?, ?, ?)", (cle, json.dumps(data, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
