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
    identity_failure_decay_per_hour: float = 0.25
    identity_binding_ttl_sec: int = 3600
    llm_job_max_calls: int = 1
    llm_job_window_sec: int = 3600
    llm_tenant_max_calls: int = 1000
    llm_tenant_window_sec: int = 86400
    selector_promotion_threshold: int = 3
    engine_queue: str = "engine:fast"
    router_max_depth: int = 2
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
    browser_humanize: bool = False
    browser_humanize_moves: int = 3
    browser_humanize_min_delay_ms: int = 25
    browser_humanize_max_delay_ms: int = 120
    browser_humanize_pause_ms: int = 150

    fetch_timeout_ms: int = 20000
    fetch_max_bytes: int = 0
    fetch_user_agent: str = "ProteusFetcher/1.0"
    fetch_curl_impersonate: str | None = None
    fetch_retries: int = 2
    fetch_backoff_ms: int = 250
    fetch_backoff_max_ms: int = 2000
    fetch_pool_max_connections: int = 100
    fetch_pool_max_keepalive: int = 20

    metrics_enabled: bool = True
    metrics_host: str = "0.0.0.0"
    metrics_port_dispatcher: int = 8002
    metrics_port_worker: int = 8003
    preview_html_max_chars: int = 500000

    auth_enabled: bool = False
    auth_api_tokens: str | None = None
    auth_jwt_secret: str | None = None
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str | None = None
    auth_jwt_leeway_sec: int = 30
    auth_protect_metrics: bool = False

    proxy_default_mode: str = "gateway"
    proxy_gateway_url: str | None = None
    stealth_enabled: bool = True
    stealth_allowed_domains: str | None = None
    external_enabled: bool = False
    external_provider: str = "scrapfly"
    external_provider_url: str | None = None
    external_api_key: str | None = None
    external_allowlist_domains: str | None = None
    external_timeout_ms: int = 30000
    external_max_calls_per_tenant: int = 100
    external_max_cost_per_tenant: float = 0.0
    external_window_sec: int = 86400
    external_cost_per_call: float = 0.0
    external_breaker_threshold: int = 3
    external_breaker_window_sec: int = 60
    external_breaker_cooldown_sec: int = 300

    plugins_dir: str = "plugins"
    plugins_allowlist: str | None = None
    plugins_default: str | None = None

    vision_ocr_enabled: bool = False
    vision_ocr_provider: str = "tesseract"
    vision_ocr_language: str = "eng"
    vision_yolo_enabled: bool = False
    vision_yolo_model: str = "yolov8n.pt"
    vision_yolo_classes: str | None = None
    vision_yolo_confidence: float = 0.25

    rate_limit_capacity: int = 0
    rate_limit_refill_per_sec: float = 0.0
    rate_limit_max_wait_ms: int = 0
    circuit_breaker_threshold: int = 5
    circuit_breaker_window_sec: int = 60
    circuit_breaker_cooldown_sec: int = 300

    ssrf_allowlist_domains: str | None = None
    ssrf_denylist_domains: str | None = None
    ssrf_allow_private_ips: bool = False

    ui_rate_limit_preview_per_min: int = 30
    ui_rate_limit_schema_per_min: int = 60
    ui_rate_limit_window_sec: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
