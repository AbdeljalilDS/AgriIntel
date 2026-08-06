"""Mémoire long terme — SQLite + similarité cosinus en numpy.

Rôle : le RAG du projet. Avant de chercher sur le web, l'agent peut
interroger cette mémoire pour voir s'il connaît déjà une information
(même formulée différemment — "Oracle" retrouve "Oracle Corporation"
grâce aux embeddings). Persiste entre les exécutions (fichier .sqlite3
sur le disque), contrairement à la mémoire de conversation qui elle est
perdue à chaque redémarrage.

Choix technique : pas de Qdrant/FAISS. À l'échelle de ce projet (quelques
centaines d'entités, pas de millions), SQLite + numpy fait exactement le
même travail sans service supplémentaire à faire tourner sur une machine
à 8 Go de RAM.
"""
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

import numpy as np

from config.settings import settings
from core.logger import get_logger

logger = get_logger(__name__)


def _connexion() -> sqlite3.Connection:
    Path(settings.memoire_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.memoire_db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entites (
            cle TEXT PRIMARY KEY,
            nom TEXT NOT NULL,
            data_json TEXT NOT NULL,
            embedding BLOB,
            date_maj TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preuves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cle_entite TEXT NOT NULL,
            type_fait TEXT NOT NULL,
            texte TEXT NOT NULL,
            source_url TEXT NOT NULL,
            date_collecte TEXT,
            confiance REAL,
            embedding BLOB
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_preuves_type ON preuves(type_fait)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_preuves_source ON preuves(source_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_preuves_date ON preuves(date_collecte)")
    return conn


def enregistrer_preuves(cle_entite: str, preuves: list[dict]) -> None:
    """Indexe des faits atomiques avec leurs preuves et embeddings."""
    if not preuves:
        return
    conn = _connexion()
    conn.execute("DELETE FROM preuves WHERE cle_entite = ?", (cle_entite,))
    for preuve in preuves:
        embedding = preuve.get("embedding")
        emb_bytes = np.array(embedding, dtype=np.float32).tobytes() if embedding else None
        conn.execute(
            """INSERT INTO preuves
            (cle_entite, type_fait, texte, source_url, date_collecte, confiance, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cle_entite, preuve["type_fait"], preuve["texte"], preuve["source_url"], preuve.get("date_collecte"), preuve.get("confiance"), emb_bytes),
        )
    conn.commit()
    conn.close()


def rechercher_preuves(requete: str, embedding_requete: list[float] | None, top_k: int = 8, seuil: float = 0.12) -> list[dict]:
    """Recherche des faits atomiques, plus precisement qu'une fiche entite."""
    conn = _connexion()
    lignes = conn.execute("SELECT type_fait, texte, source_url, date_collecte, confiance, embedding FROM preuves").fetchall()
    conn.close()
    termes = _normaliser_termes(requete)
    vecteur_requete = np.array(embedding_requete, dtype=np.float32) if embedding_requete else None
    resultats = []
    deja_vus = set()
    for type_fait, texte, source_url, date_collecte, confiance, emb_bytes in lignes:
        lexical = len(termes & _normaliser_termes(f"{type_fait} {texte}")) / max(len(termes), 1)
        vectoriel = 0.0
        if vecteur_requete is not None and emb_bytes:
            vecteur = np.frombuffer(emb_bytes, dtype=np.float32)
            if vecteur.size == vecteur_requete.size:
                norme = np.linalg.norm(vecteur) * np.linalg.norm(vecteur_requete)
                vectoriel = float(np.dot(vecteur, vecteur_requete) / norme) if norme else 0.0
        score = 0.75 * vectoriel + 0.25 * lexical
        cle = (texte.casefold(), source_url)
        if score >= seuil and cle not in deja_vus:
            deja_vus.add(cle)
            resultats.append({"type": type_fait, "texte": texte, "source": source_url, "date": date_collecte, "confiance": confiance, "score": round(score, 4)})
    resultats.sort(key=lambda item: (item["score"], item["confiance"] or 0), reverse=True)
    selection = []
    sources = {}
    for resultat in resultats:
        if sources.get(resultat["source"], 0) >= 2:
            continue
        selection.append(resultat)
        sources[resultat["source"]] = sources.get(resultat["source"], 0) + 1
        if len(selection) >= top_k:
            break
    return selection


def enregistrer(cle: str, nom: str, data_json: str, embedding: list[float] | None) -> None:
    """Ajoute ou met à jour une entité en mémoire persistante."""
    conn = _connexion()
    emb_bytes = np.array(embedding, dtype=np.float32).tobytes() if embedding else None
    conn.execute(
        """
        INSERT INTO entites (cle, nom, data_json, embedding, date_maj)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(cle) DO UPDATE SET
            data_json = excluded.data_json,
            embedding = excluded.embedding,
            date_maj = excluded.date_maj
        """,
        (cle, nom, data_json, emb_bytes),
    )
    conn.commit()
    conn.close()
    logger.info(f"Mémoire mise à jour : {nom}")


def lister_tout() -> list[dict]:
    conn = _connexion()
    lignes = conn.execute("SELECT data_json FROM entites").fetchall()
    conn.close()
    return [json.loads(l[0]) for l in lignes]


def rechercher_similaire(embedding_requete: list[float], top_k: int = 5) -> list[dict]:
    """RAG : retrouve les entités les plus proches sémantiquement d'une
    requête, même sans correspondance exacte de mots."""
    if not embedding_requete:
        return []
    conn = _connexion()
    lignes = conn.execute("SELECT nom, data_json, embedding FROM entites WHERE embedding IS NOT NULL").fetchall()
    conn.close()
    if not lignes:
        return []

    vecteur_requete = np.array(embedding_requete, dtype=np.float32)
    norme_requete = np.linalg.norm(vecteur_requete)
    resultats = []
    for nom, data_json, emb_bytes in lignes:
        vecteur = np.frombuffer(emb_bytes, dtype=np.float32)
        if vecteur.size != vecteur_requete.size:
            logger.warning(f"Embedding ignore pour {nom}: dimension incompatible")
            continue
        norme = np.linalg.norm(vecteur)
        if norme_requete == 0 or norme == 0:
            similarite = 0.0
        else:
            similarite = float(np.dot(vecteur_requete, vecteur) / (norme_requete * norme))
        resultats.append((similarite, data_json, None))

    resultats.sort(key=lambda x: x[0], reverse=True)
    return [_ajouter_score(json.loads(d), score, date) for score, d, date in resultats[:top_k]]


def _normaliser_termes(texte: str) -> set[str]:
    texte = unicodedata.normalize("NFKD", texte.lower()).encode("ascii", "ignore").decode()
    return {mot for mot in re.findall(r"[a-z0-9]+", texte) if len(mot) > 3}


def _ajouter_score(data: dict, score: float, date: str | None) -> dict:
    data = dict(data)
    data["_rag_score"] = round(float(score), 4)
    if date:
        data["_rag_date"] = date
    return data


def rechercher_hybride(requete: str, embedding_requete: list[float] | None, top_k: int = 5, seuil: float = 0.12) -> list[dict]:
    """Combine similarite vectorielle et correspondance lexicale explicable."""
    conn = _connexion()
    lignes = conn.execute("SELECT nom, data_json, embedding, date_maj FROM entites").fetchall()
    conn.close()
    termes_requete = _normaliser_termes(requete)
    vecteur_requete = np.array(embedding_requete, dtype=np.float32) if embedding_requete else None
    resultats = []
    for nom, data_json, emb_bytes, date_maj in lignes:
        data = json.loads(data_json)
        termes_document = _normaliser_termes(f"{nom} {data_json}")
        lexical = len(termes_requete & termes_document) / max(len(termes_requete), 1)
        vectoriel = 0.0
        if vecteur_requete is not None and emb_bytes:
            vecteur = np.frombuffer(emb_bytes, dtype=np.float32)
            if vecteur.size == vecteur_requete.size:
                norme = np.linalg.norm(vecteur) * np.linalg.norm(vecteur_requete)
                vectoriel = float(np.dot(vecteur, vecteur_requete) / norme) if norme else 0.0
        score = 0.75 * vectoriel + 0.25 * lexical
        if score >= seuil:
            resultats.append((score, data, date_maj))
    resultats.sort(key=lambda item: item[0], reverse=True)
    return [_ajouter_score(data, score, date) for score, data, date in resultats[:top_k]]


def rechercher_par_mot_cle(mot_cle: str, top_k: int = 5) -> list[dict]:
    """Repli automatique si le modèle d'embedding n'est pas disponible —
    moins précis (correspondance exacte de texte) mais ne casse rien."""
    conn = _connexion()
    lignes = conn.execute(
        "SELECT data_json FROM entites WHERE nom LIKE ? OR data_json LIKE ? LIMIT ?",
        (f"%{mot_cle}%", f"%{mot_cle}%", top_k),
    ).fetchall()
    conn.close()
    return [json.loads(l[0]) for l in lignes]
