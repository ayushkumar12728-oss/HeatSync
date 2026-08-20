"""
Green-corridor scenario
=======================
Green corridors are connected belts of vegetation that channel cool air
through the city and increase green connectivity. The perturbations scale
with the corridor width relative to a 50 m reference corridor:

    GreenSpacePct           += 8    * (corridor_width / 50)
    MeanNDVI                += 0.03 * (corridor_width / 50)
    GreenToBuiltRatio       *= 1 + 0.15 * (corridor_width / 50)
    VegetationCoolingIndex  *= 1 + 0.15 * (corridor_width / 50)
    DistToPark              *= 1 - 0.10 * (corridor_width / 50)

Values are clamped by the ai-engine bounds when applied.
"""

from __future__ import annotations


def build_perturbations(corridor_width: int = 50) -> dict[str, tuple]:
    """Perturbations for introducing a ``corridor_width`` m green corridor."""
    if corridor_width < 0:
        raise ValueError("corridor_width must be >= 0")
    f = corridor_width / 50.0
    return {
        "GreenSpacePct": ("add", 8.0 * f),
        "MeanNDVI": ("add", 0.03 * f),
        "GreenToBuiltRatio": ("mul", 1.0 + 0.15 * f),
        "VegetationCoolingIndex": ("mul", 1.0 + 0.15 * f),
        "DistToPark": ("mul", max(0.0, 1.0 - 0.10 * f)),
    }
