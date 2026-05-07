.PHONY: up down migrate test lint format logs shell-api run build

export PYTHONPATH := $(shell pwd)/packages

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

migrate:
	docker compose exec api alembic upgrade head

test:
	PYTHONPATH=$(PYTHONPATH) pytest tests/ -v --cov=packages --cov=apps --cov-report=term-missing

lint:
	PYTHONPATH=$(PYTHONPATH) ruff check packages/ apps/ tests/
	PYTHONPATH=$(PYTHONPATH) mypy packages/ apps/ --ignore-missing-imports

format:
	ruff format packages/ apps/ tests/

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker beat

shell-api:
	docker compose exec api bash

shell-worker:
	docker compose exec worker bash

run:
	docker compose exec api python -m apps.cli.run

ps:
	docker compose ps
