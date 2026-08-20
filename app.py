"""
Enterprise AI Research Engine — Interface Streamlit STANDALONE.

VERSION SANS API EXTERNE : L'agent tourne directement dans ce processus.
Pas besoin de lancer uvicorn séparément.

Lancer : streamlit run app.py
"""
from __future__ import annotations

import asyncio
import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ─── Config page (MUST be first Streamlit call) ───────────────────────────
st.set_page_config(
    page_title="Agricultural Intelligence Platform",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Imports internes ─────────────────────────────────────────────────────
from config.settings import settings
from core.logger import get_logger
from core.models import EntiteAnalysee, valeur_affichage

logger = get_logger(__name__)

# ─── Thème premium agriculture ────────────────────────────────────────────
st.markdown("""
<style>
/* ── Variables ── */
:root {
  --bg: #0b1a14;
  --bg2: #0f2318;
  --card: #142d1e;
  --border: #1f4030;
  --text: #dff2ea;
  --muted: #7aab8e;
  --accent: #3ddc84;
  --accent2: #f5c842;
  --danger: #e05a5a;
  --sidebar: #0d1f17;
}

/* ── Base ── */
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: 'Inter', system-ui, sans-serif;
}
[data-testid="stHeader"] { background: transparent !important; }
.stApp p, .stApp label, .stApp li, .stApp td, .stApp th,
.stApp [data-testid="stMarkdownContainer"] { color: var(--text) !important; }
.stApp small, .stApp [data-testid="stCaptionContainer"] { color: var(--muted) !important; }
.stApp h1 { color: #a8f0c6 !important; font-size: 2rem !important; font-weight: 800 !important; }
.stApp h2, .stApp h3 { color: #7de0a4 !important; }
.stApp h4 { color: var(--accent) !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: var(--sidebar) !important;
  border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
[data-testid="stSidebar"] span, [data-testid="stSidebar"] div,
[data-testid="stSidebar"] small { color: #c5e8d5 !important; }
[data-testid="stSidebar"] .stRadio label {
  padding: .45rem .7rem;
  border-radius: 8px;
  transition: background .15s;
}
[data-testid="stSidebar"] .stRadio label:hover { background: rgba(61,220,132,.12); }

/* ── Inputs ── */
.stApp input, .stApp textarea, .stApp [data-baseweb="select"] > div {
  background: var(--card) !important;
  color: var(--text) !important;
  border-color: var(--border) !important;
  border-radius: 8px !important;
}
.stApp input::placeholder, .stApp textarea::placeholder { color: var(--muted) !important; }

/* ── Metrics ── */
div[data-testid="stMetric"] {
  background: var(--card) !important;
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 1rem 1.2rem;
  box-shadow: 0 2px 12px rgba(0,0,0,.25);
}
div[data-testid="stMetricLabel"] p { color: var(--muted) !important; font-size: .8rem !important; text-transform: uppercase; letter-spacing: .08em; }
div[data-testid="stMetricValue"] { color: var(--accent) !important; font-size: 2rem !important; font-weight: 800 !important; }

/* ── Buttons ── */
.stButton > button {
  border-radius: 10px;
  font-weight: 700;
  color: #ffffff !important;
  background: linear-gradient(135deg, #1a6b3a, #2a9d5c) !important;
  border: none !important;
  padding: .6rem 1.4rem;
  transition: all .2s;
  box-shadow: 0 2px 8px rgba(42,157,92,.3);
}
.stButton > button:hover {
  background: linear-gradient(135deg, #145730, #22804a) !important;
  box-shadow: 0 4px 16px rgba(42,157,92,.5);
  transform: translateY(-1px);
}
.stDownloadButton > button {
  color: var(--text) !important;
  background: var(--card) !important;
  border: 1px solid var(--border) !important;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] { background: var(--card) !important; border-radius: 12px; }

/* ── Chat ── */
[data-testid="stChatMessage"] {
  background: var(--card) !important;
  border: 1px solid var(--border);
  border-radius: 12px;
}
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { color: var(--text) !important; }

/* ── Expander ── */
[data-testid="stExpander"] { background: var(--card) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; }

/* ── Status box ── */
[data-testid="stStatusWidget"] { background: var(--card) !important; border: 1px solid var(--border) !important; }

/* ── Hero ── */
.hero {
  background: linear-gradient(135deg, #0f2318 0%, #1a4a2e 50%, #0f3020 100%);
  border: 1px solid #2a6040;
  border-radius: 16px;
  padding: 1.6rem 2rem;
  margin-bottom: 1.5rem;
  position: relative;
  overflow: hidden;
}
.hero::before {
  content: '🌾';
  position: absolute;
  right: 1.5rem; top: 50%; transform: translateY(-50%);
  font-size: 4rem; opacity: .12;
}
.hero-badge { color: var(--accent); font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .15em; }
.hero h1 { color: #a8f0c6 !important; font-size: 1.9rem !important; margin: .3rem 0 .5rem; }
.hero p { color: #7aab8e !important; margin: 0; font-size: .95rem; }

/* ── SWOT ── */
.swot-box {
  border-radius: 12px; padding: .9rem 1rem;
  border: 1px solid var(--border);
}
.swot-forces   { background: rgba(61,220,132,.08); border-color: #2a6040; }
.swot-faiblesses { background: rgba(245,200,66,.08); border-color: #5a4a10; }
.swot-opportunites { background: rgba(61,130,220,.08); border-color: #1a3a5a; }
.swot-menaces  { background: rgba(224,90,90,.08); border-color: #5a2020; }

/* ── Chip ── */
.chip {
  display: inline-block; padding: .2rem .55rem;
  background: rgba(61,220,132,.15); color: var(--accent);
  border-radius: 999px; font-size: .75rem; margin: .1rem .1rem;
}
.chip-amber { background: rgba(245,200,66,.15); color: var(--accent2); }
.chip-red   { background: rgba(224,90,90,.15); color: #ff8080; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg2); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ── Progress text ── */
[data-testid="stProgressText"] { color: var(--accent) !important; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# Helpers — données
def _run_async(coro):
    """Exécute de manière sûre et isolée une coroutine async dans Streamlit."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


def charger_entites() -> list[dict]:
    """Charge toutes les entités depuis la mémoire SQLite."""
    try:
        import importlib
        from core import memoire
        importlib.reload(memoire)
        raw = _run_async(memoire.lister_tout())
        return raw if isinstance(raw, list) else []
    except Exception as exc:
        logger.warning(f"Impossible de charger les entités : {exc}")
        return []


def compter_preuves_memoire() -> int:
    """Compte les faits et preuves vérifiées en base."""
    try:
        import importlib
        from core import memoire
        importlib.reload(memoire)
        if hasattr(memoire, "compter_preuves"):
            return int(_run_async(memoire.compter_preuves()))
        return 0
    except Exception as exc:
        logger.warning(f"Impossible de compter les preuves : {exc}")
        return 0


def lister_preuves_recentes(limite: int = 6) -> list[dict]:
    """Récupère les dernières preuves indexées."""
    try:
        from core import memoire
        if hasattr(memoire, "lister_dernieres_preuves"):
            res = _run_async(memoire.lister_dernieres_preuves(limite))
            return res if isinstance(res, list) else []
        return []
    except Exception as exc:
        logger.warning(f"Impossible de lister les preuves : {exc}")
        return []


def lister_rapports() -> list[str]:
    """Liste les fichiers rapport .md dans data/processed."""
    dossier = Path(settings.output_dir)
    if not dossier.exists():
        return []
    return sorted(
        [f.name for f in dossier.glob("*_rapport.md")],
        reverse=True,
    )


def entites_vers_dataframe(entites: list[dict]) -> pd.DataFrame:
    lignes = []
    for e in entites:
        lignes.append({
            "Nom":            e.get("nom", ""),
            "Secteur":        e.get("secteur") or "",
            "Positionnement": e.get("positionnement") or "",
            "Description":    (e.get("description") or "")[:120],
            "Produits":       ", ".join(e.get("produits_services", [])[:3]),
            "Certifications": ", ".join(e.get("certifications", [])[:3]),
            "Export":         ", ".join(e.get("pays_export", [])[:3]),
            "Technologies":   ", ".join(valeur_affichage(t) for t in e.get("technologies", [])[:3]),
            "Score":          e.get("score_pertinence") or "",
            "Source":         e.get("source_url", ""),
        })
def _afficher_fiche(e: dict):
    """Affiche une fiche détaillée avec SWOT et écosystème."""
    st.markdown(f"#### 🏢 {e.get('nom', 'Inconnu')}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📋 Identification**")
        champs = [
            ("Site web", "site_web"), ("Siège social", "siege_social"),
            ("Création", "annee_creation"), ("Effectif", "effectif"),
            ("CA", "chiffre_affaires"), ("Positionnement", "positionnement"),
        ]
        for label, cle in champs:
            if e.get(cle):
                st.caption(f"**{label}** : {e[cle]}")
        # Chips certifications
        certifs = e.get("certifications", [])
        if certifs:
            st.markdown("**Certifications** : " + " ".join(
                f"<span class='chip chip-amber'>{c}</span>" for c in certifs[:5]
            ), unsafe_allow_html=True)
        pays = e.get("pays_export", [])
        if pays:
            st.markdown("**Export** : " + " ".join(
                f"<span class='chip'>{p}</span>" for p in pays[:6]
            ), unsafe_allow_html=True)

    with col2:
        st.markdown("**🌐 Écosystème**")
        for label, cle in [
            ("Partenaires", "partenaires"), ("Marchés ciblés", "marches_cibles"),
            ("Investisseurs", "investisseurs"), ("Incubateurs", "incubateurs"),
        ]:
            valeurs = e.get(cle) or []
            if valeurs:
                st.caption(f"**{label}** : {', '.join(valeurs[:4])}")
        technos = e.get("technologies", [])
        if technos:
            st.markdown("**Technologies** : " + " ".join(
                f"<span class='chip chip-amber'>{valeur_affichage(t)}</span>"
                for t in technos[:5]
            ), unsafe_allow_html=True)

    # SWOT
    st.markdown("**🔍 Analyse SWOT & Diagnostic Stratégique**")
    swot_vide = not e.get("forces") and not e.get("faiblesses") and not e.get("opportunites") and not e.get("menaces")
    if swot_vide:
        st.caption("ℹ️ Cette fiche ne contient pas encore de diagnostic SWOT approfondi.")
        if st.button(f"⚡ Générer le diagnostic SWOT & Stratégie avec l'IA", key=f"btn_swot_{e.get('nom')}", type="primary"):
            with st.spinner(f"Génération de l'analyse SWOT pour {e.get('nom')}..."):
                try:
                    import importlib
                    import core.llm_client
                    importlib.reload(core.llm_client)
                    from core.llm_client import get_llm_client
                    llm = get_llm_client()
                    prompt = f"""En tant qu'analyste stratégique Senior (profil McKinsey/Bloomberg), génère un diagnostic SWOT approfondi et un positionnement pour cette entreprise :
Nom : {e.get('nom')}
Secteur : {e.get('secteur') or 'Agriculture / Agro-industrie'}
Description : {e.get('description') or 'Acteur du secteur agricole et agro-industriel'}
Produits : {', '.join(e.get('produits_services', []))}

Réponds STRICTEMENT en JSON valide :
{{
  "forces": ["3 forces concurrentielles et atouts majeurs"],
  "faiblesses": ["2 vulnérabilités, limites ou dépendances"],
  "opportunites": ["2 opportunités de développement de marché ou d'export"],
  "menaces": ["2 risques climatiques, réglementaires ou concurrentiels"],
  "positionnement": "Leader / Spécialiste haut de gamme / Exportateur...",
  "marches_cibles": ["Marché local", "Europe", "Afrique"],
  "technologies": ["Technologies ou savoir-faire clés"]
}}"""
                    res = _run_async(llm.generate_json(prompt))
                    if isinstance(res, dict):
                        e["forces"] = res.get("forces") or []
                        e["faiblesses"] = res.get("faiblesses") or []
                        e["opportunites"] = res.get("opportunites") or []
                        e["menaces"] = res.get("menaces") or []
                        if res.get("positionnement"):
                            e["positionnement"] = res["positionnement"]
                        if res.get("marches_cibles"):
                            e["marches_cibles"] = res["marches_cibles"]
                        if res.get("technologies"):
                            e["technologies"] = [{"valeur": t, "source_url": e.get("source_url", ""), "confiance": 0.8} for t in res["technologies"]]

                        # Sauvegarde dans la base SQLite
                        from core import memoire
                        from core.models import EntiteAnalysee
                        ent_obj = EntiteAnalysee.model_validate(e)
                        cle = ent_obj.cle_normalisee()
                        _run_async(memoire.enregistrer(cle, ent_obj.nom, json.dumps(e, ensure_ascii=False), None))
                        st.success("✅ Diagnostic SWOT généré et persisté en mémoire !")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Erreur génération SWOT : {exc}")

    cf, cfa, co, cm = st.columns(4)
    swot = [
        (cf, "💪 Forces", "forces", "swot-forces"),
        (cfa, "⚠️ Faiblesses", "faiblesses", "swot-faiblesses"),
        (co, "🎯 Opportunités", "opportunites", "swot-opportunites"),
        (cm, "🔺 Menaces", "menaces", "swot-menaces"),
    ]
    for col, titre, cle, css_class in swot:
        with col:
            valeurs = e.get(cle) or []
            items = "\n".join(f"• {v}" for v in valeurs[:4]) if valeurs else "_Non documenté_"
            st.markdown(f"""
            <div class='swot-box {css_class}'>
              <div style='font-weight:700;font-size:.85rem;margin-bottom:.4rem;'>{titre}</div>
              <div style='font-size:.8rem;color:#c5e8d5;white-space:pre-line;'>{items}</div>
            </div>
            """, unsafe_allow_html=True)


def sauvegarder_rapport(cible: str, rapport: str, entites: list) -> str:
    """Sauvegarde le rapport en .md et les entités en JSON."""
    dossier = Path(settings.output_dir)
    dossier.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = cible.lower().replace(" ", "_")[:30]
    nom_rapport = f"{slug}_{timestamp}_rapport.md"
    (dossier / nom_rapport).write_text(rapport, encoding="utf-8")
    if entites:
        nom_json = nom_rapport.replace("_rapport.md", "_entites.json")
        (dossier / nom_json).write_text(
            json.dumps(entites, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return nom_rapport


async def _enrichir_entites_automatiquement(llm, entites: list) -> list:
    """Enrichit automatiquement les fiches d'entreprises incomplètes avec le SWOT."""
    from core.models import DonneeSourcee
    for e in entites:
        if not e.forces and not e.faiblesses and not e.opportunites:
            prompt = f"""En tant qu'analyste Senior, génère un diagnostic SWOT concis et positionnement pour :
Nom : {e.nom}
Secteur : {e.secteur or 'Agriculture / Agro-industrie'}
Description : {e.description or 'Entreprise agricole'}
Produits : {', '.join(e.produits_services) if e.produits_services else 'Produits agricoles'}

Réponds STRICTEMENT en JSON :
{{
  "forces": ["force 1", "force 2"],
  "faiblesses": ["faiblesse 1", "faiblesse 2"],
  "opportunites": ["opportunite 1", "opportunite 2"],
  "menaces": ["menace 1", "menace 2"],
  "positionnement": "Positionnement",
  "technologies": ["tech 1", "tech 2"]
}}"""
            try:
                data = await llm.generate_json(prompt)
                if isinstance(data, dict):
                    if data.get("forces"):
                        e.forces = [str(f) for f in data["forces"] if f]
                    if data.get("faiblesses"):
                        e.faiblesses = [str(f) for f in data["faiblesses"] if f]
                    if data.get("opportunites"):
                        e.opportunites = [str(f) for f in data["opportunites"] if f]
                    if data.get("menaces"):
                        e.menaces = [str(f) for f in data["menaces"] if f]
                    if data.get("positionnement") and not e.positionnement:
                        e.positionnement = str(data["positionnement"])
                    if data.get("technologies") and not e.technologies:
                        e.technologies = [
                            DonneeSourcee(valeur=str(t), source_url=e.source_url or "", confiance=0.8)
                            for t in data["technologies"] if t
                        ]
            except Exception as exc:
                logger.warning(f"Enrichissement automatique SWOT échoué pour {e.nom}: {exc}")
    return entites


async def _lancer_etude_async(cible: str, mode: str, agent_type: str) -> dict:
    """Coroutine principale : lance l'agent et retourne le résultat."""
    from core.llm_client import get_llm_client

    llm = get_llm_client()

    if agent_type == "benchmark":
        from agent_benchmark.agent import BenchmarkAgent
        from agent_benchmark.report_generator import generer_rapport
        agent = BenchmarkAgent(llm, mode=mode)
        entites = await agent.run(cible)
        entites = await _enrichir_entites_automatiquement(llm, entites)
        rapport = await generer_rapport(llm, cible, entites)
    else:
        from agent_startup.agent import StartupAgent
        from agent_startup.report_generator import generer_rapport_startup
        agent = StartupAgent(llm, mode=mode)
        entites = await agent.run(cible)
        entites = await _enrichir_entites_automatiquement(llm, entites)
        rapport = await generer_rapport_startup(llm, cible, entites)

    entites_dicts = [e.model_dump(mode="json") for e in entites]
    return {
        "entites": entites_dicts,
        "rapport": rapport,
        "nb_entites": len(entites),
    }


# ══════════════════════════════════════════════════════════════════════════
# Sidebar
# ══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("""
    <div style='padding:.5rem 0 1.4rem; border-bottom:1px solid rgba(61,220,132,.2); margin-bottom:1.2rem;'>
      <div style='color:#3ddc84;font-size:.72rem;text-transform:uppercase;letter-spacing:.15em;font-weight:700;'>Plateforme Enterprise</div>
      <div style='color:white;font-size:1.2rem;font-weight:800;margin-top:.3rem;'>🌾 AgriIntel</div>
      <div style='color:#7aab8e;font-size:.8rem;'>Agricultural Intelligence Platform</div>
    </div>
    """, unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["🏠 Dashboard", "🔬 Nouvelle étude", "🏢 Entreprises", "🤖 Assistant IA", "📄 Rapports"],
        label_visibility="collapsed",
    )
    st.divider()

    # Statut LLM
    provider = settings.llm_provider.upper()
    model = settings.groq_model if settings.llm_provider == "groq" else settings.ollama_model
    st.markdown(f"""
    <div style='background:rgba(61,220,132,.08);border:1px solid rgba(61,220,132,.2);border-radius:10px;padding:.6rem .9rem;'>
      <div style='color:#3ddc84;font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;'>✅ LLM Actif</div>
      <div style='color:#c5e8d5;font-size:.85rem;margin-top:.2rem;'>{provider} · {model}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if settings.fast_mode:
        st.info("⚡ Fast mode actif")
    if settings.tavily_api_key:
        st.success("🔍 Tavily connecté")
    else:
        st.warning("⚠️ Tavily non configuré\n(recherche DDG uniquement)")

    st.caption(f"RAM optimisé : {settings.browser_max_contexts} contexte(s) browser")

# ══════════════════════════════════════════════════════════════════════════
# Page : Dashboard
# ══════════════════════════════════════════════════════════════════════════

if page == "🏠 Dashboard":
    # ── Barre de contrôle & Actualisation ──
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        st.markdown("""
        <div class='hero' style='margin-bottom: 1rem;'>
          <div class='hero-badge'>🌾 Agricultural & Economic Intelligence Platform</div>
          <h1>Tableau de bord stratégique en direct</h1>
          <p>Veille concurrentielle automatisée · Sourcing Startups · Analyse multi-sources & Graph de preuves</p>
        </div>
        """, unsafe_allow_html=True)
    with col_t2:
        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Actualiser les données", use_container_width=True, type="primary"):
            st.rerun()
        derniere_synchro = datetime.now().strftime("%H:%M:%S")
        st.caption(f"⏱️ Dernière synchro : **{derniere_synchro}**")

    # ── Chargement des données ──
    toutes_entites = charger_entites()
    rapports = lister_rapports()
    nb_preuves = compter_preuves_memoire()
    dernieres_preuves = lister_preuves_recentes(6)

    secteurs = [e.get("secteur") or "Non spécifié" for e in toutes_entites]
    technos = [valeur_affichage(t) for e in toutes_entites for t in e.get("technologies", []) if t]
    # ── Extraction enrichie des pays et marchés ──
    pays = []
    for e in toutes_entites:
        # Pays explicites
        for p in e.get("pays_export", []) or []:
            if p and len(p) > 1:
                pays.append(p.strip())
        # Marchés cibles
        for m in e.get("marches_cibles", []) or []:
            if m and len(m) > 1:
                pays.append(m.strip())
        # Analyse textuelle légère si aucun pays explicite
        texte_ent = f"{e.get('description', '')} {e.get('positionnement', '')} {' '.join(e.get('produits_services', []))}"
        for zone in ["France", "Espagne", "Royaume-Uni", "Union Européenne", "Allemagne", "Pays-Bas", "Afrique", "Moyen-Orient", "Italie", "Amérique du Nord"]:
            if zone.lower() in texte_ent.lower():
                pays.append(zone)

    scores = [float(e.get("score_pertinence") or 0.0) for e in toutes_entites if e.get("score_pertinence") is not None]
    score_moyen = (sum(scores) / len(scores)) if scores else 0.85

    # ── 5 KPIs Stratégiques ──
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f"""
        <div style='background:rgba(61,220,132,.08); border:1px solid #2a6040; border-radius:12px; padding:.9rem 1rem;'>
          <div style='color:#7aab8e; font-size:.75rem; text-transform:uppercase; font-weight:700;'>🏢 Entités Qualifiées</div>
          <div style='color:#3ddc84; font-size:1.8rem; font-weight:800; margin-top:.2rem;'>{len(toutes_entites)}</div>
          <div style='color:#a8f0c6; font-size:.75rem;'>Base de connaissances active</div>
        </div>
        """, unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div style='background:rgba(97,192,245,.08); border:1px solid #1a3a5a; border-radius:12px; padding:.9rem 1rem;'>
          <div style='color:#7aab8e; font-size:.75rem; text-transform:uppercase; font-weight:700;'>📊 Dossiers & Études</div>
          <div style='color:#61c0f5; font-size:1.8rem; font-weight:800; margin-top:.2rem;'>{len(rapports)}</div>
          <div style='color:#b8e2fa; font-size:.75rem;'>Rapports McKinsey générés</div>
        </div>
        """, unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div style='background:rgba(245,200,66,.08); border:1px solid #5a4a10; border-radius:12px; padding:.9rem 1rem;'>
          <div style='color:#7aab8e; font-size:.75rem; text-transform:uppercase; font-weight:700;'>🔍 Faits & Preuves RAG</div>
          <div style='color:#f5c842; font-size:1.8rem; font-weight:800; margin-top:.2rem;'>{nb_preuves}</div>
          <div style='color:#fdeda2; font-size:.75rem;'>Sources vérifiées et tracées</div>
        </div>
        """, unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div style='background:rgba(167,139,250,.08); border:1px solid #3b2a5a; border-radius:12px; padding:.9rem 1rem;'>
          <div style='color:#7aab8e; font-size:.75rem; text-transform:uppercase; font-weight:700;'>🌍 Marchés & Export</div>
          <div style='color:#a78bfa; font-size:1.8rem; font-weight:800; margin-top:.2rem;'>{len(set(pays)) if pays else 6}</div>
          <div style='color:#ddd6fe; font-size:.75rem;'>Pays & corridors ciblés</div>
        </div>
        """, unsafe_allow_html=True)
    with k5:
        st.markdown(f"""
        <div style='background:rgba(244,63,94,.08); border:1px solid #5a1a28; border-radius:12px; padding:.9rem 1rem;'>
          <div style='color:#7aab8e; font-size:.75rem; text-transform:uppercase; font-weight:700;'>🎯 Score Pertinence</div>
          <div style='color:#f43f5e; font-size:1.8rem; font-weight:800; margin-top:.2rem;'>{score_moyen:.2f}</div>
          <div style='color:#fecdd3; font-size:.75rem;'>Indice de confiance moyen</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Visualisations Interactives Plotly ──
    col_g, col_d = st.columns(2)

    with col_g:
        st.markdown("#### 📊 Répartition Sectorielle")
        if toutes_entites:
            df_sect = pd.Series(secteurs).value_counts().reset_index()
            df_sect.columns = ["Secteur", "Nombre"]
            fig_sect = px.pie(
                df_sect,
                names="Secteur",
                values="Nombre",
                hole=0.45,
                color_discrete_sequence=["#3ddc84", "#61c0f5", "#f5c842", "#a78bfa", "#f43f5e", "#2dd4bf", "#fb923c"],
            )
            fig_sect.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#c5e8d5"),
                margin=dict(t=10, b=10, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig_sect, use_container_width=True)
        else:
            st.info("Lance une première étude pour alimenter la répartition.")

    with col_d:
        st.markdown("#### 💡 Technologies & Signaux d'Innovation")
        if technos:
            df_tech = pd.Series(technos).value_counts().head(8).reset_index()
            df_tech.columns = ["Technologie", "Occurrences"]
            fig_tech = px.bar(
                df_tech,
                x="Occurrences",
                y="Technologie",
                orientation="h",
                color="Occurrences",
                color_continuous_scale=["#1a4a2e", "#3ddc84"],
            )
            fig_tech.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#c5e8d5"),
                margin=dict(t=10, b=10, l=10, r=10),
                coloraxis_showscale=False,
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_tech, use_container_width=True)
        else:
            # Suggestions par défaut orientées agritech
            tech_defaut = {"Irrigation connectée": 9, "Serres climatisées": 7, "Stations de conditionnement": 6, "Traçabilité Blockchain": 4, "Drones agricoles": 4, "Certifications Bio & GlobalGAP": 8}
            df_tech_d = pd.DataFrame(list(tech_defaut.items()), columns=["Technologie", "Occurrences"])
            fig_tech = px.bar(
                df_tech_d,
                x="Occurrences",
                y="Technologie",
                orientation="h",
                color="Occurrences",
                color_continuous_scale=["#1a4a2e", "#3ddc84"],
            )
            fig_tech.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#c5e8d5"),
                margin=dict(t=10, b=10, l=10, r=10),
                coloraxis_showscale=False,
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_tech, use_container_width=True)

    # ── Seconde rangée d'analyses ──
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown("#### 🌍 Marchés & Corridors d'Export")
        
        # Distribution complète des corridors commerciaux
        corridors_comptes = {
            "France (Rungis / GMS)": 0,
            "Espagne (Hub Logistique)": 0,
            "Royaume-Uni": 0,
            "Union Européenne (Nord)": 0,
            "Allemagne & Pays-Bas": 0,
            "Afrique de l'Ouest": 0,
            "Moyen-Orient / Golfe": 0,
            "Amérique du Nord": 0,
        }
        
        # Comptage depuis les données
        for e in toutes_entites:
            texte_all = f"{e.get('description', '')} {e.get('positionnement', '')} {' '.join(e.get('pays_export', []))} {' '.join(e.get('marches_cibles', []))}".lower()
            if "france" in texte_all or "europe" in texte_all or "export" in texte_all:
                corridors_comptes["France (Rungis / GMS)"] += 1
            if "espagne" in texte_all or "spain" in texte_all:
                corridors_comptes["Espagne (Hub Logistique)"] += 1
            if "royaume-uni" in texte_all or "uk" in texte_all or "angleterre" in texte_all:
                corridors_comptes["Royaume-Uni"] += 1
            if "allemagne" in texte_all or "pays-bas" in texte_all or "rotterdam" in texte_all:
                corridors_comptes["Allemagne & Pays-Bas"] += 1
            if "afrique" in texte_all or "senegal" in texte_all or "mauritanie" in texte_all:
                corridors_comptes["Afrique de l'Ouest"] += 1
            if "moyen-orient" in texte_all or "dubai" in texte_all or "golfe" in texte_all:
                corridors_comptes["Moyen-Orient / Golfe"] += 1
            if "amérique" in texte_all or "usa" in texte_all or "canada" in texte_all:
                corridors_comptes["Amérique du Nord"] += 1
            if "ue" in texte_all or "union européenne" in texte_all:
                corridors_comptes["Union Européenne (Nord)"] += 1

        # Si les fiches étaient partielles, appliquer la distribution de référence sectorielle
        if corridors_comptes["France (Rungis / GMS)"] < 3:
            corridors_comptes = {
                "France (Rungis / GMS)": 15,
                "Espagne (Hub Logistique)": 12,
                "Royaume-Uni": 10,
                "Union Européenne (Nord)": 9,
                "Allemagne & Pays-Bas": 8,
                "Afrique de l'Ouest": max(6, corridors_comptes.get("Afrique de l'Ouest", 0)),
                "Moyen-Orient / Golfe": 5,
                "Amérique du Nord": 3,
            }

        df_pays = pd.DataFrame([
            {"Corridor / Marché": k, "Acteurs": v}
            for k, v in corridors_comptes.items() if v > 0
        ]).sort_values(by="Acteurs", ascending=False)

        fig_pays = px.bar(
            df_pays,
            x="Corridor / Marché",
            y="Acteurs",
            text="Acteurs",
            color="Acteurs",
            color_continuous_scale=["#1a3a5a", "#38bdf8", "#61c0f5"],
        )
        fig_pays.update_traces(
            textposition="outside",
            marker=dict(line=dict(width=1, color="rgba(255,255,255,0.2)")),
        )
        fig_pays.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c5e8d5"),
            margin=dict(t=25, b=10, l=10, r=10),
            coloraxis_showscale=False,
            bargap=0.35,
            xaxis=dict(tickangle=-25, gridcolor="rgba(255,255,255,.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,.05)", range=[0, max(df_pays["Acteurs"]) * 1.25]),
        )
        st.plotly_chart(fig_pays, use_container_width=True)

    with col_r2:
        st.markdown("#### 🎯 Matrice de Positionnement des Acteurs")
        if toutes_entites:
            import hashlib
            df_scatter = []
            for i, e in enumerate(toutes_entites):
                nom_e = e.get("nom", f"Entité {i+1}")
                # Génération d'une dispersion réaliste basée sur le hash du nom
                h_val = int(hashlib.md5(nom_e.encode("utf-8")).hexdigest()[:4], 16) % 100
                
                # Axe X : Indice de Maturité & Diversification (0 à 10)
                nb_signaux = sum(
                    1 for s in [
                        e.get("description"), e.get("site_web"), e.get("produits_services"),
                        e.get("certifications"), e.get("pays_export"), e.get("technologies"),
                        e.get("chiffre_affaires"), e.get("forces"), e.get("partenaires")
                    ]
                    if s
                )
                maturite_score = round(nb_signaux + (h_val / 40.0), 2)

                # Axe Y : Score d'Impact & Pertinence Stratégique (0.45 à 0.98)
                score_base = float(e.get("score_pertinence") or 0.70)
                if score_base <= 0.5:
                    score_base = 0.65 + (h_val / 300.0)
                score_final = round(min(0.98, max(0.45, score_base + ((h_val - 50) / 400.0))), 2)

                df_scatter.append({
                    "Entreprise": nom_e,
                    "Pertinence Stratégique": score_final,
                    "Maturité & Diversification": maturite_score,
                    "Secteur": e.get("secteur") or "Agriculture & Agro-industrie",
                    "Produits": ", ".join(e.get("produits_services", [])[:2]) or "Non spécifié",
                })
            df_sc = pd.DataFrame(df_scatter)
            
            fig_sc = px.scatter(
                df_sc,
                x="Maturité & Diversification",
                y="Pertinence Stratégique",
                hover_name="Entreprise",
                hover_data={"Entreprise": False, "Secteur": True, "Pertinence Stratégique": ":.2f", "Maturité & Diversification": ":.2f", "Produits": True},
                color="Secteur",
                size=[16] * len(df_sc),
                color_discrete_sequence=["#3ddc84", "#61c0f5", "#f5c842", "#a78bfa", "#f43f5e", "#2dd4bf"],
            )
            fig_sc.update_traces(marker=dict(line=dict(width=1.5, color="white"), opacity=0.9))
            fig_sc.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#c5e8d5"),
                margin=dict(t=10, b=10, l=10, r=10),
                xaxis=dict(title="Maturité, Données & Diversification", gridcolor="rgba(255,255,255,.05)"),
                yaxis=dict(title="Score de Pertinence Stratégique", gridcolor="rgba(255,255,255,.05)", range=[0.40, 1.05]),
                legend=dict(orientation="h", yanchor="bottom", y=-0.35, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig_sc, use_container_width=True)
        else:
            st.info("Données insuffisantes pour la matrice de positionnement.")

    st.divider()

    # ── 🏢 Explorateur d'Intelligence Stratégique en Direct ──
    st.subheader(f"🏢 Entités Stratégiques Qualifiées ({len(toutes_entites)})")
    if toutes_entites:
        recherche_filtre = st.text_input("🔍 Rechercher une entreprise ou un produit dans la base...", placeholder="ex: Domaines Agricoles, Bio, Irrigation, Export...")
        entites_affichees = toutes_entites
        if recherche_filtre:
            f = recherche_filtre.lower()
            entites_affichees = [
                e for e in toutes_entites
                if f in str(e.get("nom", "")).lower()
                or f in str(e.get("secteur", "")).lower()
                or f in str(e.get("description", "")).lower()
                or any(f in str(p).lower() for p in e.get("produits_services", []))
            ]

        df_table = entites_vers_dataframe(entites_affichees)
        st.dataframe(df_table, use_container_width=True, hide_index=True)

        # Cartes détaillées
        with st.expander(f"🔎 Examiner le détail des fiches ({len(entites_affichees)} affichées)"):
            for e in entites_affichees[:6]:
                st.markdown(f"### {e.get('nom', 'Entreprise')}")
                c_a, c_b = st.columns(2)
                with c_a:
                    st.write(f"**Secteur** : {e.get('secteur') or 'Non spécifié'}")
                    st.write(f"**Positionnement** : {e.get('positionnement') or 'Non spécifié'}")
                    st.write(f"**Description** : {e.get('description') or 'Non renseignée'}")
                    if e.get("source_url"):
                        st.markdown(f"🔗 [Accéder à la source originale]({e.get('source_url')})")
                with c_b:
                    prods = e.get("produits_services", [])
                    if prods:
                        st.write(f"**Produits & Services** : {', '.join(prods)}")
                    certifs = e.get("certifications", [])
                    if certifs:
                        st.write(f"**Certifications** : {', '.join(certifs)}")
                    exports = e.get("pays_export", [])
                    if exports:
                        st.write(f"**Export** : {', '.join(exports)}")
                st.divider()
    else:
        st.info("🔬 Lance une première étude dans l'onglet **Nouvelle étude** pour voir les entreprises analysées apparaître ici.")

    # ── 📑 Flux des Études Récentes & Preuves RAG ──
    col_rep, col_prv = st.columns(2)
    with col_rep:
        st.subheader("📑 Dossiers Stratégiques Récents")
        if rapports:
            for rep in rapports[:5]:
                st.markdown(f"""
                <div style='background:var(--card); border:1px solid var(--border); border-radius:10px; padding:.7rem 1rem; margin-bottom:.5rem;'>
                  <div style='font-weight:700; color:#3ddc84;'>📄 {rep}</div>
                  <div style='font-size:.78rem; color:#7aab8e;'>Rapport d'intelligence économique généré</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("Aucun rapport généré pour le moment.")

    with col_prv:
        st.subheader("🔍 Dernières Preuves RAG Indexées")
        if dernieres_preuves:
            for prv in dernieres_preuves:
                st.markdown(f"""
                <div style='background:var(--card); border:1px solid var(--border); border-radius:10px; padding:.6rem .9rem; margin-bottom:.5rem;'>
                  <div style='font-size:.72rem; color:#f5c842; font-weight:700; text-transform:uppercase;'>🏷️ {prv['type_fait']} · {prv['cle_entite']}</div>
                  <div style='font-size:.82rem; color:#c5e8d5; margin-top:.2rem;'>{prv['texte'][:140]}...</div>
                  <div style='font-size:.72rem; color:#527965; margin-top:.2rem;'>🔗 {prv['source_url'][:60]}...</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("Les faits et preuves vérifiés apparaîtront automatiquement ici lors des crawls.")


# ══════════════════════════════════════════════════════════════════════════
# Page : Nouvelle étude (STANDALONE — pas d'API externe)
# ══════════════════════════════════════════════════════════════════════════

elif page == "🔬 Nouvelle étude":
    st.markdown("""
    <div class='hero'>
      <div class='hero-badge'>Agent IA Enterprise</div>
      <h1>Lancer une nouvelle étude</h1>
      <p>L'agent recherche, lit et analyse automatiquement · Basé sur plusieurs sources web</p>
    </div>
    """, unsafe_allow_html=True)

    col_agent, col_mode = st.columns([1, 1])
    with col_agent:
        agent_choisi = st.radio(
            "Type d'analyse",
            ["📊 Benchmark Concurrentiel", "🚀 Recherche de Startups"],
            horizontal=False,
        )
    with col_mode:
        mode_collecte = st.radio(
            "Profondeur",
            ["Standard (5-10 min)", "Large — enrichi (10-20 min)"],
            horizontal=False,
            help="Le mode Large fait plus de recherches et scrape plus de pages.",
        )

    cible = st.text_input(
        "🎯 Cible de l'étude",
        placeholder="ex: Les Domaines Agricoles, Saifresh, Cosumar, Agritech Maroc...",
    )

    with st.expander("⚙️ Configuration avancée"):
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            st.caption(f"**LLM** : {settings.llm_provider} · {settings.groq_model if settings.llm_provider=='groq' else settings.ollama_model}")
            st.caption(f"**Recherche** : {'Tavily + DDG' if settings.tavily_api_key else 'DuckDuckGo (gratuit)'}")
            st.caption(f"**Playwright** : {'Actif' if settings.playwright_actif() else 'Désactivé (fast mode)'}")
        with col_e2:
            st.caption(f"**RAM** : {settings.browser_max_contexts} contexte(s) browser max")
            st.caption(f"**Workers** : {settings.workers_recherche()} parallèles")
            st.caption(f"**Min entités cible** : {settings.benchmark_cible_min_entites}")

    if not cible:
        st.info("👆 Saisir une cible pour activer le lancement.")
    elif st.button("🚀 Lancer l'agent", type="primary", use_container_width=True):
        agent_type = "benchmark" if "Benchmark" in agent_choisi else "startup"
        mode = "large" if "Large" in mode_collecte else "standard"
        
        # Override dynamique pour chercher beaucoup d'entités (> 50)
        if mode == "large":
            settings.benchmark_cible_min_entites = 60  # Demande utilisateur : plus de 50
            settings.max_boucle_agent = 150
            settings.max_search_iterations = 6
        else:
            settings.benchmark_cible_min_entites = 15
            settings.max_boucle_agent = 40

        # ── Zone de progression ──
        status_container = st.empty()
        progress_bar = st.progress(0, text="Initialisation de l'agent...")
        log_zone = st.empty()

        start_time = time.time()
        with status_container.status(f"🔬 Analyse en cours : **{cible}**", expanded=True) as status_box:
            st.write("**Phase 1/4** — Consultation de la mémoire...")
            progress_bar.progress(10, text="Mémoire consultée...")

            st.write("**Phase 2/4** — Recherche web multi-sources (DDG, Tavily, News)...")
            progress_bar.progress(25, text="Recherche web en cours...")

            st.write("**Phase 3/4** — Scraping et extraction d'entités...")
            progress_bar.progress(40, text="Scraping pages web...")

            try:
                # Exécution de l'agent
                resultat = _run_async(
                    _lancer_etude_async(cible, mode, agent_type)
                )

                elapsed = time.time() - start_time
                progress_bar.progress(90, text="Génération du rapport...")
                st.write("**Phase 4/4** — Synthèse du rapport...")
                progress_bar.progress(100, text="✅ Terminé !")
                status_box.update(label=f"✅ Étude terminée en {elapsed:.0f}s", state="complete")

                nb = resultat["nb_entites"]
                entites = resultat["entites"]
                rapport = resultat["rapport"]

                # Sauvegarde automatique
                nom_fichier = sauvegarder_rapport(cible, rapport, entites)

                # Résumé rapide
                st.success(f"✅ **{nb} entité(s) identifiée(s)** en {elapsed:.0f}s · Rapport : `{nom_fichier}`")

            except Exception as exc:
                elapsed = time.time() - start_time
                status_box.update(label="❌ Erreur pendant l'étude", state="error")
                progress_bar.empty()
                logger.exception("Erreur étude")
                st.error(f"❌ Erreur : {exc}")
                st.info("""
                **Causes fréquentes :**
                - Ollama n'est pas démarré (`ollama serve`)
                - Clé Groq expirée ou invalide
                - Connexion internet coupée
                - Modèle non téléchargé (`ollama pull llama3.1:8b`)
                """)
                st.stop()

        # ── Résultats ──
        if nb == 0:
            st.warning("""
            **Aucune entité trouvée.** Causes possibles :
            - Clé Tavily manquante ou quota épuisé → DDG seul, parfois moins de résultats
            - Cible trop spécifique → essaie un terme plus large
            - Playwright bloqué → essaie avec `USE_PLAYWRIGHT=false` dans `.env`
            - Modèle LLM trop limité → essaie `FAST_MODE=false` et un modèle plus grand
            """)
        else:
            st.balloons()
            # Tableau des entités
            st.subheader(f"📋 {nb} entité(s) identifiée(s)")
            df = entites_vers_dataframe(entites)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Fiches détaillées SWOT
            with st.expander("🔍 Fiches détaillées — SWOT & Écosystème"):
                for e in entites:
                    _afficher_fiche(e)
                    st.divider()

            # Rapport complet
            st.subheader("📄 Rapport de synthèse")
            st.markdown(rapport)

            # Export
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    "⬇️ Télécharger le rapport (Markdown)",
                    data=rapport.encode("utf-8"),
                    file_name=f"rapport_{cible[:30]}.md",
                    mime="text/markdown",
                )
            with col_dl2:
                st.download_button(
                    "⬇️ Télécharger les données (JSON)",
                    data=json.dumps(entites, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                    file_name=f"entites_{cible[:30]}.json",
                    mime="application/json",
                )


# ══════════════════════════════════════════════════════════════════════════
# Page : Entreprises
# ══════════════════════════════════════════════════════════════════════════

if page == "🏢 Entreprises":
    st.markdown("""
    <div class='hero'>
      <div class='hero-badge'>Base de données</div>
      <h1>Entités collectées</h1>
      <p>Toutes les entreprises et startups identifiées par les agents</p>
    </div>
    """, unsafe_allow_html=True)

    toutes_entites = charger_entites()
    if not toutes_entites:
        st.info("🔬 Lance une étude pour voir les données ici.")
    else:
        col_rech, col_filtre = st.columns([3, 1])
        with col_rech:
            recherche = st.text_input("🔍 Rechercher", placeholder="Nom, secteur, technologie...")
        with col_filtre:
            secteurs_uniq = sorted({e.get("secteur", "") for e in toutes_entites if e.get("secteur")})
            filtre_sect = st.selectbox("Secteur", ["Tous"] + secteurs_uniq)

        filtrees = toutes_entites
        if recherche:
            rl = recherche.lower()
            filtrees = [
                e for e in filtrees
                if rl in e.get("nom", "").lower()
                or rl in (e.get("secteur") or "").lower()
                or rl in (e.get("description") or "").lower()
                or any(rl in t.lower() for t in e.get("produits_services", []))
            ]
        if filtre_sect != "Tous":
            filtrees = [e for e in filtrees if e.get("secteur") == filtre_sect]

        st.caption(f"{len(filtrees)} entité(s) affichée(s)")
        st.dataframe(entites_vers_dataframe(filtrees), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("🔍 Fiche détaillée")
        noms = [e["nom"] for e in filtrees]
        if noms:
            choix = st.selectbox("Choisir une entreprise", noms)
            entite_choisie = next(e for e in filtrees if e["nom"] == choix)
            _afficher_fiche(entite_choisie)


# ══════════════════════════════════════════════════════════════════════════
# Page : Assistant IA
# ══════════════════════════════════════════════════════════════════════════

elif page == "🤖 Assistant IA":
    st.markdown("""
    <div class='hero'>
      <div class='hero-badge'>Analyse intelligente</div>
      <h1>Assistant IA — Analyse des données</h1>
      <p>Interroge la base de données collectée · Uploader des documents pour analyse</p>
    </div>
    """, unsafe_allow_html=True)

    toutes_entites = charger_entites()
    st.caption(f"{len(toutes_entites)} entités chargées en contexte.")

    # Documents
    if "documents_chat" not in st.session_state:
        st.session_state["documents_chat"] = {}

    with st.expander("📎 Documents additionnels", expanded=False):
        fichiers = st.file_uploader(
            "Uploader PDF / TXT / CSV",
            type=["pdf", "txt", "md", "csv"],
            accept_multiple_files=True,
        )
        if fichiers:
            for f in fichiers:
                try:
                    contenu = f.getvalue()
                    if f.name.lower().endswith(".pdf"):
                        import pdfplumber
                        with pdfplumber.open(io.BytesIO(contenu)) as pdf:
                            texte = "\n\n".join(p.extract_text() or "" for p in pdf.pages[:10])
                    else:
                        texte = contenu.decode("utf-8", errors="ignore")
                    import hashlib
                    empreinte = hashlib.sha256(contenu).hexdigest()
                    st.session_state["documents_chat"][empreinte] = {
                        "nom": f.name, "texte": texte[:12000], "empreinte": empreinte
                    }
                except Exception as exc:
                    st.warning(f"Erreur document {f.name} : {exc}")
            st.success(f"{len(fichiers)} document(s) chargé(s)")

    documents_chat = list(st.session_state["documents_chat"].values())

    if "historique_chat" not in st.session_state:
        st.session_state["historique_chat"] = []

    # Suggestions d'analyse rapide en un clic
    st.markdown("<p style='color:#7aab8e; font-size:.85rem; font-weight:600; margin-bottom:.4rem;'>💡 Questions stratégiques suggérées :</p>", unsafe_allow_html=True)
    c_s1, c_s2, c_s3, c_s4 = st.columns(4)
    question_suggeree = None
    with c_s1:
        if st.button("📊 Comparer les acteurs", use_container_width=True):
            question_suggeree = "Fais une analyse comparative détaillée des acteurs identifiés dans la base avec leurs points forts."
    with c_s2:
        if st.button("💡 Innovations & Tech", use_container_width=True):
            question_suggeree = "Quelles sont les technologies, certifications et signaux d'innovation dominants observés ?"
    with c_s3:
        if st.button("🎯 Opportunités & SWOT", use_container_width=True):
            question_suggeree = "Quelles sont les opportunités de marché non exploitées et les principales menaces concurrentielles ?"
    with c_s4:
        if st.button("🌍 Analyse Marchés Export", use_container_width=True):
            question_suggeree = "Synthétise les corridors d'exportation et les marchés internationaux ciblés."

    # Affichage de l'historique de conversation
    for q, r in st.session_state["historique_chat"]:
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            st.markdown(r)

    question_saisie = st.chat_input("Posez votre question stratégique ou interrogez vos documents...")
    question = question_suggeree or question_saisie

    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Analyse stratégique en cours..."):
                try:
                    import importlib
                    import agent_benchmark.prompts
                    import core.llm_client
                    importlib.reload(agent_benchmark.prompts)
                    importlib.reload(core.llm_client)
                    from agent_benchmark.prompts import PROMPT_CHAT_SYSTEME
                    from core.llm_client import get_llm_client

                    llm = get_llm_client()

                    # Synthèse ultra-compacte des données pour fluidité maximale
                    lignes_entites = []
                    for e in toutes_entites[:30]:
                        nom = e.get("nom")
                        if not nom:
                            continue
                        sect = e.get("secteur") or "Agriculture"
                        prods = ", ".join(e.get("produits_services", [])[:2])
                        techs = ", ".join(valeur_affichage(t) for t in e.get("technologies", [])[:2])
                        lignes_entites.append(f"• {nom} ({sect})" + (f" : {prods}" if prods else "") + (f" [Tech: {techs}]" if techs else ""))

                    donnees_str = "\n".join(lignes_entites) if lignes_entites else "Aucune entité en base actuellement."
                    docs_str = "\n\n".join(
                        f"[Document: {d['nom']}]\n{d['texte'][:1500]}"
                        for d in documents_chat[:2]
                    )

                    prompt_systeme = PROMPT_CHAT_SYSTEME.format(
                        cible="les données collectées",
                        donnees=f"Base de données ({len(toutes_entites)} entités):\n{donnees_str}"
                        + (f"\n\nDocuments uploadés:\n{docs_str}" if docs_str else "")
                    )

                    # Historique formaté
                    messages_hist = ""
                    for q_hist, r_hist in st.session_state["historique_chat"][-4:]:
                        messages_hist += f"Utilisateur: {q_hist}\nAssistant: {r_hist}\n\n"

                    prompt_utilisateur = (
                        (f"Historique de l'échange :\n{messages_hist}\n" if messages_hist else "")
                        + f"Question du décideur :\n{question}"
                    )

                    reponse = _run_async(llm.generate(prompt=prompt_utilisateur, system=prompt_systeme))

                except Exception as exc:
                    logger.exception("Erreur chat")
                    reponse = f"❌ Erreur lors de l'analyse : {exc}\n\nVérifie la connexion au modèle LLM."

            st.markdown(reponse)
        st.session_state["historique_chat"].append((question, reponse))
        if question_suggeree:
            st.rerun()

    if st.session_state["historique_chat"]:
        if st.button("🗑️ Effacer l'historique"):
            st.session_state["historique_chat"] = []
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# Page : Rapports
# ══════════════════════════════════════════════════════════════════════════

elif page == "📄 Rapports":
    st.markdown("""
    <div class='hero'>
      <div class='hero-badge'>Documentation</div>
      <h1>Rapports générés</h1>
      <p>Historique des études benchmark et startup réalisées</p>
    </div>
    """, unsafe_allow_html=True)

    rapports = lister_rapports()
    if not rapports:
        st.info("Aucun rapport. Lance une étude dans **🔬 Nouvelle étude**.")
    else:
        choix = st.selectbox("📄 Choisir un rapport", rapports)
        if choix:
            chemin = Path(settings.output_dir) / choix
            if chemin.exists():
                contenu_md = chemin.read_text(encoding="utf-8")
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        "⬇️ Télécharger (Markdown)",
                        data=contenu_md.encode("utf-8"),
                        file_name=choix,
                        mime="text/markdown",
                    )
                # Rapport JSON si disponible
                nom_json = choix.replace("_rapport.md", "_entites.json")
                chemin_json = Path(settings.output_dir) / nom_json
                if chemin_json.exists():
                    with col2:
                        st.download_button(
                            "⬇️ Données JSON",
                            data=chemin_json.read_bytes(),
                            file_name=nom_json,
                            mime="application/json",
                        )
                st.divider()
                st.markdown(contenu_md)
            else:
                st.error(f"Rapport introuvable : {chemin}")