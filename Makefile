.PHONY: up down test init

up:
	docker-compose -f deploy/docker-compose.yml up -d --build

down:
	docker-compose -f deploy/docker-compose.yml down

test:
	poetry run pytest tests/

init:
	docker-compose -f deploy/docker-compose.yml up -d db redis
	poetry run python scripts/init_db.py
