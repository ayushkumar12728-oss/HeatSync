"""
Scenario comparison helper
===========================
Thin helpers to run and rank multiple intervention scenarios against a
baseline grid and render the result as a table.
"""

from __future__ import annotations

import pandas as pd


def rank_scenarios(engine, base: pd.DataFrame,
                   scenario_names: list[str] | None = None) -> pd.DataFrame:
    """Run canonical scenarios against ``base`` and rank them coolest-first.

    Args:
        engine:         a ``scenario_engine.engine.SimulationEngine``.
        base:           baseline feature DataFrame.
        scenario_names: which scenarios to run (default: all canonical ones).

    Returns:
        Sorted DataFrame with per-scenario summary statistics.
    """
    names = scenario_names or [s["name"] for s in engine.scenarios]
    rows = [engine.run_scenario(name, base) for name in names]
    return (pd.DataFrame(rows)
            .sort_values("mean_delta_lst")
            .reset_index(drop=True))


def comparison_table(engine, base: pd.DataFrame,
                     scenarios: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Rank caller-supplied scenario grids against ``base``."""
    return engine.compare_scenarios(base, scenarios)


def to_markdown(table: pd.DataFrame,
                columns: list[str] = ("scenario", "mean_delta_lst", "pct_cells_cooler")) -> str:
    """Render a comparison table as Markdown for reports."""
    return table[list(columns)].to_markdown(index=False)
