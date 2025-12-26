.PHONY: up down test init dev stop

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
	nohup $(POETRY) run arq core.tasks.DispatcherWorkerSettings > /tmp/proteus-dispatcher.log 2>&1 &
	nohup env ENGINE_QUEUE=engine:fast $(POETRY) run arq core.tasks.EngineWorkerSettings > /tmp/proteus-fast.log 2>&1 &
	nohup env ENGINE_QUEUE=engine:browser $(POETRY) run arq core.tasks.EngineWorkerSettings > /tmp/proteus-browser.log 2>&1 &

stop:
	pkill -f "uvicorn api.main" || true
	pkill -f "arq core.tasks" || true
