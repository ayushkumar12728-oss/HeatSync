#!/usr/bin/env python3
"""
Register Model in Registry
===========================
Manages model versioning and artifact registration.

Actions:
    register  - Register a new model version
    status    - Show current model status
    promote   - Promote a model to production
    compare   - Compare two model versions

Outputs:
    model_registry/manifest.json  - Registry manifest
    model_registry/{version}/     - Model artifacts

Usage:
    python scripts/register_model.py status
    python scripts/register_model.py register --version v2
    python scripts/register_model.py promote --version v2
    python scripts/register_model.py compare --v1 v1 --v2 v2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("register_model")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = PROJECT_ROOT / "model_registry"
MANIFEST_PATH = REGISTRY_DIR / "manifest.json"


def load_manifest() -> dict:
    """Load or create the registry manifest."""
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "versions": {},
        "production_model": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def save_manifest(manifest: dict) -> None:
    """Save the registry manifest."""
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


def cmd_status(args) -> None:
    """Show current model status."""
    manifest = load_manifest()

    print("\n" + "=" * 60)
    print("MODEL REGISTRY STATUS")
    print("=" * 60)
    print(f"Production model: {manifest.get('production_model', 'None')}")
    print(f"Registered versions: {len(manifest.get('versions', {}))}")
    print()

    for version, info in manifest.get("versions", {}).items():
        status = "★ PRODUCTION" if version == manifest.get("production_model") else "  registered"
        print(f"  {version}: {status}")
        print(f"    Type: {info.get('model_type', 'unknown')}")
        print(f"    Features: {info.get('feature_count', 'unknown')}")
        print(f"    RMSE: {info.get('test_rmse', 'unknown')}°C")
        print(f"    Registered: {info.get('registered_at', 'unknown')}")
        print()

    print("=" * 60)


def cmd_register(args) -> None:
    """Register a model version."""
    version = args.version
    version_dir = REGISTRY_DIR / version

    if not version_dir.exists():
        log.error("Version directory not found: %s", version_dir)
        return

    # Check required artifacts
    model_path = version_dir / f"model_{version}.joblib"
    metrics_path = version_dir / f"metrics_{version}.json"
    schema_path = version_dir / f"feature_schema_{version}.json"

    if not model_path.exists():
        log.error("Model artifact not found: %s", model_path)
        return

    # Load metrics
    metrics = {}
    if metrics_path.exists():
        with open(metrics_path, encoding="utf-8") as fh:
            metrics = json.load(fh)

    # Load schema
    schema = {}
    if schema_path.exists():
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)

    # Register
    manifest = load_manifest()
    manifest["versions"][version] = {
        "model_type": "XGBRegressor",
        "feature_count": schema.get("feature_count", 0),
        "features": schema.get("features", []),
        "categorical_columns": schema.get("categorical_columns", []),
        "weather_features": schema.get("weather_features", []),
        "test_rmse": metrics.get("test_metrics", {}).get("RMSE"),
        "test_mae": metrics.get("test_metrics", {}).get("MAE"),
        "test_r2": metrics.get("test_metrics", {}).get("R2"),
        "cv_rmse": metrics.get("cv_summary", {}).get("RMSE"),
        "train_dates": schema.get("training_dates", []),
        "val_dates": schema.get("validation_dates", []),
        "test_dates": schema.get("test_dates", []),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "model_path": str(model_path),
        "metrics_path": str(metrics_path),
        "schema_path": str(schema_path),
    }
    save_manifest(manifest)

    log.info("Model %s registered successfully", version)


def cmd_promote(args) -> None:
    """Promote a model to production."""
    version = args.version
    manifest = load_manifest()

    if version not in manifest.get("versions", {}):
        log.error("Version %s not registered", version)
        return

    manifest["production_model"] = version
    save_manifest(manifest)

    log.info("Model %s promoted to production", version)

    # Create symlink for easy access
    prod_link = REGISTRY_DIR / "production"
    if prod_link.exists() or prod_link.is_symlink():
        prod_link.unlink()
    prod_link.symlink_to(REGISTRY_DIR / version)

    log.info("Production symlink: %s -> %s", prod_link, REGISTRY_DIR / version)


def cmd_compare(args) -> None:
    """Compare two model versions."""
    manifest = load_manifest()
    versions = manifest.get("versions", {})

    v1_info = versions.get(args.v1)
    v2_info = versions.get(args.v2)

    if not v1_info or not v2_info:
        log.error("One or both versions not found")
        return

    print("\n" + "=" * 60)
    print(f"MODEL COMPARISON: {args.v1} vs {args.v2}")
    print("=" * 60)

    for metric in ["test_rmse", "test_mae", "test_r2"]:
        v1_val = v1_info.get(metric)
        v2_val = v2_info.get(metric)
        label = metric.replace("test_", "").upper()
        print(f"  {label}: {args.v1}={v1_val} | {args.v2}={v2_val}")

    print()
    print(f"  {args.v1} features: {v1_info.get('feature_count', '?')}")
    print(f"  {args.v2} features: {v2_info.get('feature_count', '?')}")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Model registry management")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("status", help="Show model status")

    reg = sub.add_parser("register", help="Register a model")
    reg.add_argument("--version", required=True, help="Model version (e.g. v2)")

    prom = sub.add_parser("promote", help="Promote to production")
    prom.add_argument("--version", required=True, help="Model version")

    comp = sub.add_parser("compare", help="Compare versions")
    comp.add_argument("--v1", required=True, help="First version")
    comp.add_argument("--v2", required=True, help="Second version")

    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "register":
        cmd_register(args)
    elif args.command == "promote":
        cmd_promote(args)
    elif args.command == "compare":
        cmd_compare(args)
    else:
        log.error("Unknown command: %s", args.command)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
