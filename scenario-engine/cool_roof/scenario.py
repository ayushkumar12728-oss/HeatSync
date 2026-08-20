"""
Cool-roof scenario
==================
Cool (high-albedo / reflective) roofs reflect solar radiation instead of
absorbing it, cutting the heat that buildings re-emit. Cool roofs do *not*
change physical building coverage, so the perturbations model the reduced
*thermal contribution* of built surfaces:

    ImperviousSurfaceRatio -= 5   * (coverage_pct / 100)
    BuildingCoveragePct    -= 3   * (coverage_pct / 100)
    HeatVulnerabilityIndex -= 0.03 * (coverage_pct / 100)
    VegetationCoolingIndex *= 1 + 0.10 * (coverage_pct / 100)

``coverage_pct`` is the share of roof area converted (0-100). Values are
clamped by the ai-engine bounds when applied.
"""

from __future__ import annotations


def build_perturbations(coverage_pct: float = 30.0) -> dict[str, tuple]:
    """Perturbations for converting ``coverage_pct`` % of roofs to cool roofs."""
    if not 0.0 <= coverage_pct <= 100.0:
        raise ValueError("coverage_pct must be between 0 and 100")
    f = coverage_pct / 100.0
    return {
        "ImperviousSurfaceRatio": ("add", -5.0 * f),
        "BuildingCoveragePct": ("add", -3.0 * f),
        "HeatVulnerabilityIndex": ("add", -0.03 * f),
        "VegetationCoolingIndex": ("mul", 1.0 + 0.10 * f),
    }
