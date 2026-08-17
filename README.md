# 🌾 AgriIntel — Plateforme d'Intelligence Économique Agricole par Agents IA

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent_Framework-green.svg)](https://langchain-ai.github.io/langgraph/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-red.svg)](https://streamlit.io)
[![Docker](https://img.shields.io/badge/Docker-Containerized-blue.svg)](https://docker.com)

> **Projet de Fin d'Année (PFA)** — Stage d'ingénierie chez *Domseed / Les Domaines Agricoles*  
> École des Sciences de l'Information (ESI) — Filière Intelligence Artificielle & Data Science

---

## 📋 Description

**AgriIntel** est une plateforme d'intelligence économique et de veille concurrentielle propulsée par des **agents IA autonomes**. Elle automatise la recherche, l'analyse et la synthèse d'informations stratégiques sur le secteur agro-industriel.

### 🎯 Fonctionnalités Principales

- **Agents IA Multi-Étapes (LangGraph)** — Orchestration autonome d'agents de benchmark concurrentiel et de sourcing startups
- **Moteur de Recherche Multi-Sources** — Tavily, Google CSE, DuckDuckGo, Brave avec scraping résilient (Playwright, Trafilatura, BeautifulSoup)
- **Mémoire RAG Vectorielle Asynchrone** — Base de connaissances vectorielle (SQLite + aiosqlite + Numpy) avec similarité cosinus sémantique
- **Résolution d'Entités Canoniques** — Déduplication intelligente par Levenshtein + domaine web
- **Génération de Rapports Stratégiques** — SWOT, 5 Forces de Porter, PESTEL automatisés (niveau cabinet McKinsey)
- **Dashboard Interactif** — Tableau de bord décisionnel en temps réel (Streamlit + Plotly)
- **API REST** — Interface FastAPI haute performance avec traitement en arrière-plan
- **Sécurité Anti-Injection** — Protection contre le Prompt Injection sur le contenu web scrapé

---

## 🏗️ Architecture

```
AgriIntel/
├── config/                    # Configuration centralisée (Pydantic Settings)
│   └── settings.py
├── core/                      # Modules partagés
│   ├── llm_client.py          # Client LLM (Groq + Ollama fallback)
│   ├── memoire.py             # Mémoire RAG vectorielle asynchrone
│   ├── entity_resolution.py   # Résolution et déduplication d'entités
│   ├── query_planner.py       # Planificateur de requêtes structuré
│   ├── scraper_base.py        # Scraping multi-couches résilient
│   ├── models.py              # Modèles Pydantic v2
│   ├── browser_pool.py        # Pool Playwright partagé
│   └── ...
├── agent_benchmark/           # Agent de benchmark concurrentiel
│   ├── agent.py               # Pipeline LangGraph (StateGraph)
│   ├── tools.py               # Outils de l'agent (recherche, scraping, enregistrement)
│   ├── prompts.py             # Prompts système
│   ├── sources.py             # Moteur de recherche multi-provider
│   └── report_generator.py    # Générateur de rapports McKinsey
├── agent_startup/             # Agent de recherche startups & innovation
│   ├── agent.py
│   ├── tools.py
│   ├── sources.py
│   └── report_generator.py
├── tests/                     # Suite de tests (38 tests)
├── app.py                     # Interface Streamlit (Dashboard + Chat IA)
├── api.py                     # API REST FastAPI
├── Dockerfile.api             # Conteneurisation Docker
├── docker-compose.yml         # Orchestration multi-services
├── requirements.txt           # Dépendances Python
└── .env.example               # Template de configuration
```

---

## 🛠️ Stack Technique

| Composant | Technologie |
|---|---|
| **LLM** | Groq API (LLaMA 3.3 70B) + Ollama (fallback local) |
| **Framework Agent** | LangGraph (StateGraph) |
| **Backend API** | FastAPI + uvicorn |
| **Frontend** | Streamlit + Plotly |
| **Base de Données** | SQLite + aiosqlite (RAG vectoriel) |
| **Scraping** | Playwright + Trafilatura + BeautifulSoup |
| **Recherche Web** | Tavily + Google CSE + DuckDuckGo + Brave |
| **Conteneurisation** | Docker + Docker Compose |
| **Validation** | Pydantic v2 + Pytest (38 tests) |
| **Langage** | Python 3.11 |

---

## ⚡ Installation & Lancement

### Prérequis
- Python 3.11+
- [Ollama](https://ollama.com) (optionnel, pour le mode local)
- Clé API Groq gratuite : [console.groq.com](https://console.groq.com)

### Installation

```bash
# Cloner le projet
git clone https://github.com/AbdeljalilDS/AgriIntel.git
cd AgriIntel

# Créer l'environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec votre GROQ_API_KEY
```

### Lancement

```bash
# Dashboard Streamlit
streamlit run app.py

# API REST (optionnel)
uvicorn api:app --host 0.0.0.0 --port 8000

# Docker (production)
docker-compose up --build
```

---

## 🧪 Tests

```bash
pytest -v
# 38 passed, 1 skipped
```

---

## 📊 Résultats

- **32+ entités** identifiées et documentées automatiquement
- **18 études** de benchmark complètes générées
- **85%** de réduction du temps de veille stratégique
- **38 tests unitaires** validés

---

## 📄 Licence

Projet académique — PFA ESI 2026.

---

## 👤 Auteur

**Abdeljalil Ida L'Ahaj**  
Étudiant Ingénieur Bac+4 — Intelligence Artificielle & Data Science  
École des Sciences de l'Information (ESI), Rabat

**Encadrant Entreprise** — Domseed / Les Domaines Agricoles
