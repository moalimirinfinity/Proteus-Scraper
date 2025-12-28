# Proteus-Scraper: Quickstart (5 Steps)

1) Install dependencies
```bash
/Users/moalimir/.local/bin/poetry install
/Users/moalimir/.local/bin/poetry run playwright install
```

2) Start infra + init DB
```bash
make dev
```

If Poetry is not on your PATH:
```bash
make POETRY=/path/to/poetry dev
```

3) Seed a sample schema + selectors
```bash
/Users/moalimir/.local/bin/poetry run python scripts/seed_data.py
```

4) Submit a job
```bash
curl -X POST http://127.0.0.1:8000/submit \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","schema_id":"example","priority":"standard"}'
```

5) Check results
```bash
curl http://127.0.0.1:8000/status/<job_id>
curl http://127.0.0.1:8000/results/<job_id>
```

Open the Control Panel UI at `http://127.0.0.1:8000/ui` to preview pages, click elements, and manage selector candidates.

Logs are written to `/tmp/proteus-*.log`. Stop services with `pkill -f "uvicorn api.main"` and `pkill -f "arq core.tasks"`.

## Observability (Prometheus + Grafana + Loki)

Start the observability stack:
```bash
make obs-up
```

Endpoints:
- Prometheus: http://127.0.0.1:9090
- Grafana: http://127.0.0.1:3000 (admin/admin)
- Loki: http://127.0.0.1:3100

Metrics are exposed at `http://127.0.0.1:8000/metrics` for the API, and on ports `8002`/`8003`/`8004` for the dispatcher and workers.

## API Examples (Schema/Selector CRUD + Preview)

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

Preview a schema (runs extraction immediately):
```bash
curl -X POST http://127.0.0.1:8000/schemas/example/preview \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","engine":"fast"}'
```
