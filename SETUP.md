# Proteus-Scraper: Quickstart (5 Steps)

1) Install dependencies
```bash
poetry install
poetry run playwright install
```

Optional stealth fetcher:
```bash
poetry install --extras stealth
```

2) Start infra + API + workers
```bash
make dev
```

If Poetry is not on your PATH:
```bash
make POETRY=/path/to/poetry dev
```

3) Seed a sample schema + selectors
```bash
poetry run python scripts/seed_data.py
```

4) Run a preview or submit a job
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

5) Check results
```bash
curl http://127.0.0.1:8000/status/<job_id>
curl http://127.0.0.1:8000/results/<job_id>
```

Open the Control Panel UI at `http://127.0.0.1:8000/ui` to preview pages, click elements, and manage selector candidates.

Logs are written to `/tmp/proteus-*.log`. Stop services with `make stop`. Stop infra with `make down`.

## Engine Selection
- `engine: "fast"` uses httpx.
- `engine: "browser"` uses Playwright.
- `engine: "stealth"` uses curl_cffi (requires extras).
- `engine: "external"` uses the external provider (allowlist + budget gated).

You can also hint in URLs:
- `?browser=true` or `?render=true` -> browser
- `?engine=stealth` or `?stealth=true` -> stealth

## Fast Fetcher Configuration
Environment variables in `.env`:
- `FETCH_TIMEOUT_MS`
- `FETCH_MAX_BYTES`
- `FETCH_USER_AGENT`
- `FETCH_CURL_IMPERSONATE` (stealth only)

## External API Tier (Optional)
Enable Tier 4 fallback for high-value targets:
- `EXTERNAL_ENABLED=true`
- `EXTERNAL_API_KEY=...`
- `EXTERNAL_ALLOWLIST_DOMAINS=example.com,example.org`
- Optional caps: `EXTERNAL_MAX_CALLS_PER_TENANT`, `EXTERNAL_MAX_COST_PER_TENANT`

## Identity Storage (Cookies + storageState)
To persist identity cookies/storage state, set:
- `IDENTITY_ENCRYPTION_KEY` (required for encryption at rest)

## Auth + CSRF (Optional)
If `AUTH_ENABLED=true` or tokens are configured, API/UI calls require auth.
- API token: set `AUTH_API_TOKENS=token:tenant`
- Cookie auth uses `proteus_token` + `proteus_csrf` (UI handles CSRF automatically)

## Network Infrastructure (Gateway + Traefik)
The default `deploy/docker-compose.yml` includes a proxy gateway and Traefik:
- Gateway (Glider) listens on `http://127.0.0.1:8081`.
- Traefik ingress listens on `http://127.0.0.1:8088` and routes to the API/UI.

Set `PROXY_GATEWAY_URL=http://localhost:8081` in `.env` to send traffic through the gateway by default.

## Observability (Prometheus + Grafana + Loki)
Start the observability stack:
```bash
make obs-up
```

Endpoints:
- Prometheus: http://127.0.0.1:9090
- Grafana: http://127.0.0.1:3000 (admin/admin)
- Loki: http://127.0.0.1:3100

Metrics:
- API: http://127.0.0.1:8000/metrics
- Dispatcher: http://127.0.0.1:8002/metrics
- Fast worker: http://127.0.0.1:8003/metrics
- Browser worker: http://127.0.0.1:8004/metrics
- Stealth worker: http://127.0.0.1:8005/metrics
- External worker: http://127.0.0.1:8006/metrics

## API Examples (Schema/Selector CRUD)
Create a schema:
```bash
curl -X POST http://127.0.0.1:8000/schemas \
  -H "Content-Type: application/json" \
  -d '{"schema_id":"example","name":"Example","description":"Example.com demo"}'
```

Add a selector:
```bash
curl -X POST http://127.0.0.1:8000/schemas/example/selectors \
  -H "Content-Type: application/json" \
  -d '{"field":"title","selector":"h1","data_type":"string","required":true,"active":true}'
```
