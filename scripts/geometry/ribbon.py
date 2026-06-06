"""Build the road ribbon (1ROAD) and the grass heightfield mesh (GRASS).

The ribbon is swept along the projected centerline using per-vertex width; the grass mesh comes
from the terrain heightfield with the road footprint stitched/cut in.
"""

from __future__ import annotations

from typing import Any


def road_ribbon(
    centerline_m: list[tuple[float, float, float]],
    widths_m: list[float],
) -> dict[str, Any]:
    """Sweep a drivable ribbon (named ``1ROAD_*``) along the centerline. Returns mesh data."""
    raise NotImplementedError("Offset left/right by width/2 per vertex; build quad strip + normals.")


def grass_heightfield(heightfield: Any, road_footprint: Any) -> dict[str, Any]:
    """Build the surrounding grass mesh (named ``GRASS``) from the heightfield grid."""
    raise NotImplementedError("Triangulate the grid; cut/lower the road footprint to avoid z-fight.")
