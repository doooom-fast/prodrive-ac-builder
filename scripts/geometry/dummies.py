"""Compute AC dummy object placements along the centerline (local ENU metres).

Required by AC (see skill: ac-track-modding):
  AC_START_0..N, AC_PIT_0..N, AC_TIME_0_L/R (start-finish), AC_TIME_n_L/R (sectors), AC_HOTLAP_START_0
Timing gates are emitted as L/R pairs (the two ends of the timing line across the road).

**Loops vs point-to-point.** A closed circuit and a rally stage need genuinely different timing
geometry, so ``loop`` is a real branch, not a cosmetic flag:

* ``loop=True`` — the grid goes on the straightest window anywhere on the lap, the start/finish
  line sits 30 m ahead of it, and sector gates divide the lap evenly, wrapping past the end back
  to the line.
* ``loop=False`` — the road has two ends and the car drives it once. The grid goes at the START of
  the road and ``AC_TIME_0`` (which AC treats as start/finish) goes at the FINISH, so the single
  crossing the driver makes is the one that completes the run and posts a stage time. Sector gates
  divide the run between them and never wrap — wrapping would put a gate behind the driver.
"""

from __future__ import annotations

import math

Vertex = tuple[float, float, float]


def _cum_length(pts: list[Vertex]) -> list[float]:
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2]))
    return d


def _tangent(pts: list[Vertex], i: int, loop: bool = True) -> tuple[float, float]:
    n = len(pts)
    if loop:
        a, b = pts[(i - 1) % n], pts[(i + 1) % n]
    else:
        # An open road's ends don't join. Wrapping here would take the heading from the last vertex
        # to the second — pointing the start gate across the map at the finish.
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
    dx, dz = b[0] - a[0], b[2] - a[2]
    L = math.hypot(dx, dz) or 1.0
    return dx / L, dz / L


def place_dummies(
    centerline_m: list[Vertex],
    widths_m: list[float],
    n_sectors: int = 3,
    n_pits: int = 4,
    loop: bool = True,
) -> dict[str, list[float]]:
    """Return {dummy_name: [x, y, z]}. Gates split the run into ``n_sectors`` equal-length arcs —
    around the lap when ``loop``, from start to finish when not (see the module docstring)."""
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
        tx, tz = _tangent(pts, i, loop)
        nx, nz = -tz, tx
        return [round(x + nx * signed_half, 3), round(y, 3), round(z + nz * signed_half, 3)]

    # THE START BELONGS ON A STRAIGHT (Kevin: "standardize starting on straights") — pts[0] is
    # wherever the source KML/OSM loop happened to begin, which put grids on corners. Scan for
    # the straightest, flattest ~260 m window (room for grid + timing line) and rotate the whole
    # start complex there. Score = worst 4-vertex heading change + a grade penalty.
    import math as _m

    def _heading(i):
        tx, tz = _tangent(pts, i, loop)
        return _m.atan2(tz, tx)

    W = 260.0
    step = max(1, n // 1200)
    best_score, best_i = None, 0
    for i0 in range(0, n - 1, step):
        j = i0
        worst_turn = 0.0
        while j < n - 1 and cum[j] - cum[i0] < W:
            d = abs((_m.degrees(_heading(min(j + 4, n - 1)) - _heading(j)) + 180.0) % 360.0 - 180.0)
            worst_turn = max(worst_turn, d)
            j += 4
        if cum[min(j, n - 1)] - cum[i0] < W * 0.9:
            continue                      # tail too short for the full window
        grade = abs(pts[min(j, n - 1)][1] - pts[i0][1]) / max(1.0, cum[min(j, n - 1)] - cum[i0])
        score = worst_turn + 300.0 * grade
        if best_score is None or score < best_score:
            best_score, best_i = score, i0

    def index_at_arc(arc_m: float) -> int:
        # Wrap only on a closed lap. On an open road, arc past either end clamps to that end —
        # a gate must land on real geometry, not teleport to the other end of the stage.
        target = arc_m % total if loop else min(max(arc_m, 0.0), total)
        for i in range(n):
            if cum[i] >= target:
                return i
        return n - 1

    if loop:
        start_arc = cum[best_i] + 45.0    # a car-grid's length into the straightest window
    else:
        # A stage starts where the road starts — the start line is a fixed place in the world, not
        # whichever window happens to be straightest. Far enough in to leave grid room behind it.
        start_arc = min(45.0, total * 0.02)
    s_i = index_at_arc(start_arc)

    out: dict[str, list[float]] = {}
    if loop:
        # Start-finish line 30 m AHEAD of the grid: AC arms the lap clock only when the car
        # CROSSES the line — spawning ON it (start at the same station) never registered laps.
        line_arc = start_arc + 30.0
        # Start-finish (sector 0) at the LINE + intermediate sector gates, as L/R pairs.
        for k in range(n_sectors):
            i = index_at_arc(line_arc + (k / n_sectors) * total)
            half = widths_m[i] / 2.0
            out[f"AC_TIME_{k}_L"] = offset(i, +half)
            out[f"AC_TIME_{k}_R"] = offset(i, -half)
    else:
        # Point-to-point: AC_TIME_0 is the FINISH, at the far end of the road. The driver crosses it
        # exactly once and that crossing posts the stage time. Held just short of the last vertex so
        # the gate sits on built road rather than at the ragged tip of the ribbon.
        finish_arc = max(total - 15.0, start_arc + 30.0)
        i = index_at_arc(finish_arc)
        half = widths_m[i] / 2.0
        out["AC_TIME_0_L"] = offset(i, +half)
        out["AC_TIME_0_R"] = offset(i, -half)
        # Intermediate splits divide the run itself. Numbered up from 1 in driving order, so the
        # driver crosses 1, 2, ... and finally 0 — the same order a lap crosses them.
        run = finish_arc - start_arc
        for k in range(1, n_sectors):
            i = index_at_arc(start_arc + (k / n_sectors) * run)
            half = widths_m[i] / 2.0
            out[f"AC_TIME_{k}_L"] = offset(i, +half)
            out[f"AC_TIME_{k}_R"] = offset(i, -half)

    sx, sy, sz = pts[s_i]
    out["AC_START_0"] = [round(sx, 3), round(sy, 3), round(sz, 3)]
    out["AC_HOTLAP_START_0"] = [round(sx, 3), round(sy, 3), round(sz, 3)]

    # Pit slots ON the road along the start straight (no separate pit lane is modeled). Offsetting them
    # onto the verge dropped the car — the graded grass sits below the road there, so a pit-spawned car
    # fell off the edge (the hotlap start, which sits ON the road, was fine). Stagger them back along the
    # centerline and alternate left/right WITHIN the lane so cars don't overlap, at road height like
    # AC_START. staggered ~12 m apart (>2 car lengths), ~40% of a half-lane off-centre each side.
    for p in range(n_pits):
        i = index_at_arc(start_arc + (p + 1) * 10.0)     # staggered up the start straight
        side = (widths_m[i] / 2.0) * 0.4 * (1.0 if p % 2 == 0 else -1.0)
        out[f"AC_PIT_{p}"] = offset(i, side)
    return out
