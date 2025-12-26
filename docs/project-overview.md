# Proteus-Scraper: Project Overview

Proteus-Scraper is a universal, self-healing data extraction platform designed to outlive fragile, selector-only scrapers. It treats scraping as a resilient data pipeline: you submit a URL and a schema, and the system chooses the right extraction strategy, validates the output, and stores both results and raw artifacts.

Core philosophy: Speed by default, AI by necessity.

## Executive Summary
Proteus-Scraper combines a fast, deterministic extraction layer with an AI-assisted recovery layer. It routes each job to the most appropriate engine (static fetch, browser rendering, or stealth/3rd-party) and uses structured validation to decide when LLM repair is needed. The system is modular, microservices-ready, and designed for high concurrency.

At its heart, Proteus is a distributed extraction platform that separates the Control Plane (API, orchestration, schemas) from the Data Plane (workers and engines). It uses Redis for queueing and Postgres for durable state and metadata, with optional S3 for raw captures.

## Core Goals
- Resilience: keep extractions working as sites evolve.
- Speed: selectors first, LLMs only when needed.
- Deterministic quality: strong schema validation and explicit data contracts.
- Operability: clear observability, replay, and recovery paths.
- Scale: multi-engine workers and independent scaling of API and scraping.

## Non-Goals
- General web crawling at internet scale (this is targeted extraction).
- Replacing BI/ETL systems downstream (Proteus feeds them).
- Unsafe or non-compliant data access.

## High-Level Architecture
Proteus follows a modular monolith that is microservices-ready. It can be deployed as one service during early stages, and then split into services as scale grows.

### Control Plane
- FastAPI REST API for job submission and status queries.
- Schema registry and validation rules.
- Dispatcher for routing and queue assignment.
- Durable job state tracking and metadata storage.

### Data Plane
- Engine workers for scraping and parsing.
- Hybrid parsing: selectors first, LLM fallback on validation failure.
- Storage of parsed output plus raw artifacts (HTML, screenshots, HAR).

## Data Flow
1) Ingestion: User submits a JSON job via REST API.
2) Validation: Schema and job contract are validated.
3) Queueing: Job enters a priority queue in Redis.
4) Dispatch: Dispatcher selects the engine based on URL complexity and risk.
5) Extraction: Engine fetches, renders, and parses data.
6) Recovery: If validation fails, LLM module repairs or infers data.
7) Storage: Parsed data stored in Postgres; raw artifacts stored in S3.
8) Status: Results and trace metadata available via API.

## Architecture Diagram (Mermaid)
```mermaid
graph TD
    User[User / API Client] -->|POST /submit| API[FastAPI Gateway]
    API -->|Push Job| Redis[(Redis Queue)]
    API -->|Read Status| DB[(Postgres DB)]

    subgraph Data Plane
        Dispatcher[Dispatcher Worker] -->|Pop Job| Redis
        Dispatcher -->|Route| Engine{Engine Selector}

        Engine -->|Static| Scrapy[FastEngine (Scrapy)]
        Engine -->|Dynamic| PW[BrowserEngine (Playwright)]
        Engine -->|Protected| Stealth[StealthEngine]

        Scrapy & PW & Stealth -->|Raw HTML| Parser[Hybrid Parser]

        Parser -->|1. Try Selector| Validator{Pydantic Check}
        Validator -->|Pass| Store[Storage Worker]
        Validator -->|Fail| LLM[LLM Fallback]
        LLM -->|Repair JSON| Validator
    end

    Store -->|Structured Data| DB
    Store -->|Artifacts| S3[S3 Bucket]
```

## Engine Routing
Proteus uses a decision model to select the fastest viable engine:

- FastEngine (HTTPX/Scrapy): Static pages and predictable HTML.
- BrowserEngine (Playwright): SPAs, JS-rendered content, or DOM hydration.
- StealthEngine (3rd-party APIs): Heavily protected targets or anti-bot traps.

Routing signals may include:
- Content-type headers and script density.
- Known domain heuristics and risk scores.
- Historical failure rates and ban rates.
- Cost and latency thresholds per tenant.

## Identity & Session Management
Proteus treats browser identity as a managed resource, separating "who is scraping" from "what is being scraped."

- The Cookie Jar: Encrypted session vault (disk or S3) for authenticated scraping without repeated logins.
- Fingerprint Pools: Distinct browser profiles (UA, viewport, WebGL) to avoid fingerprint linking.
- Rotation Strategy: Automatic identity rotation by usage count or failure rate.

## Hybrid Extraction and Recovery
1) Selector pass: CSS/XPath rules run first for speed.
2) Validation: Pydantic schema checks for type safety and required fields.
3) LLM fallback: On failure, Instructor + LLM generate structured outputs.
4) Revalidation: LLM output must pass the same schema checks.
5) Feedback loop (dynamic selectors): selectors are fetched from Postgres at runtime, not hardcoded in Python.
6) Auto-patching: when the LLM succeeds after a selector failure, a candidate selector is inferred, verified N times, and promoted to active.

## Storage Model
- Postgres: job state, metadata, extracted structured data.
- S3 (optional): raw HTML, screenshots, HAR traces, and logs.
- Redis: transient queues and scheduling.

## Reliability and Safety
- Retries with exponential backoff.
- Dead-letter queue for manual inspection.
- Per-domain rate limits and concurrency caps.
- Schema-driven validation to prevent silent corruption.

## Distributed Governance
To prevent bans at scale, Proteus enforces global policies via Redis.

- Global rate limiting: Token Bucket per domain across all workers.
- Circuit breakers: Trip on repeated 403s and pause domain traffic.
- Cost guardrails: Hard LLM budget per job to prevent runaway spend.

## Observability
- Structured logs (loguru).
- Metrics for throughput, latency, ban rate, and fallback rate.
- Tracing for end-to-end job lifecycle.

## Global Observability (Grafana Mission Control)
Proteus exports Prometheus metrics and visualizes them in Grafana dashboards.

- Success rate per domain (e.g., Amazon 98%, LinkedIn 40%).
- Ban rate spikes (403/429 anomalies).
- Proxy health by provider and pool.
- LLM cost rate (tokens or dollars per minute).
- Throughput (pages per minute) and queue depth.

## Testing & Simulation
- Network replay: HAR ingestion to test parsers without live targets.
- Mock server: Containerized target-practice site for safe validation.
- Dry-run mode: Execute pipeline while skipping DB writes or LLM calls.

## Security and Compliance
- Input validation to prevent SSRF and unsafe navigation.
- Optional robots.txt policy enforcement.
- Credential and secret isolation via environment variables.
- Proxy and identity rotation policy controls.

## Network Supremacy (Smart Egress Gateway)
Proteus decouples proxy rotation from code by routing all worker traffic through a dedicated forward proxy gateway.

- Provider fallback: Auto-switch between proxy providers when one fails.
- Protocol translation: Normalize HTTP, HTTPS, and SOCKS5 from a single gateway endpoint.
- TLS termination: Centralize TLS handling for consistent fingerprints across workers.
- Operational win: Change proxy strategy without touching scraping code.

## Behavioral Biometrics (Ghost Cursor)
Tier-4 anti-bot systems analyze interaction patterns, not just headers.

- Human-like mouse paths: Bezier-curve motion, micro-hesitations, and overshoot corrections.
- Drop-in API: Replace `page.click()` with `human_click()` for sensitive flows.
- Goal: Avoid behavior-based bot detection in protected UI steps.

## Vision and Local Intelligence (Ocular Module)
Local vision reduces external API cost and latency for image-based content.

- OCR: Tesseract or PaddleOCR for text-in-image extraction.
- Lightweight detection: Quantized YOLOv8 for simple visual challenges.
- Policy: Use local models by default, fall back to paid APIs only when needed.

## Data Lake and Time Travel
Proteus stores change history, not just current snapshots, to enable analytics.

- Diffing engine: Compare new scrape vs last known state.
- Versioned storage: Snapshot raw HTML with version tags in S3.
- Change tables: Track price_history or field deltas for longitudinal analysis.

## Directory Structure (Monolith)
```
proteus-scraper/
├── deploy/                  # Infrastructure configs
│   ├── Dockerfile.api       # For the REST API
│   ├── Dockerfile.worker    # For the Scrapy/Playwright workers
│   └── docker-compose.yml   # Local orchestration
├── docs/                    # Architecture + roadmap docs
├── migrations/              # Alembic migrations
├── scripts/                 # Helper scripts
├── src/
│   ├── api/                 # FastAPI application (control plane)
│   │   ├── main.py          # Entry point
│   │   ├── routes.py        # /submit, /status, /results
│   │   └── schemas.py       # Pydantic models for API requests
│   ├── core/                # Shared logic
│   │   ├── config.py        # Environment variables
│   │   ├── db.py            # Async Postgres connection
│   │   └── tasks.py         # ARQ (Redis) task definitions
│   └── scraper/             # Scrapy project (data plane)
│       ├── spiders/
│       │   └── proteus.py   # The "Universal" spider
│       ├── middlewares.py   # Stealth + proxy rotation
│       ├── pipelines.py     # Validation + DB storage
│       ├── settings.py      # Tuned for high concurrency
│       └── parsing.py       # Hybrid AI logic (selector + LLM)
├── tests/                   # Unit + integration tests
├── alembic.ini              # Alembic config
├── Makefile                 # Common dev commands
├── poetry.lock              # Locked dependencies
└── pyproject.toml           # Project + dependency config
```

## Tech Stack (2025 Standard)
Application Layer (Python):

- Frameworks: FastAPI, Scrapy, Scrapy-Playwright, Arq
- Data: Pydantic, SQLAlchemy (Async), Alembic
- AI/Parsing: Selectolax, Instructor, OpenAI SDK, Ultralytics (YOLO)

Infrastructure Layer (Ops):

- Orchestration: Docker Compose (Dev), Kubernetes + KEDA (Prod)
- Networking: Squid/Glider (Egress Gateway), Traefik (Ingress)
- Observability: Prometheus (Metrics), Grafana (Viz), Loki (Logs)
- Storage: PostgreSQL 15, Redis 7, MinIO/S3

## Job Contract (Example)
```json
{
  "job_id": "uuid",
  "url": "https://example.com/product/123",
  "schema_id": "product_v1",
  "priority": "high",
  "render": "auto",
  "engine_hint": "auto",
  "metadata": {
    "tenant": "acme",
    "tags": ["product", "price"]
  }
}
```

## Example Schema (Pydantic)
```json
{
  "name": "string",
  "price": "float",
  "currency": "string",
  "availability": "string",
  "url": "string"
}
```

## Deployment Options
- Single-node "God Mode" via docker-compose.
- Split services on Kubernetes with independent scaling of API and workers.
- Dedicated worker pools per engine type and tenant.

## Extension Points
- Add new spiders or parsing adapters.
- Custom routing logic per domain.
- Additional storage backends (BigQuery, Snowflake, etc).
- Domain-specific validation rules and post-processing.

## Roadmap Ideas
- Selector versioning with automatic promotion of LLM-generated rules.
- Cost-aware routing (budget caps per tenant).
- Active learning from failed extractions.
- Reproducible job runs with artifact snapshots.

## Summary
Proteus-Scraper is designed as an end-to-end extraction platform rather than a fragile scraping script. It prioritizes speed, resilience, and observability, combining deterministic parsing with AI-assisted recovery to keep data pipelines stable over time.
