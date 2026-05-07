.PHONY: up down migrate migrate-local seed test lint format logs shell-api run build venv install

PYTHON    := python3.12
VENV      := .venv
BIN       := $(VENV)/bin
COMPOSE   := docker compose -f $(shell pwd)/docker-compose.yml --project-directory $(shell pwd)

export PYTHONPATH := $(shell pwd)/packages

$(VENV):
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -e ".[dev]"

venv: $(VENV)

install: venv

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

migrate:
	$(COMPOSE) exec api alembic upgrade head

migrate-local:
	PYTHONPATH=$(PYTHONPATH) $(BIN)/alembic upgrade head

seed:
	$(COMPOSE) exec api python -m apps.cli.seed

seed-local:
	PYTHONPATH=$(PYTHONPATH) $(BIN)/python apps/cli/seed.py

test: $(VENV)
	PYTHONPATH=$(PYTHONPATH) $(BIN)/pytest tests/ -v --cov=packages --cov=apps --cov-report=term-missing

lint: $(VENV)
	PYTHONPATH=$(PYTHONPATH) $(BIN)/ruff check packages/ apps/ tests/
	PYTHONPATH=$(PYTHONPATH) $(BIN)/mypy packages/ apps/ --ignore-missing-imports

format: $(VENV)
	$(BIN)/ruff format packages/ apps/ tests/

logs:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f api

logs-worker:
	$(COMPOSE) logs -f worker beat

shell-api:
	$(COMPOSE) exec api bash

shell-worker:
	$(COMPOSE) exec worker bash

run:
	$(COMPOSE) exec api python -m apps.cli.run

ps:
	$(COMPOSE) ps
