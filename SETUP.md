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

3) Seed a selector
```sql
INSERT INTO selectors (id, schema_id, field, selector, data_type, required, active)
VALUES (gen_random_uuid(), 'example', 'title', 'h1', 'string', true, true);
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

Logs are written to `/tmp/proteus-*.log`. Stop services with `pkill -f "uvicorn api.main"` and `pkill -f "arq core.tasks"`.
