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


def corner_kerbs(centerline_m: list[Vertex], widths_m: list[float], *,
                 thr: float = 0.018, min_run: int = 6, kerb_w: float = 1.3, lift: float = 0.08,
                 tile_m: float = 1.0) -> dict:
    """Return a single merged kerb mesh ({'vertices','uvs','tris'}) covering all detected corners.
    UVs run U across the strip (0 road-edge → 1 outer) and V along the run (distance/``tile_m``) so a
    red/white kerb texture stripes correctly along each corner."""
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
            side = 1.0 if rate[(i + j) // 2] > 0 else -1.0  # inside of the turn
            base = len(verts)
            run = list(range(i, j))
            d = 0.0
            for idx, k in enumerate(run):
                x, y, z = pts[k]
                if idx > 0:
                    p = pts[run[idx - 1]]
                    d += math.hypot(x - p[0], z - p[2])
                # tangent → left normal (nx, nz)
                a = pts[max(0, k - 1)]; b = pts[min(n - 1, k + 1)]
                tx, tz = b[0] - a[0], b[2] - a[2]
                tl = math.hypot(tx, tz) or 1e-6
                nx, nz = -tz / tl, tx / tl
                half = widths_m[k] / 2.0
                inner = (x + nx * half * side, y, z + nz * half * side)            # road edge
                outer = (x + nx * (half + kerb_w) * side, y + lift, z + nz * (half + kerb_w) * side)
                verts.append(inner)
                verts.append(outer)
                uvs.append((0.0, d / tile_m))
                uvs.append((1.0, d / tile_m))
            for m in range(len(run) - 1):
                a0, a1 = base + 2 * m, base + 2 * m + 1
                b0, b1 = base + 2 * (m + 1), base + 2 * (m + 1) + 1
                tris.append((a0, a1, b1))
                tris.append((a0, b1, b0))
        i = j
    return {"vertices": verts, "uvs": uvs, "tris": tris}
