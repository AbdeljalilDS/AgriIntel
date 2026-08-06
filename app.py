"""Frontend Streamlit — communique UNIQUEMENT avec l'API FastAPI via HTTP.
Prérequis : l'API doit tourner (uvicorn api:app --reload)
Lancer : streamlit run app.py
"""
import os
import io
import hashlib
import time

import pandas as pd
import requests
import streamlit as st
from core.models import valeur_affichage

# En local : http://127.0.0.1:8000/api (valeur par défaut)
# En Docker : surchargé par la variable d'environnement API_URL (voir docker-compose.yml)
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000/api")
st.set_page_config(page_title="Benchmark Intelligence", page_icon="BI", layout="wide", initial_sidebar_state="expanded")


def api_get(chemin, **kwargs):
    return requests.get(f"{API_URL}{chemin}", timeout=30, **kwargs)


def api_post(chemin, json_data, **kwargs):
    return requests.post(f"{API_URL}{chemin}", json=json_data, timeout=30, **kwargs)


def extraire_document(fichier) -> dict:
    """Extrait un contexte borne pour le chat sans persister le fichier."""
    contenu = fichier.getvalue()
    extension = fichier.name.lower().rsplit(".", 1)[-1] if "." in fichier.name else "txt"
    try:
        if extension == "pdf":
            import pdfplumber
            with pdfplumber.open(io.BytesIO(contenu)) as pdf:
                texte = "\n\n".join(page.extract_text() or "" for page in pdf.pages[:10])
        elif extension == "csv":
            texte = contenu.decode("utf-8", errors="ignore")
        else:
            texte = contenu.decode("utf-8", errors="ignore")
    except Exception as exc:
        return {"nom": fichier.name, "texte": "", "erreur": str(exc)}
    texte = texte[:12000]
    return {
        "nom": fichier.name,
        "texte": texte,
        "taille": len(contenu),
        "empreinte": hashlib.sha256(contenu).hexdigest(),
    }

st.markdown(
    """
    <style>
    :root { --ink:#e8f3f1; --muted:#a8bfbd; --line:#294653; --paper:#0b1720; --card:#122633; --navy:#d7f1eb; --teal:#58c7a4; --amber:#e8a04d; --green:#183d3a; }
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: var(--paper) !important; color: var(--ink) !important; }
    [data-testid="stHeader"] { background: transparent !important; }
    .stApp p, .stApp label, .stApp li, .stApp td, .stApp th, .stApp [data-testid="stMarkdownContainer"] { color: var(--ink) !important; }
    .stApp small, .stApp [data-testid="stCaptionContainer"] { color: var(--muted) !important; }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: var(--navy) !important; }
    .stApp input, .stApp textarea, .stApp [data-baseweb="select"] > div { color: var(--ink) !important; background:var(--card) !important; border-color:var(--line) !important; }
    .stApp input::placeholder, .stApp textarea::placeholder { color:#9bb3b1 !important; opacity:1 !important; }
    .stApp [data-testid="stDataFrame"], .stApp [data-testid="stExpander"], div[data-testid="stMetric"] { background:var(--card) !important; }
    .stApp [data-testid="stExpander"] { border:1px solid var(--line); }
    [data-testid="stSidebar"] { background: #122633 !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div, [data-testid="stSidebar"] small { color: #e7f5f0 !important; }
    [data-testid="stSidebar"] .stRadio label { padding: .48rem .65rem; border-radius: 8px; }
    [data-testid="stSidebar"] .stRadio label:hover { background: rgba(255,255,255,.10); }
    .brand { padding: .4rem 0 1.4rem; border-bottom: 1px solid rgba(255,255,255,.18); margin-bottom: 1.2rem; }
    .brand-kicker { color:#8bd3c7; font-size:.72rem; text-transform:uppercase; letter-spacing:.12em; font-weight:700; }
    .brand-title { color:white; font-size:1.25rem; font-weight:750; margin-top:.25rem; }
    .eyebrow { color:var(--teal); text-transform:uppercase; letter-spacing:.12em; font-size:.72rem; font-weight:750; }
    .hero { padding: 1.1rem 1.4rem; background: linear-gradient(115deg,#122633,#145b58); border-radius:14px; color:#ffffff; margin-bottom:1.2rem; }
    .hero h1, .hero .eyebrow { color:white !important; margin:.25rem 0 .35rem; font-size:2rem; }
    .hero p { color:#e3f3ee !important; margin:0; }
    div[data-testid="stMetric"] { border:1px solid var(--line); border-radius:12px; padding: .9rem 1rem; box-shadow:0 2px 8px rgba(15,59,74,.07); }
    div[data-testid="stMetricLabel"] { color:var(--muted) !important; }
    .section-title { font-size:1.05rem; font-weight:750; color:var(--navy); margin:1.2rem 0 .55rem; }
    .source-chip { display:inline-block; padding:.2rem .48rem; background:#e6fffb; color:#0f766e; border-radius:999px; font-size:.75rem; margin:.15rem; }
    [data-testid="stChatMessage"] { background:var(--card) !important; border:1px solid var(--line); border-radius:12px; }
    [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { color:var(--ink) !important; }
    .stButton > button { border-radius:8px; font-weight:650; color:#ffffff !important; background:#176b62 !important; border:1px solid #176b62 !important; }
    .stButton > button:hover { background:#12564f !important; }
    .stDownloadButton > button { color:var(--ink) !important; background:var(--green) !important; border:1px solid #2d665f !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

def verifier_api_disponible() -> bool:
    try:
        return api_get("/health").status_code == 200
    except requests.RequestException:
        return False


def entites_vers_dataframe(entites):
    lignes = []
    for e in entites:
        lignes.append({
            "Nom": e.get("nom", ""), "Secteur": e.get("secteur") or "",
            "Description": e.get("description") or "",
            "Produits/services": ", ".join(e.get("produits_services", [])),
            "Technologies": ", ".join(valeur_affichage(item) for item in e.get("technologies", [])),
            "Compétences": ", ".join(valeur_affichage(item) for item in e.get("competences", [])),
            "Investissements": ", ".join(valeur_affichage(item) for item in e.get("investissements", [])),
            "Innovations": ", ".join(valeur_affichage(item) for item in e.get("innovations", [])),
            "Score": e.get("score_pertinence", ""), "Source": e.get("source_url", ""),
        })
    return pd.DataFrame(lignes)


if not verifier_api_disponible():
    st.error("Impossible de joindre l'API sur http://127.0.0.1:8000. Lance-la avec le virtualenv du projet : `venv\\Scripts\\python.exe -m uvicorn api:app --reload`")
    st.stop()

st.sidebar.title("🌾 Benchmark Intelligence")
page = st.sidebar.radio("Navigation", ["🏠 Dashboard", "🚀 Nouvelle étude", "🏢 Entreprises", "🤖 Assistant IA", "📄 Rapports"])
st.sidebar.divider()
st.sidebar.success("✅ API connectée")
try:
    sante = api_get("/health").json()
    st.sidebar.caption(f"Modèle : {sante.get('modele', '—')}")
    if sante.get("fast_mode"):
        st.sidebar.info("⚡ Fast mode actif")
except requests.RequestException:
    pass

toutes_entites = api_get("/entites").json()

if page == "🏠 Dashboard":
    st.title("Dashboard")
    rapports = api_get("/rapports").json()
    secteurs = [e["secteur"] for e in toutes_entites if e.get("secteur")]
    technos = [valeur_affichage(t) for e in toutes_entites for t in e.get("technologies", [])]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Entités analysées", len(toutes_entites))
    col2.metric("Études réalisées", len(rapports))
    col3.metric("Secteurs distincts", len(set(secteurs)))
    col4.metric("Technologies citées", len(set(technos)))

    st.divider()
    col_g, col_d = st.columns(2)
    with col_g:
        st.subheader("Répartition par secteur")
        if secteurs:
            st.bar_chart(pd.Series(secteurs).value_counts())
        else:
            st.caption("Pas encore de données.")
    with col_d:
        st.subheader("Technologies les plus citées")
        if technos:
            st.bar_chart(pd.Series(technos).value_counts().head(10))
        else:
            st.caption("Pas encore de données.")

elif page == "🚀 Nouvelle étude":
    st.title("Lancer une nouvelle étude")
    agent_choisi = st.radio("Quel agent ?", ["📊 Étude Benchmark", "🚀 Recherche de Startup"], horizontal=True)
    cible = st.text_input("Cible", placeholder="ex: Les Domaines Agricoles")
    mode_collecte = st.radio(
        "Profondeur de collecte",
        ["Standard", "Large — enrichir le RAG"],
        horizontal=True,
        help="Le mode large recherche davantage de variantes et de pages. Il est plus long sur CPU.",
    )

    with st.expander("ℹ️ À propos"):
        st.write("L'agent Benchmark cherche, lit et décide lui-même de ses recherches (mémoire + web). Sur CPU, compte plusieurs minutes.")

    if st.button("Lancer l'agent", type="primary", disabled=not cible):
        route = "/benchmark/lancer" if agent_choisi.startswith("📊") else "/startup/lancer"
        mode = "large" if mode_collecte.startswith("Large") else "standard"
        job_id = api_post(route, {"cible": cible, "mode": mode}).json()["job_id"]

        statut_zone = st.empty()
        barre = st.progress(0, text="Démarrage...")
        etape_prec, i = None, 0
        while True:
            data = api_get(f"/jobs/{job_id}").json()
            if data["etape"] != etape_prec:
                etape_prec = data["etape"]
                statut_zone.info(f"⏳ {data['etape']}")
            i = (i + 5) % 100
            barre.progress(i / 100, text=data["etape"] or "En cours...")

            if data["statut"] == "termine":
                barre.progress(100, text="Terminé !")
                resultat = data["resultat"]
                st.success(f"✅ {resultat['nb_entites']} résultat(s) trouvé(s).")
                if resultat["entites"]:
                    st.dataframe(entites_vers_dataframe(resultat["entites"]), use_container_width=True, hide_index=True)
                st.markdown(resultat["rapport"])
                break
            if data["statut"] == "erreur":
                st.error(f"❌ {data['erreur']}")
                break
            if data["statut"] == "interrompu":
                st.warning(f"⚠️ Étude interrompue (redémarrage API). Relancez l'étude.")
                break
            time.sleep(2)

elif page == "🏢 Entreprises":
    st.title("Toutes les entités collectées")
    st.caption(f"{len(toutes_entites)} entités")
    if not toutes_entites:
        st.info("Aucune donnée. Lance une étude dans '🚀 Nouvelle étude'.")
    else:
        recherche = st.text_input("🔍 Rechercher")
        filtrees = toutes_entites
        if recherche:
            rl = recherche.lower()
            filtrees = [e for e in toutes_entites if rl in e["nom"].lower() or rl in (e.get("secteur") or "").lower()]
        st.dataframe(entites_vers_dataframe(filtrees), use_container_width=True, hide_index=True)

elif page == "🤖 Assistant IA":
    st.title("Assistant IA")
    st.caption(f"{len(toutes_entites)} entités chargées. Ajoute un document pour obtenir une analyse ciblée.")
    if "documents_chat" not in st.session_state:
        st.session_state["documents_chat"] = {}
    documents_chat = list(st.session_state["documents_chat"].values())

    if documents_chat:
        with st.expander(f"Documents actifs ({len(documents_chat)})", expanded=True):
            for document in documents_chat:
                col_doc, col_remove = st.columns([8, 1])
                col_doc.caption(f"{document['nom']} · {len(document.get('texte', '')):,} caractères")
                if col_remove.button("×", key=f"remove_{document['empreinte']}", help="Retirer ce document"):
                    del st.session_state["documents_chat"][document["empreinte"]]
                    st.rerun()
    erreurs_documents = [document for document in documents_chat if document.get("erreur")]
    for document in erreurs_documents:
        st.warning(f"Document ignoré ({document['nom']}) : {document['erreur']}")
    if "historique_chat" not in st.session_state:
        st.session_state["historique_chat"] = []

    for q, r in st.session_state["historique_chat"]:
        with st.chat_message("user"): st.write(q)
        with st.chat_message("assistant"): st.write(r)

    with st.popover("+ Ajouter un document", use_container_width=False):
        st.caption("Les documents restent dans cette conversation et seront analysés avec ta question.")
        fichiers = st.file_uploader(
            "Choisir des fichiers",
            type=["pdf", "txt", "md", "csv"],
            accept_multiple_files=True,
            key="documents_upload",
            label_visibility="collapsed",
        )
        if fichiers:
            for fichier in fichiers:
                document = extraire_document(fichier)
                st.session_state["documents_chat"][document["empreinte"]] = document
            documents_chat = list(st.session_state["documents_chat"].values())
            st.success(f"{len(fichiers)} document(s) ajouté(s) au contexte")

    question = st.chat_input("Pose une question sur tes données ou tes documents...")
    if question:
        with st.chat_message("user"): st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Réflexion... (1-2 min sur CPU)"):
                try:
                    r = requests.post(
                        f"{API_URL}/chat",
                        json={
                            "question": question,
                            "historique": st.session_state["historique_chat"][-5:],
                            "documents": [document for document in documents_chat if document.get("texte")],
                        },
                        timeout=(10, 900),
                    )
                    r.raise_for_status()
                    donnees_chat = r.json()
                    reponse = donnees_chat["reponse"]
                except requests.Timeout:
                    donnees_chat = {"niveau": "faible", "confiance": 0, "verifiee": False, "statistiques": {}, "citations": []}
                    reponse = "La recherche prend trop de temps sur cette machine. Réduis le nombre de pages ou relance la question."
                except requests.RequestException as exc:
                    donnees_chat = {"niveau": "faible", "confiance": 0, "verifiee": False, "statistiques": {}, "citations": []}
                    reponse = f"Le service API est momentanément indisponible : {exc}"
            st.write(reponse)
            if donnees_chat.get("niveau"):
                confiance = donnees_chat.get("confiance")
                confiance_affichee = f"{confiance:.0%}" if confiance is not None else "non documentée"
                statut = "oui" if donnees_chat.get("verifiee") else "à confirmer"
                st.caption(f"Confiance : {donnees_chat['niveau']} ({confiance_affichee}) | Vérifiée : {statut}")
            with st.expander("Statistiques et sources"):
                st.json({"statistiques": donnees_chat.get("statistiques", {}), "citations": donnees_chat.get("citations", [])})
        st.session_state["historique_chat"].append((question, reponse))

    if st.session_state["historique_chat"] and st.button("🗑️ Effacer l'historique"):
        st.session_state["historique_chat"] = []
        st.rerun()

elif page == "📄 Rapports":
    st.title("Rapports générés")
    rapports = api_get("/rapports").json()
    if not rapports:
        st.info("Aucun rapport. Lance une étude dans '🚀 Nouvelle étude'.")
    else:
        choix = st.selectbox("Choisir un rapport", rapports)
        if choix:
            contenu_md = api_get(f"/rapports/{choix}/markdown").text
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button("⬇️ Markdown", data=contenu_md, file_name=choix, mime="text/markdown")
            with col2:
                st.download_button("⬇️ Excel", data=api_get(f"/rapports/{choix}/excel").content,
                    file_name=choix.replace("_rapport.md", ".xlsx"),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with col3:
                st.download_button("⬇️ PDF", data=api_get(f"/rapports/{choix}/pdf").content,
                    file_name=choix.replace("_rapport.md", ".pdf"), mime="application/pdf")
            st.divider()
            st.markdown(contenu_md)
