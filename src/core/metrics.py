from __future__ import annotations

import logging
from urllib.parse import urlparse

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from core.config import settings

logger = logging.getLogger(__name__)

_metrics_started = False

JOBS_TOTAL = Counter(
    "proteus_jobs_total",
    "Total jobs by state, engine, and domain.",
    ["state", "engine", "domain"],
)
JOB_DURATION = Histogram(
    "proteus_job_duration_seconds",
    "Job duration in seconds.",
    ["engine", "domain"],
)
FAILURES_TOTAL = Counter(
    "proteus_failures_total",
    "Total failures by reason and domain.",
    ["reason", "domain"],
)
PROXY_ERRORS_TOTAL = Counter(
    "proteus_proxy_errors_total",
    "Total proxy errors by provider.",
    ["provider"],
)
LLM_TOKENS_TOTAL = Counter(
    "proteus_llm_tokens_total",
    "Total LLM tokens consumed by model and tenant.",
    ["model", "tenant"],
)
LLM_CALLS_TOTAL = Counter(
    "proteus_llm_calls_total",
    "Total LLM calls by model and tenant.",
    ["model", "tenant"],
)
QUEUE_DEPTH = Gauge(
    "proteus_queue_depth",
    "Queue depth by queue name.",
    ["queue"],
)


def start_metrics_server(port: int) -> None:
    if not settings.metrics_enabled:
        return
    global _metrics_started
    if _metrics_started:
        return
    try:
        start_http_server(port, addr=settings.metrics_host)
    except OSError as exc:
        logger.warning("metrics_server_failed: %s", exc)
        return
    _metrics_started = True
    logger.info("metrics_server_started port=%s", port)


def record_job_state(state: str, engine: str | None, url: str | None) -> None:
    if not settings.metrics_enabled:
        return
    JOBS_TOTAL.labels(
        state=_label(state, "unknown"),
        engine=_label(engine, "unknown"),
        domain=_domain_from_url(url),
    ).inc()


def record_job_duration(engine: str | None, url: str | None, seconds: float) -> None:
    if not settings.metrics_enabled:
        return
    JOB_DURATION.labels(
        engine=_label(engine, "unknown"),
        domain=_domain_from_url(url),
    ).observe(seconds)


def record_failure(reason: str | None, url: str | None) -> None:
    if not settings.metrics_enabled:
        return
    FAILURES_TOTAL.labels(
        reason=_label(reason, "unknown"),
        domain=_domain_from_url(url),
    ).inc()


def record_proxy_error(provider: str | None) -> None:
    if not settings.metrics_enabled:
        return
    PROXY_ERRORS_TOTAL.labels(provider=_label(provider, "unknown")).inc()


def record_llm_usage(model: str | None, tokens: int | None, tenant: str | None) -> None:
    if not settings.metrics_enabled:
        return
    model_label = _label(model, "unknown")
    tenant_label = _label(tenant, "default")
    LLM_CALLS_TOTAL.labels(model=model_label, tenant=tenant_label).inc()
    if tokens:
        LLM_TOKENS_TOTAL.labels(model=model_label, tenant=tenant_label).inc(tokens)


def record_queue_depth(queue: str, depth: int) -> None:
    if not settings.metrics_enabled:
        return
    QUEUE_DEPTH.labels(queue=_label(queue, "unknown")).set(depth)


def _label(value: str | None, fallback: str) -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return value or fallback


def _domain_from_url(url: str | None) -> str:
    if not url:
        return "unknown"
    try:
        host = urlparse(url).hostname
    except ValueError:
        host = None
    return host or "unknown"
