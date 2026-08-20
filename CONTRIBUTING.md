# Contributing

Thanks for your interest in the Urban Digital Twin! This guide covers setting
up the repository, running each component, and the conventions we follow.

## Repository setup

### 1. Clone

```bash
git clone https://github.com/<you>/urban-digital-twin.git
cd urban-digital-twin
```

### 2. Python environment

Requires Python **3.11+**.

```bash
python -m venv --system-site-packages .venv     # or: make setup
source .venv/bin/activate                        # Windows: .venv\Scripts\activate
```

> **GDAL note (Windows):** if `rasterio`/`geopandas` fail to install, use the
> [conda-forge](https://conda-forge.org/) channel
> (`conda install gdal rasterio geopandas`) — see [docs/setup.md](docs/setup.md).

### 3. Install dependencies

```bash
pip install -r requirements.txt       # runtime deps
pip install -r requirements-dev.txt   # dev/test deps (pytest, ruff, httpx)
cp .env.example .env                  # adjust as needed
```

### 4. Frontend installation

Requires Node.js **v18+** and npm **v9+**.

```bash
cd frontend
npm install
cp .env.example .env                  # VITE_* API keys (optional)
```

### 5. Backend installation

The FastAPI backend needs no extra install beyond the Python deps above.
Optionally install the PostgreSQL extras (already in `requirements.txt`):

```bash
pip install sqlalchemy psycopg2-binary  # included in requirements.txt
```

### 6. Database setup (optional, PostGIS)

```bash
export DATABASE_URL=postgresql://admin:password@localhost:5432/urban_digital_twin
python database/migrate.py                    # apply schema + migrations
python database/seed/load_artifacts.py        # load grid + predictions + simulations
```

The API is artifact-first and runs fine without a database.

## Running the pipeline

Run the stages in order — each is resumable; use `--force` to redo:

```bash
# 1. GIS engine — download + process all datasets
cd gis-engine && python main.py

# 2. Feature engineering — build the 100 m ML training grid
cd gis-engine/feature_engineering && python main.py

# 3. AI engine — train, explain, export, predict
cd ../.. && cd ai-engine && python main.py
```

### Run the backend

```bash
uvicorn backend.main:app --reload    # or: python -m backend.run
# Swagger UI: http://localhost:8000/docs
```

### Run the frontend

```bash
cd frontend
npm run dev            # dashboard → http://localhost:5173
npm run build          # production build → frontend/dist
```

### Run the tests

```bash
pytest tests/ -v       # or: make test
```

Model-dependent tests are skipped automatically when the trained artifacts
(`models/best_model.pkl` + `data/feature_engineering/training_dataset.csv`)
are absent — run the AI engine first to enable them.

## Coding style

- **Python:** follow [ruff.toml](ruff.toml); format and lint with
  `make lint` (`ruff check backend scenario-engine tests`). Run
  `ruff check --fix` before pushing.
- **JavaScript/JSX:** the frontend lints with `oxlint` (`npm run lint`).
- **SQL:** keep schema changes idempotent (`CREATE TABLE IF NOT EXISTS` …)
  and add a numbered migration file under `database/migrations/`.
- **Docs:** keep README/docs in sync with the code — update paths and
  commands when you move things.

## Commit style

- Write imperative, concise commit messages that explain **why**:
  `fix: correct AQI interpolation for missing stations`.
- Prefix by scope when useful: `feat(gis-engine): …`, `fix(backend): …`,
  `docs: …`, `test: …`, `chore: …`, `refactor: …`.
- Never commit generated artifacts: `data/`, `models/`, `logs/`,
  `node_modules/`, `__pycache__/`, `*.onnx`, `*.pkl` are gitignored.
- Keep commits small and reviewable; one logical change per commit.

## Folder rules

| Folder | What goes in it |
|--------|-----------------|
| `backend/` | FastAPI app — API routers, services, schemas, middleware, config |
| `ai-engine/` | ML training / inference pipeline code only (no model artifacts) |
| `gis-engine/` | Download + processing scripts and the feature-engineering grid |
| `scenario-engine/` | Intervention simulation library and scenario modules |
| `database/` | Schema, SQL migrations and the artifact seed loader |
| `deployment/` | Docker image, nginx config, env templates, deploy scripts |
| `docs/` | Markdown guides (setup, API, workflow, architecture, deployment) |
| `tests/` | pytest tests mirroring `backend/` and `scenario-engine/` |
| `scripts/` | Standalone utility scripts not tied to one engine |

Rules:

- **No generated outputs in the repo.** `data/` and `models/` are produced by
  the pipeline at runtime and must never be committed.
- **No duplicate logic.** If two modules do the same thing, consolidate —
  `backend/utils/aie.py` deliberately reuses `ai-engine/` code by loading it
  with `importlib` instead of copying it.
- **`boundary.geojson` stays at the repo root.** Engines resolve it from the
  project root (`PROJECT_ROOT / "boundary.geojson"`); do not move it.
- **Keep the file count lean.** Add a file only when it cannot live inside an
  existing module.
