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
    selector_promotion_threshold: int = 3
    engine_queue: str = "engine:fast"
    browser_timeout_ms: int = 30000
    browser_wait_until: str = "networkidle"
    browser_wait_for_selector: str | None = None
    browser_wait_for_ms: int = 0
    browser_headless: bool = True
    browser_full_page: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
