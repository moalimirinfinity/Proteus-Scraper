# Proteus-Scraper: Development Plan

This plan translates `project-overview.md` and `ARCHITECTURE.md` into an executable roadmap with phases, deliverables, and acceptance criteria. It assumes the existing scaffold in the repository root and focuses on building a production-grade, multi-engine extraction platform.

## Guiding Principles
- Speed by default, AI by necessity.
- Selector-first parsing with strict schema validation.
- Global governance and cost controls for safe scale.
- Observability as a first-class feature.
- Configuration and selectors are database-driven, not hardcoded.

## Phase 0: Foundation and Developer Experience
Goal: Make the repository runnable, testable, and consistent.

Deliverables:
- Poetry-based dependency management and lockfile.
- CI workflow that runs tests on push/PR.
- Makefile commands for common tasks.
- Base docs for architecture and overview.
- .env.example and config conventions.

Acceptance criteria:
- `make test` succeeds in CI.
- `make up` boots local services with no manual edits.
- Docs describe how to submit a job and read results.

## Phase 1: Core Control Plane (API + State)
Goal: Implement the API, job contract, and durable state machine.

Deliverables:
- FastAPI app with `/submit`, `/status/{job_id}`, `/results/{job_id}`.
- Pydantic schemas for jobs and results.
- Postgres schema for `jobs`, `job_attempts`, `artifacts`.
- Redis queues: priority + engine routing.
- ARQ tasks skeleton and dispatcher contract.

Acceptance criteria:
- Submitting a job creates a DB record and enqueues in Redis.
- Status endpoint reflects state transitions (queued -> running -> done).
- Results endpoint returns structured output and artifact links.

## Phase 2: Data Plane MVP (FastEngine)
Goal: Get deterministic scraping working end-to-end for static pages.

Deliverables:
- Scrapy spider that fetches URLs from the queue.
- Parser that uses selectors from DB (no hardcoded selectors).
- Artifact capture: HTML stored to S3/MinIO and referenced in DB.
- Storage worker to persist validated output.

Acceptance criteria:
- Static target successfully extracted with schema validation.
- Artifacts uploaded and linked to job record.
- Errors captured in `job_attempts` with a reason code.

## Phase 3: BrowserEngine and Rendering
Goal: Support JS-rendered targets using Playwright.

Deliverables:
- Playwright integration with proper browser contexts.
- Rendering policies (timeout, wait conditions).
- Capture screenshot and HAR for rendered sessions.

Acceptance criteria:
- SPA target returns validated data via BrowserEngine.
- HAR and screenshot artifacts stored for successful runs.

## Phase 4: Hybrid Parsing and LLM Recovery
Goal: Add AI-assisted recovery to reduce selector fragility.

Deliverables:
- Instructor-based LLM output constrained by schema.
- Revalidation pipeline with explicit failure reasons.
- Selector candidate generation on LLM success.
- Selector promotion policy (N successes -> active).

Acceptance criteria:
- Selector failure triggers LLM fallback and revalidation.
- Candidates recorded and promoted after verification threshold.

## Phase 5: Governance and Cost Controls
Goal: Centralize global safety policies for distributed workers.

Deliverables:
- Redis token bucket rate limits per domain.
- Circuit breaker logic for ban spikes (403/429).
- LLM budget guardrails per job and per tenant.

Acceptance criteria:
- Requests across multiple workers respect a global rate.
- Breaker trips and pauses domains after threshold.
- LLM calls stop when budget exceeded.

## Phase 6: Identity and Session Management
Goal: Treat identity as a managed resource.

Deliverables:
- Cookie jar storage (encrypted at rest).
- Fingerprint pool definitions per tenant.
- Identity rotation based on usage and failure.

Acceptance criteria:
- Authenticated scraping works without repeated login.
- Identity rotation reduces repeated bans on target.

## Phase 7: Observability and Mission Control
Goal: Full visibility across extraction and infrastructure.

Deliverables:
- Prometheus metrics for jobs, failures, latency, LLM costs.
- Grafana dashboards for success rate and ban spikes.
- Log aggregation via Loki.

Acceptance criteria:
- Dashboards show domain success rate and proxy health.
- Alerts trigger on ban spikes or budget overruns.

## Phase 8: Network Infrastructure
Goal: Decouple proxy logic from code.

Deliverables:
- Smart egress gateway (Squid/Glider) with provider fallback.
- Ingress routing via Traefik for API and web endpoints.
- Configurable proxy policies in the DB.

Acceptance criteria:
- Workers route traffic through the gateway by default.
- Proxy provider switching does not require code changes.

## Phase 9: Human-Like Interaction and Vision
Goal: Reduce bot detection and external API cost.

Deliverables:
- Ghost Cursor integration for human-like mouse movement.
- Local OCR pipeline (Tesseract/PaddleOCR).
- Lightweight object detection (YOLO) for simple challenges.

Acceptance criteria:
- Protected UI flows succeed more often with human-like interaction.
- OCR handles image-encoded data without external APIs.

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

## Phase 12: Release Readiness
Goal: Make the project consumable by the public.

Deliverables:
- Contributor guide, security policy, and changelog.
- Example schemas, jobs, and sample outputs.
- Docker Compose for single-node demo.
- Kubernetes manifests or Helm chart for production.

Acceptance criteria:
- New contributor can run the stack from scratch.
- First-time users can submit a job and get results.

## Cross-Cutting Workstreams
- **Schema Registry**: Versioned schemas, migration path, validation rules.
- **Config Service**: Domain policies, selector sets, and routing rules.
- **Multi-Tenancy**: Per-tenant budgets, rate limits, and identity pools.
- **Security**: SSRF protection, allow/deny lists, audit logging.

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
- FastAPI submit/status/results.
- Postgres job state machine.
- Redis queues and dispatcher skeleton.
- FastEngine scraping + selector registry.
- Artifact storage to MinIO/S3.
- Minimal observability (metrics + logs).
