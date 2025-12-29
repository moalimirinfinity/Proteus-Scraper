# Proteus-Scraper: Project Overview

Proteus-Scraper is a schema-driven extraction platform that combines fast HTTP fetching, browser rendering, and LLM recovery to keep data pipelines stable as sites evolve. You submit a URL and a schema; Proteus selects an engine, validates results, and stores both structured data and raw artifacts.

Core philosophy: speed by default, AI only when needed.

## What You Can Do Today
- Submit jobs and fetch status/results via API.
- Preview any URL with the fast fetcher, browser renderer, or gated external tier.
- Define schemas and selectors in the database and test them immediately.
- Extract list pages with grouped selectors and attribute fields.
- Use the Control Panel UI to preview, build selectors, and review candidates (auth + CSRF protected).
- Enforce global governance (rate limits, circuit breakers, LLM + external budgets).
- Rotate identities (cookies + fingerprints) and route traffic via proxy policies.
- Escalate across tiers automatically when detectors see blocks.
- Enable human-like browser behavior and local OCR/vision signals when needed.

## How It Works (Happy Path)
1) Submit job -> API validates and persists the job.
2) Dispatcher routes to engine queue (fast, stealth, browser, external).
3) Engine fetches HTML (httpx, curl_cffi, Playwright, or external provider).
4) Detector analyzes response; blocked responses can escalate to a higher tier.
5) Parser applies selectors and validates the schema.
6) If validation fails, LLM recovery attempts repair and suggests selectors.
7) Results and artifacts are saved; job status updates in Postgres.

## Engines
- FastEngine: async HTTP fetcher (httpx) for static HTML.
- BrowserEngine: Playwright for JS-rendered targets.
- StealthEngine: curl_cffi-backed fetcher for TLS/JA3-sensitive targets.

## Target Engine Escalation (Standard)
- Tier 1: httpx (default) for clean/static targets.
- Tier 2: curl_cffi for TLS/JA3-sensitive targets.
- Tier 3: Playwright for JS-rendered or heavily dynamic pages.
- Tier 4: External scraping API for hard blocks (budget + allowlist gated).
- Escalation is driven by a detector (captcha markers, 403/429, blocked HTML, OCR/vision signals).
- Escalation records reason codes in `job_attempts` and respects max depth.
- Identities stay sticky per domain until they burn, then rotate.

## Selectors and Schemas
- Selectors live in Postgres; no code changes for new targets.
- Grouped selectors support list extraction.
- Attribute fields (href/src/data-*) capture links.
- XPath is supported via Parsel when selectors are prefixed with `xpath:`.

## Recovery and Self-Healing
- LLM recovery runs only after selector validation fails.
- Candidate selectors are recorded and promoted after repeated success.
- Failures are tagged with explicit reason codes for debugging.

## Governance and Identity
- Global per-domain rate limits and circuit breakers.
- LLM budget caps per job and per tenant.
- External API budgets per tenant with allowlist gating.
- Identity pools (fingerprint + encrypted cookies/storage state) rotate by usage/failure.
- Proxy policies route traffic per domain, with gateway fallback.

## Observability and Control Panel
- Prometheus metrics + Grafana dashboards.
- Loki log aggregation for debug traces.
- Control Panel UI for preview, selector building, and candidate review.
- Metrics include detector signals, escalations, engine mix, and external API usage.

## Deployment Options
- Local dev: Docker Compose + Makefile.
- Single-node demo: API + workers + services.
- Scale-out: separate worker pools per engine.

## Extension Points
- Plugin interface for request/response/parse hooks loaded from `plugins/`.
- Solver pipeline for CAPTCHA and challenge flows.
- Domain-specific parsers (PDF, JSON, feeds).

## Directory Structure (Current)
```
proteus-scraper/
├── deploy/                  # Infrastructure configs
│   ├── Dockerfile.api       # REST API
│   ├── Dockerfile.worker    # Worker image (fetcher + Playwright)
│   └── docker-compose.yml   # Local orchestration
├── docs/                    # Architecture + roadmap docs
├── plugins/                 # Request/response/parse plugins
├── migrations/              # Alembic migrations
├── scripts/                 # Helper scripts
├── src/
│   ├── api/                 # FastAPI application (control plane)
│   ├── core/                # Shared logic (db, config, governance)
│   └── scraper/             # Fetcher + parser (data plane)
│       ├── fetcher.py       # HTTP fetch layer (httpx/curl_cffi)
│       ├── detector.py      # Block detection + escalation signals
│       └── parsing.py       # Hybrid parsing (selectors + LLM)
├── tests/                   # Unit + integration tests
├── alembic.ini              # Alembic config
├── Makefile                 # Common dev commands
├── poetry.lock              # Locked dependencies
└── pyproject.toml           # Project + dependency config
```

## Tech Stack (2025 Standard)
Application Layer:
- FastAPI, httpx, curl_cffi (optional), Playwright, Arq
- Pydantic, SQLAlchemy (Async), Alembic
- Selectolax, Parsel, Instructor, OpenAI SDK

Infrastructure Layer:
- Docker Compose (dev), Kubernetes + KEDA (prod)
- Traefik (ingress), Glider/Squid (egress)
- Prometheus, Grafana, Loki
- Postgres, Redis, MinIO/S3

## Job Contract (Example)
```json
{
  "job_id": "uuid",
  "url": "https://example.com/product/123",
  "schema_id": "product_v1",
  "priority": "high",
  "metadata": {
    "tenant": "acme",
    "tags": ["product", "price"]
  }
}
```

## Summary
Proteus-Scraper is designed as a resilient extraction platform rather than a fragile script. It prioritizes fast deterministic parsing, selective AI recovery, and operational control so teams can scale reliably without constant scraper rewrites.
