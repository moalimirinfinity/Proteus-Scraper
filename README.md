# Proteus-Scraper

This repository contains the Proteus-Scraper control and data plane services.

- Architecture: see `docs/ARCHITECTURE.md`
- Project overview: see `docs/project-overview.md`
- Development plan: see `docs/DEVELOPMENT_PLAN.md`

## Quickstart

Start local services:

```bash
make up
poetry install
make init
```

Run the API:

```bash
poetry run uvicorn api.main:app --reload
```

Run the dispatcher and engine worker (separate terminals):

```bash
poetry run arq core.tasks.DispatcherWorkerSettings
poetry run arq core.tasks.EngineWorkerSettings
```

For BrowserEngine, set `ENGINE_QUEUE=engine:browser` before starting the engine worker.

Submit a job:

```bash
curl -X POST http://localhost:8000/submit \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","schema_id":"example","priority":"standard"}'
```

Submit a browser-rendered job:

```bash
curl -X POST http://localhost:8000/submit \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com?render=true","schema_id":"example","priority":"standard","engine":"browser"}'
```

Check status and results:

```bash
curl http://localhost:8000/status/<job_id>
curl http://localhost:8000/results/<job_id>
```

## Selector Registry (MVP)

Selectors are stored in Postgres and loaded at runtime for parsing. Example insert:

```sql
INSERT INTO selectors (schema_id, field, selector, data_type, required, active)
VALUES ('example', 'title', 'h1', 'string', true, true);
```
