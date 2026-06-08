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


def corner_kerbs(centerline_m: list[Vertex], widths_m: list[float], *, thr: float = 0.007,
                 min_run: int = 5, kerb_w: float = 0.9, lift: float = 0.05, sharp: float = 0.05,
                 apex_reach: float = 0.7, tile_m: float = 1.0) -> dict:
    """Red/white kerbs at corners, on the TRACK side of the edge (a clipped rumble, not a strip out
    in the grass). Two kinds, chosen by how tight the corner is:
      • tight junctions (peak curvature >= ``sharp``) -> a single triangular apex kerb on the inside;
      • high-speed sweepers (gentler, sustained)      -> kerb strips on BOTH the inside and outside.
    The low ``thr`` catches the fast curves (Sand Creek / Colorado / 46th); build_mesh lifts the mesh
    with the road. UVs: U across the 0->1 width, V along the run."""
    pts = centerline_m
    n = len(pts)
    rate = _smooth(_turn_rate(pts))
    verts: list[Vertex] = []
    uvs: list[tuple[float, float]] = []
    tris: list[tuple[int, int, int]] = []

    def strip(run: list[int], side: float) -> None:
        base = len(verts)
        arc = 0.0
        for idx, k in enumerate(run):
            x, y, z = pts[k]
            if idx > 0:
                p = pts[run[idx - 1]]
                arc += math.hypot(x - p[0], z - p[2])
            inx, inz = _inside_normal(pts, k, side)
            half = widths_m[k] / 2.0
            verts.append((x + inx * half, y + lift, z + inz * half))                       # road edge
            verts.append((x + inx * (half - kerb_w), y + lift, z + inz * (half - kerb_w)))  # onto track
            uvs.append((0.0, arc / tile_m))
            uvs.append((1.0, arc / tile_m))
        for idx in range(len(run) - 1):
            a0, a1 = base + 2 * idx, base + 2 * idx + 1
            b0, b1 = base + 2 * (idx + 1), base + 2 * (idx + 1) + 1
            tris.append((a0, a1, b1))
            tris.append((a0, b1, b0))

    def apex(run: list[int], side: float) -> None:  # one clean triangle at the inside of the junction
        base = len(verts)
        for k, inset, uv in ((run[0], 0.0, (0.0, 0.0)),
                             (run[len(run) // 2], kerb_w + apex_reach, (0.5, 1.0)),
                             (run[-1], 0.0, (1.0, 0.0))):
            x, y, z = pts[k]
            inx, inz = _inside_normal(pts, k, side)
            half = widths_m[k] / 2.0
            verts.append((x + inx * (half - inset), y + lift, z + inz * (half - inset)))
            uvs.append(uv)
        tris.append((base, base + 1, base + 2))

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
        side = 1.0 if rate[run[len(run) // 2]] > 0 else -1.0  # inside of the turn
        if peak >= sharp and len(run) >= 2:
            apex(run, side)         # tight junction -> triangular apex kerb
        elif len(run) >= min_run:
            strip(run, side)        # sweeper -> inside kerb ...
            strip(run, -side)       # ... and outside kerb
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
