"""Compute AC dummy object placements along the centerline (local ENU metres).

Required by AC (see skill: ac-track-modding):
  AC_START_0..N, AC_PIT_0..N, AC_TIME_0_L/R (start-finish), AC_TIME_n_L/R (sectors), AC_HOTLAP_START_0
Timing gates are emitted as L/R pairs (the two ends of the timing line across the road).
"""

from __future__ import annotations

import math

Vertex = tuple[float, float, float]


def _cum_length(pts: list[Vertex]) -> list[float]:
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2]))
    return d


def _tangent(pts: list[Vertex], i: int) -> tuple[float, float]:
    n = len(pts)
    a, b = pts[(i - 1) % n], pts[(i + 1) % n]
    dx, dz = b[0] - a[0], b[2] - a[2]
    L = math.hypot(dx, dz) or 1.0
    return dx / L, dz / L


def place_dummies(
    centerline_m: list[Vertex],
    widths_m: list[float],
    n_sectors: int = 3,
    n_pits: int = 4,
) -> dict[str, list[float]]:
    """Return {dummy_name: [x, y, z]}. Gates split the lap into ``n_sectors`` equal-length arcs."""
    pts = centerline_m
    n = len(pts)
    cum = _cum_length(pts)
    total = cum[-1]

    def index_at(fraction: float) -> int:
        target = fraction * total
        for i in range(n):
            if cum[i] >= target:
                return i
        return n - 1

    def offset(i: int, signed_half: float) -> list[float]:
        x, y, z = pts[i]
        tx, tz = _tangent(pts, i)
        nx, nz = -tz, tx
        return [round(x + nx * signed_half, 3), round(y, 3), round(z + nz * signed_half, 3)]

    out: dict[str, list[float]] = {}
    # Start-finish (sector 0) + intermediate sector gates, as L/R timing-line pairs.
    for k in range(n_sectors):
        i = index_at(k / n_sectors)
        half = widths_m[i] / 2.0
        out[f"AC_TIME_{k}_L"] = offset(i, +half)
        out[f"AC_TIME_{k}_R"] = offset(i, -half)

    sx, sy, sz = pts[0]
    out["AC_START_0"] = [round(sx, 3), round(sy, 3), round(sz, 3)]
    out["AC_HOTLAP_START_0"] = [round(sx, 3), round(sy, 3), round(sz, 3)]

    # Pit slots: placeholder along the start straight, offset onto the (right-side) verge.
    # The real pit lane is the SW Quality-Restaurant-Equipment spur (TODO: model it).
    for p in range(n_pits):
        i = min(p * 5, n - 1)
        out[f"AC_PIT_{p}"] = offset(i, -(widths_m[i] / 2.0 + 4.0))
    return out
