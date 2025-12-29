.PHONY: up down test init dev stop obs-up obs-down

POETRY ?= poetry

up:
	docker-compose -f deploy/docker-compose.yml up -d --build

down:
	docker-compose -f deploy/docker-compose.yml down

test:
	$(POETRY) run pytest tests/

init:
	docker-compose -f deploy/docker-compose.yml up -d db redis
	$(POETRY) run python scripts/init_db.py

dev: up init
	$(POETRY) run playwright install
	nohup $(POETRY) run uvicorn api.main:app --reload > /tmp/proteus-api.log 2>&1 &
	nohup env METRICS_PORT=8002 $(POETRY) run arq core.tasks.DispatcherWorkerSettings > /tmp/proteus-dispatcher.log 2>&1 &
	nohup env METRICS_PORT=8003 ENGINE_QUEUE=engine:fast $(POETRY) run arq core.tasks.EngineWorkerSettings > /tmp/proteus-fast.log 2>&1 &
	nohup env METRICS_PORT=8004 ENGINE_QUEUE=engine:browser $(POETRY) run arq core.tasks.EngineWorkerSettings > /tmp/proteus-browser.log 2>&1 &
	nohup env METRICS_PORT=8005 ENGINE_QUEUE=engine:stealth $(POETRY) run arq core.tasks.EngineWorkerSettings > /tmp/proteus-stealth.log 2>&1 &
	nohup env METRICS_PORT=8006 ENGINE_QUEUE=engine:external $(POETRY) run arq core.tasks.EngineWorkerSettings > /tmp/proteus-external.log 2>&1 &

stop:
	pkill -f "uvicorn api.main" || true
	pkill -f "arq core.tasks" || true

obs-up:
	docker-compose -f deploy/observability/docker-compose.yml up -d

obs-down:
	docker-compose -f deploy/observability/docker-compose.yml down
