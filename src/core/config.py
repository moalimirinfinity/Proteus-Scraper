from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: str = "development"
    log_level: str = "info"

    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/proteus"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None

    openai_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 800
    llm_temperature: float = 0.2
    llm_timeout_ms: int = 30000
    llm_max_html_chars: int = 12000
    identity_encryption_key: str | None = None
    identity_failure_threshold: int = 3
    llm_job_max_calls: int = 1
    llm_job_window_sec: int = 3600
    llm_tenant_max_calls: int = 1000
    llm_tenant_window_sec: int = 86400
    selector_promotion_threshold: int = 3
    engine_queue: str = "engine:fast"
    browser_timeout_ms: int = 30000
    browser_wait_until: str = "networkidle"
    browser_wait_for_selector: str | None = None
    browser_wait_for_ms: int = 0
    browser_scroll_steps: int = 0
    browser_scroll_delay_ms: int = 0
    browser_scroll_container_selector: str | None = None
    browser_collect_max_items: int = 0
    browser_pagination_max_pages: int = 1
    browser_pagination_next_selector: str | None = None
    browser_pagination_param: str | None = None
    browser_pagination_start: int = 1
    browser_pagination_step: int = 1
    browser_pagination_template: str | None = None
    browser_headless: bool = True
    browser_full_page: bool = True

    metrics_enabled: bool = True
    metrics_host: str = "0.0.0.0"
    metrics_port_dispatcher: int = 8002
    metrics_port_worker: int = 8003
    preview_html_max_chars: int = 500000

    rate_limit_capacity: int = 0
    rate_limit_refill_per_sec: float = 0.0
    rate_limit_max_wait_ms: int = 0
    circuit_breaker_threshold: int = 5
    circuit_breaker_window_sec: int = 60
    circuit_breaker_cooldown_sec: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
