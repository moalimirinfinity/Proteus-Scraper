# Proteus-Scraper: Development Plan

This plan translates `project-overview.md` and `ARCHITECTURE.md` into an executable roadmap with phases, deliverables, and acceptance criteria. It assumes the existing scaffold in the repository root and focuses on building a production-grade, multi-engine extraction platform.

## Guiding Principles
- Speed by default, AI by necessity.
- Selector-first parsing with strict schema validation.
- Global governance and cost controls for safe scale.
- Observability as a first-class feature.
- Configuration and selectors are database-driven, not hardcoded.

## Phase 0: Foundation and Developer Experience (Partial)
Goal: Make the repository runnable, testable, and consistent.

Deliverables:
- ✅ Poetry-based dependency management and lockfile.
- ❌ CI workflow that runs tests on push/PR.
- ✅ Makefile commands for common tasks (dev, stop, POETRY override).
- ✅ Base docs for architecture and overview.
- ✅ .env.example and config conventions (browser settings documented).
- ✅ SETUP.md quickstart with runnable examples.

Acceptance criteria:
- ❌ `make test` succeeds in CI (tests directory exists but is empty).
- ✅ `make up` boots local services with no manual edits.
- ✅ `make dev` boots infra, initializes DB, and starts API + workers.
- ✅ Docs describe how to submit a job and read results.

## Phase 1: Core Control Plane (API + State) ✅
Goal: Implement the API, job contract, and durable state machine.

Deliverables:
- ✅ FastAPI app with `/submit`, `/status/{job_id}`, `/results/{job_id}`.
- ✅ Pydantic schemas for jobs and results (includes Schema models).
- ✅ Postgres schema for `jobs`, `job_attempts`, `artifacts`, `selectors`, `selector_candidates`, `schemas`.
- ✅ Schema + selector CRUD endpoints (`/schemas`, `/schemas/{schema_id}/selectors`).
- ✅ Preview endpoint for immediate extraction (`/schemas/{schema_id}/preview`).
- ✅ Redis queues: priority + engine routing.
- ✅ ARQ tasks skeleton and dispatcher contract.

Acceptance criteria:
- ✅ Submitting a job creates a DB record and enqueues in Redis.
- ✅ Status endpoint reflects state transitions (queued -> running -> succeeded/failed).
- ✅ Results endpoint returns structured output and artifact links.
- ✅ Preview endpoint runs extraction and returns data + artifacts.

## Phase 2: Data Plane MVP (FastEngine) ✅
Goal: Get deterministic scraping working end-to-end for static pages.

Deliverables:
- ✅ Scrapy spider that fetches URLs from the queue.
- ✅ Parser that uses selectors from DB (no hardcoded selectors).
- ✅ List extraction with grouped selectors (`group_name` + `item_selector`).
- ✅ Attribute extraction for fields (e.g., `href`).
- ✅ Artifact capture: HTML stored to S3/MinIO and referenced in DB.
- ✅ Storage worker to persist validated output.

Acceptance criteria:
- ✅ Static target successfully extracted with schema validation.
- ✅ List page returns arrays of items with per-field validation.
- ✅ Artifacts uploaded and linked to job record.
- ✅ Errors captured in `job_attempts` with a reason code.

## Phase 3: BrowserEngine and Rendering ✅
Goal: Support JS-rendered targets using Playwright.

Deliverables:
- ✅ Playwright integration with proper browser contexts.
- ✅ Rendering policies (timeout, wait conditions, optional scroll steps).
- ✅ Capture screenshot and HAR for rendered sessions.

Acceptance criteria:
- ✅ SPA target returns validated data via BrowserEngine.
- ✅ HAR and screenshot artifacts stored for successful runs.
- ✅ Scroll settings are configurable via environment.

## Phase 3.1: List Pagination/Virtualization ✅
Goal: Capture long, virtualized lists beyond the initial viewport.

Deliverables:
- ✅ Scroll-and-collect aggregation in BrowserEngine (merge items per scroll step, de-dupe, max-items cap).
- ✅ Pagination strategies (next-link detection + page parameter templates).
- ✅ URL normalization for attribute selectors (relative -> absolute).

Acceptance criteria:
- ✅ List pages yield more than the initial viewport without custom code.
- ✅ Items are de-duplicated and stable across scroll steps.
- ✅ Extracted item URLs are absolute and followable.

## Phase 4: Hybrid Parsing and LLM Recovery ✅
Goal: Add AI-assisted recovery to reduce selector fragility.

Deliverables:
- ✅ Instructor-based LLM output constrained by schema.
- ✅ Revalidation pipeline with explicit failure reasons.
- ✅ Selector candidate generation on LLM success.
- ✅ Selector promotion policy (N successes -> active).
- ✅ List-aware LLM extraction for grouped selectors.

Acceptance criteria:
- ✅ Selector failure triggers LLM fallback and revalidation.
- ✅ Candidates recorded and promoted after verification threshold.
- ✅ List-page recovery records candidates with group/item/attribute context.

## Phase 5: Governance and Cost Controls ✅
Goal: Centralize global safety policies for distributed workers.

Deliverables:
- ✅ Redis token bucket rate limits per domain.
- ✅ Circuit breaker logic for ban spikes (403/429).
- ✅ LLM budget guardrails per job and per tenant.

Acceptance criteria:
- ✅ Requests across multiple workers respect a global rate.
- ✅ Breaker trips and pauses domains after threshold.
- ✅ LLM calls stop when budget exceeded.

## Phase 6: Identity and Session Management ✅
Goal: Treat identity as a managed resource.

Deliverables:
- ✅ Cookie jar storage (encrypted at rest).
- ✅ Fingerprint pool definitions per tenant.
- ✅ Identity rotation based on usage and failure.
- ✅ Identity CRUD API for managing fingerprints + cookies.

Acceptance criteria:
- ✅ Authenticated scraping works without repeated login.
- ✅ Identity rotation reduces repeated bans on target.

## Phase 7: Observability and Mission Control ✅
Goal: Full visibility across extraction and infrastructure.

Deliverables:
- ✅ Prometheus metrics for jobs, failures, latency, LLM costs.
- ✅ Grafana dashboards for success rate and ban spikes.
- ✅ Log aggregation via Loki.

Acceptance criteria:
- ✅ Dashboards show domain success rate and proxy health.
- ✅ Alerts trigger on ban spikes or budget overruns.

## Phase 7.1: Control Panel (Web UI) ✅
Goal: Make the system usable without direct DB edits or raw API calls.

Deliverables:
- ✅ Web dashboard to submit a URL and run preview jobs.
- ✅ Visual selector builder to generate schema JSON (click + highlight).
- ✅ "Quarantine" view for broken selectors and LLM candidates.

Acceptance criteria:
- ✅ Non-technical users can create a schema without SQL.
- ✅ Preview results show data + artifacts in the UI.
- ✅ Quarantine view allows promoting or rejecting candidates.

## Phase 8: Network Infrastructure
Goal: Decouple proxy logic from code.

Deliverables:
- Smart egress gateway (Squid/Glider) with provider fallback.
- Ingress routing via Traefik for API and web endpoints.
- Configurable proxy policies in the DB.

Acceptance criteria:
- Workers route traffic through the gateway by default.
- Proxy provider switching does not require code changes.

## Phase 8.1: Extensibility and Plugin Interface
Goal: Allow new capabilities without modifying core code.

Deliverables:
- ❌ Plugin/middleware interface for request/response hooks.
- ❌ Plugin discovery and safe loading from `plugins/`.
- ❌ Reference plugins (e.g., PDF parser, custom headers).

Acceptance criteria:
- ❌ Custom logic can be added via a plugin without touching core modules.
- ❌ Plugins can be enabled per schema or tenant.

## Phase 9: Human-Like Interaction and Vision
Goal: Reduce bot detection and external API cost.

Deliverables:
- Ghost Cursor integration for human-like mouse movement.
- Local OCR pipeline (Tesseract/PaddleOCR).
- Lightweight object detection (YOLO) for simple challenges.

Acceptance criteria:
- Protected UI flows succeed more often with human-like interaction.
- OCR handles image-encoded data without external APIs.

## Phase 9.1: Solver Pipeline (CAPTCHA and Challenges)
Goal: Provide a standard solver interface for hard challenges (reCAPTCHA/Turnstile).

Deliverables:
- ❌ Challenge detection signals and pause/resume flow in BrowserEngine.
- ❌ Solver interface (external API or human-in-the-loop).
- ❌ Token injection and session resume in the browser context.
- ❌ Solver cost/latency tracking and timeouts.

Acceptance criteria:
- ❌ Challenges can be routed to a configured solver.
- ❌ Successful solves resume the job without a restart.
- ❌ Failures are recorded with explicit reason codes.

## Phase 10: Data Lake and Time-Travel Storage
Goal: Turn scraping into longitudinal intelligence.

Deliverables:
- Diffing engine for state changes.
- Versioned raw artifact storage in S3.
- History tables (e.g., `price_history`).

Acceptance criteria:
- No duplicate records for unchanged results.
- Versioned snapshots accessible by job/time.

## Phase 11: Testing and Simulation
Goal: Validate safely without getting banned.

Deliverables:
- HAR replay mode and dry-run pipeline.
- Mock target service for integration tests.
- Golden fixtures for regression detection.

Acceptance criteria:
- Integration tests run without hitting external targets.
- Regression tests catch selector drift or parsing errors.

## Phase 12: Release Readiness (Partial)
Goal: Make the project consumable by the public.

Deliverables:
- ❌ Contributor guide, security policy, and changelog.
- ✅ Example schemas, jobs, and sample outputs (seed_data includes list example).
- ✅ Docker Compose for single-node demo (docker-compose.yml exists).
- ❌ Kubernetes manifests or Helm chart for production.
- ✅ README with quickstart and examples.
- ✅ SETUP.md with step-by-step local run instructions.

Acceptance criteria:
- ✅ New contributor can run the stack from scratch (README provides instructions).
- ✅ First-time users can submit a job and get results (README has curl examples).

## Cross-Cutting Workstreams
- **Schema Registry**: ✅ Schema registry (Schema model exists), ✅ selector sets (grouped + attribute selectors), ✅ CRUD + preview endpoint, ❌ migration path (Alembic configured but no migrations), ✅ validation rules (Pydantic schemas).
- **Config Service**: ❌ Domain policies, ✅ selector sets (database-driven), ❌ routing rules (basic engine selection only).
- **Multi-Tenancy**: ✅ Per-tenant LLM budgets, ❌ per-tenant rate limits, ✅ identity pools per tenant, ❌ tenant isolation (row-level or schema split).
- **Security**: ❌ SSRF protection, ❌ allow/deny lists, ❌ audit logging (basic logging only).
- **Control Panel**: ✅ Preview UI, ✅ selector builder, ✅ selector quarantine workflow.
- **Extensibility**: ❌ Plugin interface, ❌ plugin sandboxing, ❌ plugin registry.
- **Solver Pipeline**: ❌ Challenge detection, ❌ solver adapters, ❌ resume flow.

## Dependencies and Order
- Phases 1-2 are prerequisites for any engine or AI work.
- Phase 4 depends on Phase 2 parsing and schema validation.
- Phases 5-6 (governance + identity) must be in place before scaling.
- Phase 7 (observability) should be incremental from Phase 1 onward.

## Success Metrics
- Extraction success rate > 95% on known domains.
- LLM fallback rate < 20% for stable targets.
- Ban rate < 2% per domain per day.
- Mean time to recovery from selector drift < 24 hours.
- Cost per successful extraction within budget.

## Risks and Mitigations
- **Selector drift**: mitigate with candidate promotion and rollback.
- **Cost overruns**: enforce budgets and fallback caps.
- **Ban waves**: enforce governance and rotate identities.
- **Data corruption**: strict schema validation + artifact review.

## Suggested First Milestone (MVP)
- ✅ FastAPI submit/status/results.
- ✅ Postgres job state machine.
- ✅ Redis queues and dispatcher skeleton.
- ✅ FastEngine scraping + selector registry.
- ✅ Schema/selector CRUD + preview endpoint.
- ✅ List extraction + attribute selectors.
- ✅ BrowserEngine with Playwright.
- ✅ List pagination/scroll aggregation.
- ✅ LLM recovery with selector candidate promotion.
- ✅ Artifact storage to MinIO/S3.
- ✅ Governance (rate limits + circuit breaker + LLM budgets).
- ✅ Identity management (encrypted cookies + fingerprints).
- ✅ Observability stack (Prometheus/Grafana/Loki) with baseline alerts.
