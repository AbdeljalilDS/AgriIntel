# Benchmark Intelligence — Les Domaines Agricoles

Deux agents IA locaux (Ollama, aucune donnée ne sort de la machine) + API
FastAPI + interface Streamlit + déploiement Docker.

## Architecture

- **Agent Benchmark** (`agent_benchmark/`) : boucle agentique où le LLM
  choisit lui-même ses outils (mémoire → recherche web → lecture de
  page/PDF → enregistrement), avec mémoire long terme persistante
  (SQLite + similarité vectorielle en numpy).
- **Agent Startup** (`agent_startup/`) : pipeline simple (recherche →
  scraping → extraction), même base `core/`.
- **API** (`api.py`) : FastAPI, jobs persistés en SQLite, CORS configurable.
- **Interface** (`app.py`) : Streamlit, communique uniquement à l'API en HTTP.

## Installation locale (sans Docker)

```bash
python -m venv venv
source venv/bin/activate          # Windows : venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Édite `.env` :
- `OLLAMA_MODEL` — voir section Modèles ci-dessous
- `TAVILY_API_KEY` (gratuit sur tavily.com, optionnel grâce au repli DuckDuckGo)

```bash
ollama serve
ollama pull llama3.1:8b          # recommandé (8+ Go RAM)
ollama pull nomic-embed-text     # pour la mémoire vectorielle (~137M)
```

Lancement (2 terminaux) :
```bash
uvicorn api:app --reload          # terminal 1 — http://localhost:8000/docs
streamlit run app.py              # terminal 2 — http://localhost:8501
```

## Modèles Ollama recommandés

| Modèle | RAM | Usage |
|--------|-----|-------|
| `llama3.1:8b` | 8+ Go | **Recommandé** — meilleur raisonnement |
| `llama3.2:3b` | 4-8 Go | Minimum — plus rapide, moins précis |
| `mistral:7b` | 8+ Go | Alternative performante |

Sur machine lente (CPU, 8 Go RAM) : `FAST_MODE=true` dans `.env`.

## Recherche web (avec ou sans Tavily)

Chaîne de repli automatique :
1. Tavily (si clé configurée)
2. Google Custom Search (si clé configurée)
3. **DuckDuckGo** (gratuit, sans clé)
4. Google News RSS
5. Sites sectoriels marocains

## Déploiement Docker

Ollama tourne **sur la machine hôte**, pas dans Docker.

```bash
ollama serve
docker compose up --build
```

En production, définir dans `.env` :
```bash
APP_ENV=production
CORS_ORIGINS=https://votre-domaine.com
```

## Git et secrets

- Le dépôt Git doit être initialisé **dans ce dossier** (`projet_agents/`), pas au niveau utilisateur.
- `.env` et `venv/` sont exclus via `.gitignore` — ne jamais committer de clés API.
- Initialiser le dépôt : `git init` depuis `projet_agents/`.

## Tests

```bash
pytest tests/ -v
```

## Améliorations v2.1

- **Jobs persistés** (`data/jobs.sqlite3`) — survivent aux redémarrages API
- **Recherche DuckDuckGo** — fonctionne sans aucune clé API
- **Recherche parallèle** — variantes exécutées en parallèle (4 workers)
- **Client LLM singleton** — modèle Ollama gardé chaud (`keep_alive`)
- **CORS configurable** — restriction en production via `APP_ENV`
- **Fast mode** — réduit latence sur CPU (`FAST_MODE=true`)
- **Modèle 8B par défaut** — meilleur raisonnement que 3B

## Limites résolues (v2.1)

| Problème | Solution |
|----------|----------|
| Jobs perdus au redémarrage API | Persistance SQLite (`data/jobs.sqlite3`) |
| Recherche bloquée sans Tavily | Repli DuckDuckGo + Google News + sites sectoriels |
| CORS ouvert (`*`) en production | `CORS_ORIGINS` + `APP_ENV=production` |
| Modèle 3B par défaut | `llama3.1:8b` recommandé (3B en secours si RAM limitée) |
| Lenteur CPU | `FAST_MODE=true`, client LLM singleton, recherche parallèle |
| Secrets / venv versionnés | `.gitignore` — initialiser Git dans `projet_agents/` |

## Limites restantes (infrastructure)

- Sur CPU sans GPU, chaque tour agent peut prendre 1-3 min (réduire avec `FAST_MODE=true`).
- Le modèle local peut faire des erreurs sur des comparaisons très complexes — vérifier les résultats.
- La mémoire vectorielle retombe en recherche mot-clé si `nomic-embed-text` n'est pas installé.
