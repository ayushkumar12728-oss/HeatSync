#!/usr/bin/env python3
"""
Pre-warm cell-level scenario caches
===================================
Computes per-cell XGBoost predictions for every predefined scenario over the
full 53,802-cell grid and writes the server-side caches under
``data/outputs/scenarios/`` (``{scenario}.json`` + ``{scenario}.geojson`` +
the shared ``_grid_wgs84.json`` geometry cache).

It also regenerates ``data/outputs/reports/sensitivity_analysis.csv`` on the
full grid so ``GET /api/simulation/results`` agrees with ``POST
/api/simulation/run`` and the cell-level endpoints (the offline pipeline
historically computed STEP 9 on the 20% test set, causing a small mismatch).

Run from the project root::

    .venv/Scripts/python scripts/prewarm_scenario_cells.py

Re-run any time the model or dataset changes; the endpoints regenerate the
cache automatically on demand (``?refresh=true`` forces it per scenario).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config.settings import get_settings  # noqa: E402
from backend.services.serving import ServingContext  # noqa: E402
from backend.services.simulation import SimulationService  # noqa: E402


def main() -> int:
    settings = get_settings()
    serving = ServingContext(settings)
    sim = SimulationService(settings, serving)

    if not serving.model_available:
        print("Trained model not available - nothing to pre-warm.")
        print(f"Required: {settings.model_pkl}")
        return 1

    t0 = time.time()

    # 1) regenerate the aggregate sensitivity CSV on the full grid
    csv_path = sim.regenerate_sensitivity_csv()
    print(f"[1/2] sensitivity CSV regenerated (full grid): {csv_path}")

    # 2) pre-warm every scenario's cell-level cache
    print("[2/2] pre-warming cell-level scenario caches ...")
    totals = []
    for name in sim.scenario_names():
        t = time.time()
        cells = sim.cells(name)
        elapsed = time.time() - t
        totals.append((name, cells["count"], cells["mean_delta_lst"], elapsed))
        print(
            f"  {name:<22} {cells['count']:>6} cells  "
            f"delta {cells['mean_delta_lst']:+.4f} °C  "
            f"({elapsed:.1f} s)"
        )

    print("-" * 70)
    for name, _count, delta, _elapsed in totals:
        print(f"{name:<22} mean delta {delta:+.4f} °C")
    print(f"done in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
