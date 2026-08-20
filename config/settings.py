from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    api_key: str = ""

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    embedding_model: str = "nomic-embed-text"
    # 0.30 : moins de rejets de fiches valides
    embedding_validation_threshold: float = 0.30
    llm_timeout: int = 300

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    ollama_num_predict_chat: int = 280
    ollama_num_predict_agent: int = 400
    ollama_num_predict_json: int = 500
    ollama_num_ctx_chat: int = 3072
    ollama_num_ctx_agent: int = 4096
    ollama_keep_alive: str = "30m"
    ollama_num_thread: int = 0

    # 8 Go RAM : False = qualité ; True si la machine rame
    fast_mode: bool = False
    max_pages_par_site: int = 4

    # Search providers
    tavily_api_key: str = ""
    tavily_monthly_limit: int = 950
    google_api_key: str = ""
    google_cse_id: str = ""
    enable_duckduckgo: bool = True
    # Nouveaux providers optionnels
    brave_api_key: str = ""
    bing_api_key: str = ""
    serper_api_key: str = ""
    serpapi_key: str = ""

    cors_origins: str = (
        "http://localhost:8501,http://127.0.0.1:8501,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    request_timeout: int = 15
    max_retries: int = 3
    scrape_delay_seconds: float = 1.0
    use_playwright: bool = True
    # Browser pool — 2 contextes sur 8 Go avec Ollama
    browser_max_contexts: int = 2
    # 2 workers suffisent sur 8 Go RAM
    search_parallel_workers: int = 2
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
    max_boucle_agent: int = 12
    benchmark_cible_min_entites: int = 5
    chat_recherche_live: bool = True
    page_cache_ttl: int = 86400
    response_cache_ttl: int = 3600
    audit_log_path: str = "logs/audit.jsonl"

    # Coverage & stop criteria
    min_coverage_score: float = 0.40
    min_source_quality: float = 0.40
    max_search_queries: int = 50
    max_pages_scraped: int = 100
    diminishing_returns_threshold: float = 0.02

    output_dir: str = "data/processed"
    raw_dir: str = "data/raw"
    log_dir: str = "logs"
    memoire_db: str = "data/memoire.sqlite3"
    jobs_db: str = "data/jobs.sqlite3"

    def cors_origins_liste(self) -> list[str]:
        return [
            o.strip() for o in self.cors_origins.split(",") if o.strip()
        ]

    def playwright_actif(self) -> bool:
        return self.use_playwright and not self.fast_mode

    def max_tours_agent(self, mode: str) -> int:
        base = (
            self.collecte_large_variantes
            if mode == "large"
            else self.max_boucle_agent
        )
        return max(4, base - 2) if self.fast_mode else base

    def workers_recherche(self) -> int:
        return 2 if self.fast_mode else self.search_parallel_workers

    def pages_par_site(self) -> int:
        return 2 if self.fast_mode else self.max_pages_par_site


settings = Settings()