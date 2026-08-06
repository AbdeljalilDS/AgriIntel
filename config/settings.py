from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Environnement : "development" | "production"
    app_env: str = "development"

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    # Recommandé : llama3.1:8b (meilleur raisonnement) ; minimum RAM : llama3.2:3b
    ollama_model: str = "llama3.1:8b"
    embedding_model: str = "nomic-embed-text"
    embedding_validation_threshold: float = 0.45
    llm_timeout: int = 300

    # Optimisations CPU (ajuster selon votre machine)
    ollama_num_predict_chat: int = 280
    ollama_num_predict_agent: int = 350
    ollama_num_predict_json: int = 400
    ollama_num_ctx_chat: int = 3072
    ollama_num_ctx_agent: int = 4096
    ollama_keep_alive: str = "30m"
    # 0 = Ollama auto-détecte les cœurs disponibles (recommandé)
    # Mettre une valeur explicite (ex: 8) si Ollama ne détecte pas bien votre CPU
    ollama_num_thread: int = 0
    fast_mode: bool = False  # réduit tours agent, désactive Playwright, recherche parallèle limitée
    # Nombre max de pages internes crawlées par site (réduit à 2 en fast_mode via playwright_actif)
    max_pages_par_site: int = 4

    tavily_api_key: str = ""
    google_api_key: str = ""
    google_cse_id: str = ""
    enable_duckduckgo: bool = True  # repli gratuit sans clé API

    # CORS — en production, liste explicite (séparée par des virgules)
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501,http://localhost:8000,http://127.0.0.1:8000"

    request_timeout: int = 15
    max_retries: int = 3
    scrape_delay_seconds: float = 1.5
    use_playwright: bool = True
    search_parallel_workers: int = 4
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    max_search_iterations: int = 3
    max_results_per_query: int = 8
    max_variantes_recherche: int = 6
    max_urls_a_scraper: int = 15
    collecte_large_urls: int = 40
    collecte_large_variantes: int = 12
    max_boucle_agent: int = 8
    chat_recherche_live: bool = True
    page_cache_ttl: int = 86400
    response_cache_ttl: int = 3600
    audit_log_path: str = "logs/audit.jsonl"

    output_dir: str = "data/processed"
    raw_dir: str = "data/raw"
    log_dir: str = "logs"
    memoire_db: str = "data/memoire.sqlite3"
    jobs_db: str = "data/jobs.sqlite3"

    def cors_origins_liste(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def playwright_actif(self) -> bool:
        return self.use_playwright and not self.fast_mode

    def max_tours_agent(self, mode: str) -> int:
        base = self.collecte_large_variantes if mode == "large" else self.max_boucle_agent
        return max(4, base - 2) if self.fast_mode else base

    def workers_recherche(self) -> int:
        return 2 if self.fast_mode else self.search_parallel_workers

    def pages_par_site(self) -> int:
        """Nombre max de pages internes crawlées par site — réduit en fast_mode."""
        return 2 if self.fast_mode else self.max_pages_par_site


settings = Settings()
