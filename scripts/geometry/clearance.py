"""Road-corridor clearance index — the single authority on "is this point on tarmac?".

Used by the mesh pass (kerb sweeps must not cross other roads at junctions) and the environment
pass (street furniture, barriers, buildings and vegetation must clear EVERY drivable surface —
the loop and the connectors). Pure stdlib.
"""

from __future__ import annotations

import math

Vertex = tuple[float, float, float]


class RoadClearance:
    """Spatial index over every drivable surface. ``clear(x, z, margin)`` is False when the point
    sits within ``local half-width + margin`` of any indexed centerline vertex. Negative margins
    allow geometry that hugs a road's own edge (kerbs) while still rejecting mid-road crossings."""

    def __init__(self, cell: float = 50.0):
        self._pts: list[tuple[float, float, float]] = []
        self._cell = cell
        self._buckets: dict = {}

    def add_polyline(self, pts: list[Vertex], half) -> None:
        for i, p in enumerate(pts):
            x, z = p[0], p[2]
            hw = half[i] if isinstance(half, (list, tuple)) else float(half)
            self._pts.append((x, z, hw))
            self._buckets.setdefault((int(x // self._cell), int(z // self._cell)),
                                     []).append(len(self._pts) - 1)

    def clear(self, x: float, z: float, margin: float = 0.3) -> bool:
        ci, cj = int(x // self._cell), int(z // self._cell)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for k in self._buckets.get((ci + di, cj + dj), ()):
                    px, pz, hw = self._pts[k]
                    if math.hypot(px - x, pz - z) < hw + margin:
                        return False
        return True
