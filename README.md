# Proteus-Scraper

Proteus-Scraper is a schema-driven extraction platform that combines fast HTTP fetching, browser rendering, and LLM recovery. You submit a URL and a schema; Proteus selects an engine, validates results, and stores both structured data and raw artifacts.

- Architecture: `docs/ARCHITECTURE.md`
- Project overview: `docs/project-overview.md`
- Development plan: `docs/DEVELOPMENT_PLAN.md`

## What You Get
- FastEngine (httpx) for static HTML.
- BrowserEngine (Playwright) for JS-rendered pages.
- StealthEngine (curl_cffi, optional) for TLS/JA3-sensitive targets.
- External API tier (allowlist + budget gated).
- Schema/selector CRUD + preview endpoints.
- List extraction with grouped selectors and attribute fields.
- LLM recovery + selector candidate promotion.
- Governance (rate limits, circuit breakers, budgets).
- Adaptive engine router (detector-driven escalation).
- Security (SSRF protections + auth/tenant scoping).
- Control Panel UI for preview and selector building.
- Plugin hooks for request/response/parse pipelines.
- Human-like browser cursor and local OCR/vision signals.

## Quickstart

Install dependencies:
```bash
poetry install
poetry run playwright install
```

(Optional) enable stealth fetcher:
```bash
poetry install --extras stealth
```

Start infra + API + workers:
```bash
make dev
```

If Poetry is not on your PATH:
```bash
make POETRY=/path/to/poetry dev
```

Seed a sample schema:
```bash
poetry run python scripts/seed_data.py
```

Submit a job:
```bash
curl -X POST http://127.0.0.1:8000/submit \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","schema_id":"example","priority":"standard"}'
```

Preview extraction immediately:
```bash
curl -X POST http://127.0.0.1:8000/schemas/example/preview \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","engine":"fast"}'
```

Preview raw HTML (fast or browser):
```bash
curl -X POST http://127.0.0.1:8000/preview/html \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","engine":"browser"}'
```

Check status/results:
```bash
curl http://127.0.0.1:8000/status/<job_id>
curl http://127.0.0.1:8000/results/<job_id>
```

Open the Control Panel UI:
- `http://127.0.0.1:8000/ui`

## Selector Registry
Selectors are stored in Postgres and loaded at runtime for parsing. You can manage them via the UI or the API.

Example selector insert via API:
```bash
curl -X POST http://127.0.0.1:8000/schemas/example/selectors \
  -H "Content-Type: application/json" \
  -d '{"field":"title","selector":"h1","data_type":"string","required":true,"active":true}'
```

XPath selectors are supported with a prefix:
- `xpath://div[@id="main"]//h1`

## Engine Selection
- `engine: "fast"` uses httpx.
- `engine: "browser"` uses Playwright.
- `engine: "stealth"` uses curl_cffi (requires extras).
- `engine: "external"` uses the external provider (allowlist + budget gated).

You can also hint in URLs:
- `?browser=true` or `?render=true` -> browser
- `?engine=stealth` or `?stealth=true` -> stealth

## Plugins
Plugins live in `plugins/` and can be enabled per schema or tenant.
- Set `PLUGINS_ALLOWLIST` to restrict which plugins can load.
- Use `PLUGINS_DEFAULT` to enable plugins for all jobs.
- Update schema `plugins` or `PUT /tenants/{tenant}/plugins`.

## Upgrade Notes
- Stealth fetching uses curl_cffi and is optional (`--extras stealth`).
- New fetcher config lives in `.env` (`FETCH_TIMEOUT_MS`, `FETCH_MAX_BYTES`, `FETCH_USER_AGENT`, `FETCH_CURL_IMPERSONATE`).
- External tier is gated by `EXTERNAL_ENABLED`, `EXTERNAL_API_KEY`, and `EXTERNAL_ALLOWLIST_DOMAINS`.
- Identity persistence requires `IDENTITY_ENCRYPTION_KEY`.
