#!/usr/bin/env python3
"""
Load pipeline artifacts into PostgreSQL / PostGIS
==================================================
Populates the database from the pipeline outputs (optional PostGIS mode):

    * grid_cells   <- data/feature_engineering/training_dataset.geojson
    * predictions  <- data/predictions/predictions.csv
    * simulations  <- data/outputs/reports/sensitivity_analysis.csv

Usage::

    python database/migrate.py               # apply schema first
    python database/seed/load_artifacts.py --url postgresql://admin:password@localhost:5432/urban_digital_twin

``DATABASE_URL`` is used when ``--url`` is not given. Requires psycopg2.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("seed")

# database/seed/load_artifacts.py -> database -> root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# training CSV header -> snake_case database column
_SNAKE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _snake(name: str) -> str:
    return _SNAKE.sub("_", name).replace(" ", "_").lower()


def _clean(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=None, help="SQLAlchemy database URL "
                   "(default: $DATABASE_URL)")
    p.add_argument("--grid", type=Path,
                   default=PROJECT_ROOT / "data" / "feature_engineering"
                   / "training_dataset.geojson")
    p.add_argument("--predictions", type=Path,
                   default=PROJECT_ROOT / "data" / "predictions" / "predictions.csv")
    p.add_argument("--simulations", type=Path,
                   default=PROJECT_ROOT / "data" / "outputs" / "reports"
                   / "sensitivity_analysis.csv")
    p.add_argument("--batch-size", type=int, default=2000)
    args = p.parse_args()

    url = args.url or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: provide --url or set DATABASE_URL")
        return 1

    try:
        import pandas as pd
        from shapely.geometry import shape
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        print(f"ERROR: missing dependency ({exc}). Install requirements.txt")
        return 1

    engine = create_engine(url, pool_pre_ping=True, executemany_mode="values")

    # ---- grid cells ------------------------------------------------------
    if args.grid.exists():
        log.info("Loading grid from %s", args.grid)
        with open(args.grid, encoding="utf-8") as fh:
            geojson = json.load(fh)
        features = geojson.get("features", [])
        log.info("Grid features: %d", len(features))

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM predictions"))
            conn.execute(text("DELETE FROM simulations"))
            conn.execute(text("DELETE FROM grid_cells"))

        cols = None
        rows = []
        for feat in features:
            props = feat.get("properties", {})
            geom = shape(feat.get("geometry"))
            record = {_snake(k): _clean(v) for k, v in props.items()}
            record["grid_id"] = int(props.get("Grid_ID", 0))
            record["geometry"] = f"SRID=4326;{geom.wkt}"
            if cols is None:
                cols = list(record.keys())
            rows.append([record.get(c) for c in cols])

        with engine.begin() as conn:
            for i in range(0, len(rows), args.batch_size):
                chunk = rows[i:i + args.batch_size]
                column_list = ", ".join(cols)
                placeholders = ", ".join(f":{c}" for c in cols)
                # Column names come from the trusted training dataset; all
                # values are bound parameters.
                insert_sql = text(
                    f"INSERT INTO grid_cells ({column_list}) VALUES ({placeholders}) "  # noqa: S608
                    "ON CONFLICT (grid_id) DO NOTHING"
                )
                conn.execute(insert_sql, [dict(zip(cols, row, strict=True)) for row in chunk])
        log.info("grid_cells loaded: %d rows", len(rows))
    else:
        log.warning("Grid GeoJSON not found: %s - skipping grid_cells", args.grid)

    # ---- predictions ------------------------------------------------------
    if args.predictions.exists():
        df = pd.read_csv(args.predictions)
        records = [
            {
                "grid_id": int(r.grid_id) if not pd.isna(r.grid_id) else None,
                "scenario": "baseline",
                "predicted_lst": _clean(r.predicted_lst),
                "target_lst": _clean(r.target_lst),
                "residual_lst": _clean(r.residual),
            }
            for r in df.itertuples()
        ]
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO predictions (grid_id, scenario, predicted_lst, "
                "target_lst, residual_lst) VALUES (:grid_id, :scenario, "
                ":predicted_lst, :target_lst, :residual_lst)"
            ), records)
        log.info("predictions loaded: %d rows", len(records))
    else:
        log.warning("predictions.csv not found: %s", args.predictions)

    # ---- simulations ------------------------------------------------------
    if args.simulations.exists():
        df = pd.read_csv(args.simulations)
        records = [
            {
                "scenario": r.scenario,
                "description": r.description,
                "n_cells": None,
                "baseline_lst": _clean(r.baseline_lst),
                "mean_predicted_lst": _clean(r.mean_predicted_lst),
                "mean_delta_lst": _clean(r.mean_delta_lst),
                "min_delta": _clean(r.min_delta),
                "max_delta": _clean(r.max_delta),
                "pct_cells_cooler": _clean(r.pct_cells_cooler),
            }
            for r in df.itertuples()
        ]
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO simulations (scenario, description, n_cells, "
                "baseline_lst, mean_predicted_lst, mean_delta_lst, min_delta, "
                "max_delta, pct_cells_cooler) VALUES (:scenario, :description, "
                ":n_cells, :baseline_lst, :mean_predicted_lst, :mean_delta_lst, "
                ":min_delta, :max_delta, :pct_cells_cooler)"
            ), records)
        log.info("simulations loaded: %d rows", len(records))
    else:
        log.warning("sensitivity_analysis.csv not found: %s", args.simulations)

    log.info("Seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
