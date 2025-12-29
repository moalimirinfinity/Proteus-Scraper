# Proteus-Scraper: Development Plan

This plan translates `project-overview.md` and `ARCHITECTURE.md` into an executable roadmap with phases, deliverables, and acceptance criteria. Status reflects the current codebase.

## Status Legend
- ✅ Done
- 🟡 Partial
- ❌ Planned

## Guiding Principles
- Speed by default, AI by necessity.
- Selector-first parsing with strict schema validation.
- Global governance and cost controls for safe scale.
- Observability as a first-class feature.
- Configuration and selectors are database-driven, not hardcoded.

## Phase 0: Foundation and Developer Experience ✅
Goal: Make the repository runnable, testable, and consistent.

Deliverables:
- ✅ Poetry dependency management and lockfile.
- ✅ CI workflow that runs tests on push/PR and builds API/worker images.
- ✅ Makefile commands for common tasks (dev, stop, POETRY override).
- ✅ Base docs for architecture and overview.
- ✅ .env.example and config conventions.
- ✅ SETUP.md quickstart with runnable examples.

Acceptance criteria:
- ✅ CI runs pytest on push/PR and builds container images.
- ✅ `make up` boots local services with no manual edits.
- ✅ `make dev` boots infra, initializes DB, and starts API + workers.
- ✅ Docs describe how to submit a job and read results.

## Phase 1: Core Control Plane (API + State) ✅
Goal: Implement the API, job contract, and durable state machine.

Deliverables:
- ✅ FastAPI app with `/submit`, `/status/{job_id}`, `/results/{job_id}`.
- ✅ Pydantic schemas for jobs and results.
- ✅ Postgres schema for jobs, attempts, artifacts, selectors, candidates, schemas.
- ✅ Schema + selector CRUD endpoints.
- ✅ Preview endpoint for immediate extraction (`/schemas/{schema_id}/preview`).
- ✅ Preview HTML endpoint (`/preview/html`).
- ✅ Redis queues: priority + engine routing.
- ✅ ARQ tasks skeleton and dispatcher contract.

Acceptance criteria:
- ✅ Submitting a job creates a DB record and enqueues in Redis.
- ✅ Status endpoint reflects state transitions.
- ✅ Results endpoint returns structured output and artifact links.
- ✅ Preview endpoints return data or HTML + artifacts.

## Phase 2: Data Plane MVP (FastEngine) ✅
Goal: Deterministic scraping for static pages using the modern async fetcher.

Deliverables:
- ✅ Async fetcher (httpx) with proxy + identity support.
- ✅ Optional stealth fetcher (curl_cffi) for TLS/JA3-sensitive targets.
- ✅ Unified fetcher used by fast engine and preview HTML path.
- ✅ Parser that uses selectors from DB (no hardcoded selectors).
- ✅ List extraction with grouped selectors (`group_name` + `item_selector`).
- ✅ Attribute extraction for fields (e.g., `href`).
- ✅ XPath support via Parsel (`xpath:` selectors).
- ✅ Artifact capture: HTML stored to S3/MinIO and referenced in DB.

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

## Phase 5.1: Adaptive Engine Router ✅
Goal: Escalate across tiers when blocked while preserving auditability.

Deliverables:
- ✅ Detector for captcha/blocked/403/429/empty selectors (headers/URL/title/script markers).
- ✅ Escalation re-queues with reason codes and max depth (`ROUTER_MAX_DEPTH`).
- ✅ Analyzer runs pre-parse and post-parse (empty data with 200 is a signal).
- ✅ Detector reason recorded in `job_attempts`.

Acceptance criteria:
- ✅ Auto-escalation works without infinite loops.
- ✅ Blocked responses move to the next tier with reason codes.

## Phase 5.2: External API Tier ✅
Goal: Provide a gated Tier 4 fallback for high-value targets.

Deliverables:
- ✅ Provider interface (Scrapfly/ZenRows) with allowlist + budget gate.
- ✅ Usage metrics and cost tracking in Prometheus.
- ✅ Separate queue (`engine:external`) and per-tenant caps to prevent runaway costs.
- ✅ Circuit breaker for vendor failures and per-domain cooling.

Acceptance criteria:
- ✅ External calls are measurable and controlled.
- ✅ Budget/allowlist gates prevent unauthorized usage.

## Phase 6: Identity and Session Management ✅
Goal: Treat identity as a managed resource.

Deliverables:
- ✅ Sticky identity per domain (cookies + proxy/IP binding).
- ✅ Cookie jar storage (encrypted at rest).
- ✅ storageState/localStorage support for browser contexts.
- ✅ Identity health score with decay and failure-based rotation.
- ✅ Fingerprint pool definitions per tenant.
- ✅ Identity CRUD API for managing fingerprints + cookies.
- ✅ Per-domain identity bindings with TTLs to avoid cross-domain leakage.

Acceptance criteria:
- ✅ Authenticated scraping works without repeated login.
- ✅ Identity reuse is consistent per domain; rotations occur after failures.
- ✅ Stored cookies/storage state are reused by the browser engine.

## Phase 6.1: Security and Access Control ✅
Goal: Protect the API and UI for multi-tenant usage.

Deliverables:
- ✅ SSRF protections with allow/deny lists and private IP blocking.
- ✅ API + UI auth (token/JWT) with tenant scoping.
- ✅ CSRF protection for cookie-authenticated requests.
- ✅ Preview/artifact endpoints enforce auth + tenant access checks.

Acceptance criteria:
- ✅ Unauthorized preview/artifact requests return 401.
- ✅ Tenant mismatch returns 403.
- ✅ SSRF blocks private IPs by default.

## Phase 7: Observability and Mission Control ✅
Goal: Full visibility across extraction and infrastructure.

Deliverables:
- ✅ Prometheus metrics for jobs, failures, latency, LLM costs, detector signals, escalations, engine mix, external API usage.
- ✅ Grafana dashboards for tier mix, success rate, ban spikes, and budget usage.
- ✅ Log aggregation via Loki.
- ✅ Stealth/external worker targets included in Prometheus scrapes.

Acceptance criteria:
- ✅ Dashboards show tier mix and failure causes.
- ✅ Alerts trigger on ban spikes or budget overruns.

## Phase 7.1: Control Panel Hardening ✅
Goal: Make the system usable and safe for multi-tenant usage.

Deliverables:
- ✅ Web dashboard to submit a URL and run preview jobs.
- ✅ Visual selector builder to generate schema JSON (click + highlight).
- ✅ "Quarantine" view for broken selectors and LLM candidates.
- ✅ Auth gate + CSRF protection for UI actions.
- ✅ Preview sandboxing (CSP + iframe sandbox) and rate limits.

Acceptance criteria:
- ✅ Non-technical users can create a schema without SQL.
- ✅ Preview results show data + artifacts in the UI.
- ✅ UI actions are rate-limited and require auth/CSRF.
- ✅ Preview sandbox prevents script execution.
- ✅ Quarantine view allows promoting or rejecting candidates.

## Phase 8: Network Infrastructure ✅
Goal: Decouple proxy logic from code.

Deliverables:
- ✅ Smart egress gateway (Squid/Glider) with provider fallback.
- ✅ Ingress routing via Traefik for API and web endpoints.
- ✅ Configurable proxy policies in the DB.

Acceptance criteria:
- ✅ Workers route traffic through the gateway by default.
- ✅ Proxy provider switching does not require code changes.

## Phase 8.1: Extensibility and Plugin Interface (✅)
Goal: Allow new capabilities without modifying core code.

Deliverables:
- ✅ Plugin/middleware interface for request/response hooks.
- ✅ Plugin discovery and safe loading from `plugins/`.
- ✅ Reference plugins (PDF parser, custom headers, payload transforms).

Acceptance criteria:
- ✅ Custom logic can be added via a plugin without touching core modules.
- ✅ Plugins can be enabled per schema or tenant.

## Phase 9: Human-Like Interaction and Vision (✅)
Goal: Reduce bot detection and external API cost.

Deliverables:
- ✅ Ghost Cursor integration for human-like mouse movement.
- ✅ Local OCR pipeline (Tesseract/PaddleOCR).
- ✅ Lightweight object detection (YOLO) for simple challenges.

Acceptance criteria:
- ✅ Protected UI flows succeed more often with human-like interaction.
- ✅ OCR handles image-encoded data without external APIs.

## Phase 9.1: Solver Pipeline (CAPTCHA and Challenges) (❌)
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

## Phase 10: Data Lake and Time-Travel Storage (❌)
Goal: Turn scraping into longitudinal intelligence.

Deliverables:
- ❌ Diffing engine for state changes.
- ❌ Versioned raw artifact storage in S3.
- ❌ History tables (e.g., `price_history`).

Acceptance criteria:
- ❌ No duplicate records for unchanged results.
- ❌ Versioned snapshots accessible by job/time.

## Phase 11: Testing and Simulation (🟡)
Goal: Validate safely without getting banned.

Deliverables:
- ❌ HAR replay mode and dry-run pipeline.
- ✅ Mock target service for integration tests.
- ✅ Golden fixtures for regression detection.
- ✅ Integration tests for parsing, escalation, and LLM recovery.

Acceptance criteria:
- ✅ Integration tests run without hitting external targets.
- 🟡 Regression tests catch selector drift or parsing errors (fixtures + integration tests in place).

## Phase 12: Release Readiness (🟡)
Goal: Make the project consumable by the public.

Deliverables:
- ❌ Contributor guide, security policy, and changelog.
- ✅ CI workflow for tests and container builds.
- ✅ Example schemas, jobs, and sample outputs.
- ✅ Docker Compose for single-node demo.
- ❌ Kubernetes manifests or Helm chart for production.
- ✅ README with quickstart and examples.
- ✅ SETUP.md with step-by-step local run instructions.

Acceptance criteria:
- ✅ New contributor can run the stack from scratch.
- ✅ First-time users can submit a job and get results.

## Cross-Cutting Workstreams
- **Schema Registry**: ✅ selectors, ✅ CRUD + preview, 🟡 schema versioning/migration path, ✅ validation rules.
- **Fetcher Stack**: ✅ httpx fetcher, ✅ optional curl_cffi stealth, ✅ shared preview path.
- **Routing & Policy**: ✅ adaptive routing + escalation policies, ✅ external tier gating.
- **Multi-Tenancy**: ✅ per-tenant LLM budgets, ✅ per-tenant external caps, ❌ per-tenant rate limits, ✅ identity pools, 🟡 tenant isolation (auth scoping only).
- **Security**: ✅ SSRF protection, ✅ allow/deny lists, ✅ auth + tenant scoping, ❌ audit logging.
- **Control Panel**: ✅ preview UI, ✅ selector builder, ✅ candidate quarantine, ✅ auth/CSRF, ✅ rate limits, ✅ preview sandboxing.
- **Observability**: ✅ engine mix + detector signals, ✅ external API metrics.
- **Extensibility**: ✅ plugin interface, ❌ sandboxing, ❌ registry.
- **Solver Pipeline**: ❌ challenge detection, ❌ solver adapters, ❌ resume flow.

## Dependencies and Order
- Phases 1-2 are prerequisites for any engine or AI work.
- Phase 4 depends on Phase 2 parsing and schema validation.
- Phases 5-6 (governance + identity) must be in place before scaling.
- Phases 5.1-5.2 (adaptive router + external tier) depend on Phase 2 and governance.
- Phase 6.1 (security) should precede UI hardening and external exposure.
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
- ✅ FastEngine fetcher + selector registry.
- ✅ Schema/selector CRUD + preview endpoints.
- ✅ List extraction + attribute selectors + XPath support.
- ✅ BrowserEngine with Playwright.
- ✅ List pagination/scroll aggregation.
- ✅ LLM recovery with selector candidate promotion.
- ✅ Artifact storage to MinIO/S3.
- ✅ Governance (rate limits + circuit breaker + LLM budgets).
- ✅ Adaptive engine router (detector + escalation).
- ✅ External API tier (allowlist + budget gated).
- ✅ Identity management (encrypted cookies + fingerprints).
- ✅ Security (SSRF + auth/tenant scoping).
- ✅ Observability stack (Prometheus/Grafana/Loki) with baseline alerts.
- ✅ Control Panel (preview, selector builder, quarantine).
- ✅ Control Panel hardening (auth/CSRF + rate limits).
