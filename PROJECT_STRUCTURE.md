# Project Structure

An AI-powered **Urban Digital Twin** that monitors, predicts and simulates
**Urban Heat Island (UHI)** effects in Bhubaneswar, Odisha — from raw satellite
imagery to an interactive web dashboard.

## Architecture

```
                        ┌─────────────────────────┐
                        │  Frontend (React + Vite)│
                        │  Leaflet · Chart.js     │
                        └───────────┬─────────────┘
                                    │  HTTP / REST
                                    ▼
                        ┌─────────────────────────┐
                        │  Backend API (FastAPI)  │
                        │  prediction · layers    │
                        │  simulation · metrics   │
                        └───────────┬─────────────┘
                          ┌─────────┴──────────┐
                          ▼                    ▼
              ┌──────────────────┐  ┌─────────────────────┐
              │ PostgreSQL +     │  │  Artifact store      │
              │ PostGIS (opt.)   │  │  data/ · models/     │
              └──────────────────┘  └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  GIS Engine          │
                                    │  download · process  │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  Feature Engineering│
                                    │  100 m grid · ~90   │
                                    │  features / cell    │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  AI Engine (XGBoost)│
                                    │  CV · Optuna · SHAP │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  Scenario Simulator │
                                    │  trees · cool roofs │
                                    │  green corridors    │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  Prediction API     │
                                    │  /api/prediction/*  │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  Frontend Dashboard │
                                    │  live LST · layers  │
                                    └─────────────────────┘
```

## Data flow (one line per stage)

1. `gis-engine/` downloads Sentinel-2, Landsat 8/9, DEM, weather and AQI data,
   clips it to `boundary.geojson` and derives NDVI, LST, land cover, terrain
   and AQI layers into `data/processed/`.
2. `gis-engine/feature_engineering/` tessellates the study area into a 100 m
   grid and computes ~90 engineered features per cell →
   `data/feature_engineering/training_dataset.csv`.
3. `ai-engine/` trains an XGBoost model (with leakage detection, 5-fold CV,
   6-model comparison and Optuna tuning), explains it with SHAP and exports it
   as `models/best_model.pkl` + `.onnx`.
4. `scenario-engine/` provides the intervention simulation library (tree
   planting, cool roofs, green corridors, 7 canonical scenarios).
5. `backend/` (FastAPI) serves the model, layers and simulations over REST —
   artifact-first, with an optional PostgreSQL/PostGIS persistence layer.
6. `frontend/` (React + Vite) renders the GIS dashboard, analytics, simulator
   and priority matrix.

## Folder reference

| Folder | Purpose | Entry point |
|--------|---------|-------------|
| `frontend/` | HeatSync React (Vite) dashboard — Leaflet map, Chart.js analytics, intervention simulator, priority matrix | `npm run dev` |
| `backend/` | FastAPI service — predictions, data layers, simulations, explainability, dashboard payloads | `uvicorn backend.main:app` |
| `ai-engine/` | UHI ML pipeline — training, CV, hyperparameter search, SHAP, ONNX export, prediction | `python main.py` |
| `gis-engine/` | Unified GIS pipeline — per-dataset download + processing stages | `python main.py` |
| `scenario-engine/` | Intervention simulation library (tree, cool roof, green corridor, comparison) | imported by `backend/` |
| `database/` | PostgreSQL/PostGIS schema, SQL migrations, artifact seed loader | `python migrate.py` |
| `deployment/` | Docker image, docker-compose (at repo root), nginx proxy, deploy script, env templates | `docker compose up` |
| `docs/` | Setup, API, workflow, architecture and deployment guides | — |
| `tests/` | pytest suite (backend, serving, simulation engine) | `pytest tests/` |
| `scripts/` | One-off utility scripts that do not belong to a specific engine | — |

## Top-level files

| File | Purpose |
|------|---------|
| `README.md` | Project overview, quick start, API summary |
| `PROJECT_STRUCTURE.md` | This document |
| `CONTRIBUTING.md` | Setup, style and contribution guidelines |
| `LICENSE` | MIT license |
| `docker-compose.yml` | Local stack: backend + optional PostGIS |
| `requirements.txt` | Python runtime dependencies |
| `requirements-dev.txt` | Python dev/test dependencies (pytest, ruff, httpx) |
| `ruff.toml` | Ruff (linter) configuration |
| `Makefile` | Developer shortcuts (`make test`, `make train`, …) |
| `boundary.geojson` | Study-area boundary polygon — engines resolve it from the project root |
| `.env.example` | Environment variable template (copy to `.env`) |
| `.github/workflows/ci.yml` | GitHub Actions: compile, lint, test |
