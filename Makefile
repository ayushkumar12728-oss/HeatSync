# =============================================================================
# Urban Digital Twin - developer shortcuts
# Usage:  make <target>   (on Windows use Git Bash / WSL, or run the commands
#         in README directly)
# =============================================================================

PYTHON    ?= python
VENV      ?= .venv
PIP       := $(VENV)/bin/pip
ifeq ($(OS),Windows_NT)
	PY := $(VENV)/Scripts/python
else
	PY := $(VENV)/bin/python
endif

.DEFAULT_GOAL := help

.PHONY: help setup venv install install-dev ingest process features train serve test lint migrate seed docker-build docker-up docker-down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: venv install ## Create the virtualenv and install runtime deps

venv: ## Create a virtualenv
	$(PYTHON) -m venv --system-site-packages $(VENV)

install: ## Install runtime dependencies
	$(PIP) install -r requirements.txt

install-dev: ## Install dev/test dependencies
	$(PIP) install -r requirements-dev.txt

ingest: ## Download remote-sensing data (Sentinel-2, Landsat, DEM, weather, AQI)
	cd gis-engine && $(PY) main.py

process: ## Process raw data (NDVI, LST, terrain, weather, AQI)
	cd gis-engine && $(PY) main.py --skip-download

features: ## Build the 100 m ML training grid (feature engineering)
	cd gis-engine/feature_engineering && $(PY) main.py

train: ## Run the AI engine end-to-end (CV, comparison, Optuna, SHAP, export)
	cd ai-engine && $(PY) main.py

serve: ## Start the FastAPI backend (dev)
	$(PY) -m uvicorn backend.main:app --reload

test: ## Run the test suite
	$(PY) -m pytest tests/ -v

lint: ## Lint the new code (backend / scenario-engine / tests)
	$(PY) -m ruff check backend scenario-engine tests

migrate: ## Apply database migrations (set DATABASE_URL first)
	$(PY) database/migrate.py

seed: ## Load pipeline artifacts into PostGIS (set DATABASE_URL first)
	$(PY) database/seed/load_artifacts.py

docker-build: ## Build the backend image
	docker build -f deployment/docker/Dockerfile -t urban-digital-twin:backend .

docker-up: ## Start the stack (backend + optional PostGIS)
	docker compose -f docker-compose.yml up -d --build

docker-down: ## Stop the stack
	docker compose -f docker-compose.yml down
