# Migration Baseline Runbook

Purpose: snapshot current behavior before the tiered stack migration so the
submit/preview/results happy path stays reproducible.

## Critical Flows
- Submit job -> status -> results.
- Preview HTML (fast and browser).
- Schema/selector CRUD (optional, but useful for regression checks).
- UI preview at `/ui`.

## Current Engine Routing + Policy Defaults (Baseline)
- Engine order: fast -> stealth -> browser -> external.
- `ROUTER_MAX_DEPTH=2` (default) allows escalation up to browser; set `0` to disable escalation, `3` to allow external.
- Stealth gating: `STEALTH_ENABLED=true` + `STEALTH_ALLOWED_DOMAINS` (empty = allow all domains).
- External gating: `EXTERNAL_ENABLED=false`, `EXTERNAL_ALLOWLIST_DOMAINS` required, plus `EXTERNAL_API_KEY`.
- Budgets: `LLM_JOB_MAX_CALLS`, `LLM_TENANT_MAX_CALLS`, `EXTERNAL_MAX_CALLS_PER_TENANT`,
  `EXTERNAL_MAX_COST_PER_TENANT`, `EXTERNAL_COST_PER_CALL` (0 disables caps).
- Governance: `RATE_LIMIT_CAPACITY`, `RATE_LIMIT_REFILL_PER_SEC`, `RATE_LIMIT_MAX_WAIT_MS`,
  `CIRCUIT_BREAKER_THRESHOLD`, `CIRCUIT_BREAKER_WINDOW_SEC`, `CIRCUIT_BREAKER_COOLDOWN_SEC`
  (0 disables limits).

## Rollback Flags
- Set `ROUTER_MAX_DEPTH=0` to stop escalation.
- Set `STEALTH_ENABLED=false` to force fast-only fetching.
- Set `EXTERNAL_ENABLED=false` to block the external tier.

## Happy Path Snapshot (Local)
1) Start services:
```bash
make dev
```

2) Seed example schema + selectors:
```bash
poetry run python scripts/seed_data.py
```

3) Preview extraction:
```bash
curl -X POST http://127.0.0.1:8000/schemas/example/preview \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","engine":"fast"}'
```

4) Preview raw HTML (browser):
```bash
curl -X POST http://127.0.0.1:8000/preview/html \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","engine":"browser"}'
```

5) Submit a job and record the `job_id`, then check status/results:
```bash
curl -X POST http://127.0.0.1:8000/submit \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","schema_id":"example","priority":"standard"}'

curl http://127.0.0.1:8000/status/<job_id>
curl http://127.0.0.1:8000/results/<job_id>
```

Store outputs (JSON + artifacts) under `artifacts/baseline/<date>/` for later
comparison.

## Baseline Tag (Recommended)
Once you have a clean commit, tag it for rollback:
```bash
git tag -a migration-baseline-YYYYMMDD -m "Baseline before tiered stack migration"
```

## Environment Snapshot
Default values live in `.env.example`; capture any overrides used in the run.

## Operational Migration Steps (Post-Cleanup)
- Remove legacy Scrapy entrypoints and spider modules; deployments should not invoke `scrapy` commands.
- Ensure migrations are the source of truth: for a fresh DB run `alembic upgrade head`.
- For existing DBs, verify schema matches the baseline migration before using `alembic stamp head`.
- Start worker pools by queue (`engine:fast`, `engine:browser`, `engine:stealth`, `engine:external`) plus dispatcher.
- If enabling the external tier, set `EXTERNAL_ENABLED`, `EXTERNAL_API_KEY`, and `EXTERNAL_ALLOWLIST_DOMAINS`.
- For identity persistence, set `IDENTITY_ENCRYPTION_KEY` before storing cookies/storage state.
- Confirm Prometheus scrapes engine worker ports (`8003`-`8006`) and dispatcher (`8002`).
