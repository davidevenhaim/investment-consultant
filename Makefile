.PHONY: up down migrate migrate-local seed seed-advisor-scenario scrape-x test test-integration lint format logs shell-api run build venv install memory-reset-dev trigger-scheduled-research

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

seed-advisor-scenario: $(VENV)
	PYTHONPATH=$(PYTHONPATH) $(BIN)/python -m apps.cli.seed_advisor_scenario --reset

# Host-only: needs `pip install -e ".[social]" && playwright install chromium`
scrape-x: $(VENV)
	PYTHONPATH=$(PYTHONPATH) $(BIN)/python -m apps.cli.scrape_x --symbols $(SYMBOLS)

test: $(VENV)
	PYTHONPATH=$(PYTHONPATH) $(BIN)/pytest tests/ -v --cov=packages --cov=apps --cov-report=term-missing -m "not integration"

test-integration: $(VENV)
	@echo "Running integration tests — requires live ChromaDB on localhost:8001"
	@echo "Run 'make up' first to start services."
	PYTHONPATH=$(PYTHONPATH) $(BIN)/pytest tests/integration/ -m integration -v

memory-reset-dev:
	@echo "Resetting dev Chroma collections (clears all indexed research memory)..."
	$(COMPOSE) exec -T api python -m apps.cli.memory reset --yes

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

trigger-scheduled-research:
	$(COMPOSE) exec -T worker celery -A apps.worker.celery_app call \
		apps.worker.tasks.research.scheduled_research_task

typecheck: $(VENV)
	PYTHONPATH=$(PYTHONPATH) $(BIN)/mypy packages/ apps/ --ignore-missing-imports

mypy: typecheck

ps:
	$(COMPOSE) ps
