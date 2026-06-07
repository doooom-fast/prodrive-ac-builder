"""Build the road ribbon (1ROAD) and the grass heightfield mesh (GRASS).

The ribbon is swept along the projected centerline using per-vertex width; the grass mesh is the
triangulated terrain grid. All inputs are local ENU metres (X-east, Y-up, Z-north). Meshes are
returned as ``{"vertices": [(x,y,z)...], "tris": [(a,b,c)...]}`` with 0-based triangle indices.
"""

from __future__ import annotations

import math

Vertex = tuple[float, float, float]


def _horiz_tangent(pts: list[Vertex], i: int, closed: bool) -> tuple[float, float]:
    """Unit tangent in the horizontal X-Z plane at vertex i (centered difference)."""
    n = len(pts)
    a = pts[(i - 1) % n] if closed else pts[max(0, i - 1)]
    b = pts[(i + 1) % n] if closed else pts[min(n - 1, i + 1)]
    dx, dz = b[0] - a[0], b[2] - a[2]
    L = math.hypot(dx, dz) or 1.0
    return dx / L, dz / L


def road_ribbon(centerline_m: list[Vertex], widths_m: list[float]) -> dict:
    """Sweep a drivable ribbon (1ROAD) along the centerline, offsetting ±width/2 per vertex."""
    pts = centerline_m
    n = len(pts)
    closed = abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][2] - pts[-1][2]) < 1e-6
    m = n - 1 if closed else n  # unique cross-sections (drop the duplicate closing vertex)
    verts: list[Vertex] = []
    for i in range(m):
        x, y, z = pts[i]
        tx, tz = _horiz_tangent(pts, i, closed)
        nx, nz = -tz, tx  # left normal (tangent rotated +90° in X-Z)
        half = widths_m[i] / 2.0
        verts.append((x + nx * half, y, z + nz * half))  # left  -> 2i
        verts.append((x - nx * half, y, z - nz * half))  # right -> 2i+1
    tris: list[tuple[int, int, int]] = []
    last = m if closed else m - 1
    for i in range(last):
        j = (i + 1) % m
        l0, r0, l1, r1 = 2 * i, 2 * i + 1, 2 * j, 2 * j + 1
        tris.append((l0, r0, r1))
        tris.append((l0, r1, l1))
    return {"vertices": verts, "tris": tris}


def grass_terrain(grid_xyz: list[list[Vertex]]) -> dict:
    """Triangulate the projected terrain grid (ny rows × nx cols of (x,y,z)) into the GRASS mesh."""
    ny = len(grid_xyz)
    nx = len(grid_xyz[0])
    verts = [grid_xyz[j][i] for j in range(ny) for i in range(nx)]
    tris: list[tuple[int, int, int]] = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i
            tris.append((a, b, c))
            tris.append((a, c, d))
    return {"vertices": verts, "tris": tris}
