"""
Tree-planting scenario
======================
Trees cool the surface through canopy shading and evapotranspiration. The
perturbation set mirrors the canonical ``increase_trees`` scenario from the
ai-engine config, scaled by the requested number of trees per cell:

    TreeCount              += num_trees
    TreeDensity            += 10  * (num_trees / 50)
    MeanNDVI               += 0.04 * (num_trees / 50)
    VegetationDensity      += 5   * (num_trees / 50)
    GreenCover             += 5   * (num_trees / 50)
    VegetationCoolingIndex *= 1 + 0.10 * (num_trees / 50)

All values are clamped by the ai-engine bounds (percentages to [0, 100],
NDVI to [-1, 1]) when applied.
"""

from __future__ import annotations

# canonical ai-engine "increase_trees" deltas (per +50 trees)
_CANONICAL = {
    "TreeCount": ("add", 50.0),
    "TreeDensity": ("add", 10.0),
    "MeanNDVI": ("add", 0.04),
    "VegetationDensity": ("add", 5.0),
    "GreenCover": ("add", 5.0),
    "VegetationCoolingIndex": ("mul", 1.10),
}


def build_perturbations(num_trees: int = 100) -> dict[str, tuple]:
    """Perturbations for planting ``num_trees`` trees per grid cell."""
    if num_trees < 0:
        raise ValueError("num_trees must be >= 0")
    factor = num_trees / 50.0
    out: dict[str, tuple] = {}
    for col, (kind, value) in _CANONICAL.items():
        if kind == "add":
            out[col] = (kind, value * factor if col != "TreeCount" else float(num_trees))
        else:  # multiplicative
            out[col] = (kind, 1.0 + (value - 1.0) * factor)
    return out
