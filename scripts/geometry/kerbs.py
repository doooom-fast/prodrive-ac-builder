"""Generate 1KERB ribbons at the corners of the centerline (curvature-based).

Finds high-curvature runs (corners), lays a raised kerb strip on the inside edge of each, named
``1KERB_*`` so AC treats it as a kerb (rumble via surfaces.ini KEY=KERB). Inputs are local ENU metres.
"""

from __future__ import annotations

import math

Vertex = tuple[float, float, float]


def _turn_rate(pts: list[Vertex]) -> list[float]:
    """Signed turn angle per metre at each vertex (in the X-Z plane); +ve = left turn."""
    n = len(pts)
    tr = [0.0] * n
    for i in range(1, n - 1):
        (ax, _, az), (bx, _, bz), (cx, _, cz) = pts[i - 1], pts[i], pts[i + 1]
        v1, v2 = (bx - ax, bz - az), (cx - bx, cz - bz)
        l1, l2 = math.hypot(*v1) or 1e-6, math.hypot(*v2) or 1e-6
        cross = max(-1.0, min(1.0, (v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)))
        tr[i] = math.asin(cross) / ((l1 + l2) / 2)
    return tr


def _smooth(a: list[float], k: int = 3) -> list[float]:
    n = len(a)
    return [sum(a[max(0, i - k):min(n, i + k + 1)]) / len(a[max(0, i - k):min(n, i + k + 1)]) for i in range(n)]


def _inside_normal(pts: list[Vertex], k: int, side: float) -> tuple[float, float]:
    """Unit normal at vertex k pointing to the ``side`` of the road (left-normal × side)."""
    n = len(pts)
    a = pts[max(0, k - 1)]
    b = pts[min(n - 1, k + 1)]
    tx, tz = b[0] - a[0], b[2] - a[2]
    tl = math.hypot(tx, tz) or 1e-6
    return (-tz / tl * side, tx / tl * side)


def _fine_stations(poly: list[Vertex], step: float) -> list[tuple[float, float, float, float, float, float]]:
    """Resample a polyline to ~``step`` spacing; return (x, y, z, tx, tz, arc) with a unit X-Z tangent.
    Kerbs are densified like this so the per-metre ridges can be modelled (the 3 m centreline is far
    too coarse for that)."""
    seg = [0.0]
    for i in range(1, len(poly)):
        seg.append(seg[-1] + math.hypot(poly[i][0] - poly[i - 1][0], poly[i][2] - poly[i - 1][2]))
    total = seg[-1]
    if total < 1e-6:
        return []
    steps = max(1, round(total / step))
    out = []
    si = 1
    for s in range(steps + 1):
        d = total * s / steps
        while si < len(poly) - 1 and seg[si] < d:
            si += 1
        a, b = poly[si - 1], poly[si]
        denom = (seg[si] - seg[si - 1]) or 1e-6
        t = (d - seg[si - 1]) / denom
        tx, tz = b[0] - a[0], b[2] - a[2]
        tl = math.hypot(tx, tz) or 1e-6
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t,
                    tx / tl, tz / tl, d))
    return out


def corner_kerbs(centerline_m: list[Vertex], widths_m: list[float], *, thr: float = 0.007,
                 min_run: int = 5, kerb_w: float = 1.0, kerb_h: float = 0.10, ridge_period: float = 0.6,
                 ridge_lo: float = 0.45, top_frac: float = 0.55, lift: float = 0.01,
                 fine_step: float = 0.3, sharp: float = 0.05, tile_m: float = 0.6) -> dict:
    """Real 3D **ridged** kerbs on corners — a raised, serrated rumble strip, not a flat texture plane.
    Each corner run is resampled fine (``fine_step``) and a cross-section is swept along it:
        road-edge bottom -> raised top (with a vertical outer face) -> ramp back down to the track,
    with the top height pulsing every ``ridge_period`` m (down to ``ridge_lo`` x height) to form the
    ridges you feel. ``kerb_h`` is the kerb height — tune it freely. Sits on the TRACK side of the
    edge; build_mesh raises the whole thing onto the road. Sweepers get inside+outside kerbs; tight
    junctions get a short inside kerb hugging the apex. UVs: U across the profile, V along the run."""
    pts = centerline_m
    n = len(pts)
    rate = _smooth(_turn_rate(pts))
    verts: list[Vertex] = []
    uvs: list[tuple[float, float]] = []
    tris: list[tuple[int, int, int]] = []

    def sweep(run: list[int], side: float, half: float) -> None:
        st = _fine_stations([pts[k] for k in run], fine_step)
        if len(st) < 2:
            return
        rows = []
        for x, y, z, tx, tz, arc in st:
            nx, nz = -tz * side, tx * side                       # toward this side of the road
            ph = (arc % ridge_period) / ridge_period             # triangle wave -> serrated ridges
            h = kerb_h * (ridge_lo + (1.0 - ridge_lo) * (1.0 - abs(2.0 * ph - 1.0)))
            edge, top, ramp = half, half - kerb_w * top_frac, half - kerb_w
            r = len(verts)
            verts.append((x + nx * edge, y + lift, z + nz * edge))            # 0 edge bottom
            verts.append((x + nx * edge, y + lift + h, z + nz * edge))        # 1 edge top (vertical face)
            verts.append((x + nx * top, y + lift + h, z + nz * top))          # 2 top inner
            verts.append((x + nx * ramp, y + lift, z + nz * ramp))            # 3 ramp bottom (track side)
            v = arc / tile_m
            uvs.extend([(0.0, v), (0.15, v), (0.5, v), (1.0, v)])
            rows.append(r)
        for r in range(len(rows) - 1):
            p, q = rows[r], rows[r + 1]
            for u in (0, 1, 2):  # outer vertical face (0->1), top (1->2), ramp (2->3)
                tris.append((p + u, p + u + 1, q + u + 1))
                tris.append((p + u, q + u + 1, q + u))

    i = 0
    while i < n:
        if abs(rate[i]) <= thr:
            i += 1
            continue
        j = i
        while j < n and abs(rate[j]) > thr:
            j += 1
        run = list(range(i, j))
        peak = max(abs(rate[k]) for k in run)
        side = 1.0 if rate[run[len(run) // 2]] > 0 else -1.0
        half = widths_m[run[len(run) // 2]] / 2.0
        if peak >= sharp and len(run) >= 2:
            sweep(run, side, half)            # tight junction -> inside ridged kerb at the apex
        elif len(run) >= min_run:
            sweep(run, side, half)            # sweeper -> inside ...
            sweep(run, -side, half)           # ... and outside
        i = j
    return {"vertices": verts, "uvs": uvs, "tris": tris}


def corner_barriers(centerline_m: list[Vertex], widths_m: list[float], *, thr: float = 0.013,
                    min_run: int = 7, off: float = 1.6, base_lift: float = -0.4, height: float = 1.2,
                    pad: int = 4, tile_m: float = 2.0) -> dict:
    """A low barrier wall on the OUTSIDE of each corner (opposite the kerb) — where cars run wide.
    Realistic for an open road circuit (guardrails at corners, open straights) rather than walling the
    whole lap. Returns a wall mesh with UVs (U up the 0→1 face, V along the run). build_mesh raises it
    with the road; ``base_lift`` sinks the foot into the graded verge so it doesn't float."""
    pts = centerline_m
    n = len(pts)
    rate = _smooth(_turn_rate(pts))
    verts: list[Vertex] = []
    uvs: list[tuple[float, float]] = []
    tris: list[tuple[int, int, int]] = []
    i = 0
    while i < n:
        if abs(rate[i]) <= thr:
            i += 1
            continue
        j = i
        while j < n and abs(rate[j]) > thr:
            j += 1
        if j - i >= min_run:
            side = -1.0 if rate[(i + j) // 2] > 0 else 1.0  # OUTSIDE of the turn
            run = list(range(max(0, i - pad), min(n, j + pad)))  # extend past the apex
            arc = 0.0
            ring = []
            for idx, k in enumerate(run):
                x, y, z = pts[k]
                if idx > 0:
                    p = pts[run[idx - 1]]
                    arc += math.hypot(x - p[0], z - p[2])
                a = pts[max(0, k - 1)]
                b = pts[min(n - 1, k + 1)]
                tx, tz = b[0] - a[0], b[2] - a[2]
                tl = math.hypot(tx, tz) or 1e-6
                nx, nz = -tz / tl, tx / tl
                o = side * (widths_m[k] / 2.0 + off)
                bx, bz = x + nx * o, z + nz * o
                bi = len(verts)
                verts.append((bx, y + base_lift, bz))
                verts.append((bx, y + base_lift + height, bz))
                uvs.append((0.0, arc / tile_m))
                uvs.append((1.0, arc / tile_m))
                ring.append((bi, bi + 1))
            for idx in range(len(ring) - 1):
                b0, t0 = ring[idx]
                b1, t1 = ring[idx + 1]
                tris.append((b0, b1, t1))
                tris.append((b0, t1, t0))
        i = j
    return {"vertices": verts, "uvs": uvs, "tris": tris}
