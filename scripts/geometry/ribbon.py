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


def road_ribbon(centerline_m: list[Vertex], widths_m: list[float], *, tile_m: float = 4.0) -> dict:
    """Sweep a drivable ribbon (1ROAD) along the centerline, offsetting ±width/2 per vertex.

    Also emits per-vertex UVs (parallel to vertices) in metres/``tile_m``: U across the width
    (±half/tile), V along the lap (cumulative arc/tile) — so a seamless asphalt tiles correctly down
    the road and a detail/markings layer can key off the same coordinates."""
    pts = centerline_m
    n = len(pts)
    closed = abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][2] - pts[-1][2]) < 1e-6
    m = n - 1 if closed else n  # unique cross-sections (drop the duplicate closing vertex)
    verts: list[Vertex] = []
    uvs: list[tuple[float, float]] = []
    arc = 0.0
    for i in range(m):
        if i > 0:
            arc += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2])
        x, y, z = pts[i]
        tx, tz = _horiz_tangent(pts, i, closed)
        nx, nz = -tz, tx  # left normal (tangent rotated +90° in X-Z)
        half = widths_m[i] / 2.0
        verts.append((x + nx * half, y, z + nz * half))  # left  -> 2i
        verts.append((x - nx * half, y, z - nz * half))  # right -> 2i+1
        uvs.append((half / tile_m, arc / tile_m))        # left
        uvs.append((-half / tile_m, arc / tile_m))       # right
    tris: list[tuple[int, int, int]] = []
    last = m if closed else m - 1
    for i in range(last):
        j = (i + 1) % m
        l0, r0, l1, r1 = 2 * i, 2 * i + 1, 2 * j, 2 * j + 1
        tris.append((l0, r0, r1))
        tris.append((l0, r1, l1))
    return {"vertices": verts, "uvs": uvs, "tris": tris}


def _road_surface_samples(centerline_m: list[Vertex], widths_m: list[float] | None):
    """Centre + both edge points per station (flat cross-section), each tagged with its lap index.
    Grading to these — not just the centreline — makes the terrain meet the road at its real edges."""
    n = len(centerline_m)
    closed = abs(centerline_m[0][0] - centerline_m[-1][0]) < 1e-6 and abs(centerline_m[0][2] - centerline_m[-1][2]) < 1e-6
    out: list[tuple[float, float, float, int]] = []
    for i, (x, y, z) in enumerate(centerline_m):
        out.append((x, y, z, i))
        if widths_m:
            tx, tz = _horiz_tangent(centerline_m, i, closed)
            nx, nz = -tz, tx
            h = widths_m[i] / 2.0
            out.append((x + nx * h, y, z + nz * h, i))
            out.append((x - nx * h, y, z - nz * h, i))
    return out, n


def conform_terrain_to_road(grid_xyz: list[list[Vertex]], centerline_m: list[Vertex],
                            widths_m: list[float] | None = None,
                            *, corridor: float = 12.0, blend: float = 12.0) -> None:
    """Grade the terrain to the road so the road never dips into it. Each grid node within
    ``corridor`` m of the road surface (centre + both edges) is pulled down to the *lowest* nearby
    road elevation; the cut then blends back to natural terrain over ``blend`` m. Mutates in place.

    Taking the minimum (not the nearest) is what guarantees the terrain never rises above the road —
    including where the route is grade-separated (one part passing under another): the under-road wins
    and the over-road floats free as a drivable bridge. For that guarantee to hold at every road point,
    ``corridor`` must exceed the terrain grid's half-diagonal — so the grid must be FINE (see
    ``upsample_grid``). A fine grid also keeps the min-cut shallow (float ≈ grade × corridor), so the
    road hugs the terrain instead of riding a fat embankment. On the coarse 40 m grid this same call
    left ~115 poke-throughs (the grass surface bulged between far nodes); at ~13 m it goes clean."""
    from collections import defaultdict
    reach = corridor + blend
    corr2 = corridor * corridor
    samples, _ = _road_surface_samples(centerline_m, widths_m)
    buckets: dict[tuple[int, int], list[tuple[float, float, float]]] = defaultdict(list)
    for x, y, z, _i in samples:
        buckets[(int(x // reach), int(z // reach))].append((x, y, z))
    for row in grid_xyz:
        for k in range(len(row)):
            gx, gy, gz = row[k]
            ci, cj = int(gx // reach), int(gz // reach)
            best_d2, near_y, corr_min = 1e18, None, None
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for cx, cy, cz in buckets.get((ci + di, cj + dj), ()):
                        d2 = (gx - cx) ** 2 + (gz - cz) ** 2
                        if d2 < best_d2:
                            best_d2, near_y = d2, cy
                        if d2 <= corr2 and (corr_min is None or cy < corr_min):
                            corr_min = cy
            if near_y is None:
                continue
            target = corr_min if corr_min is not None else near_y
            d = math.sqrt(best_d2)
            if d <= corridor:
                row[k] = (gx, target, gz)
            elif d <= reach:
                t = (d - corridor) / blend
                row[k] = (gx, target * (1 - t) + gy * t, gz)


def upsample_grid(grid: list[list[float]], meta: dict, factor: int) -> tuple[list[list[float]], dict]:
    """Bilinearly upsample the raw DEM height grid by an integer factor (finer spacing). Free (no
    re-sampling) and lossless on gentle terrain — a fine grid lets ``conform_terrain_to_road`` hug the
    road with a small corridor and little float, instead of fighting 40 m facets. Returns (grid, meta)
    with nx/ny/spacing_m updated; the lon/lat bbox is unchanged so projection stays identical."""
    if factor <= 1:
        return grid, meta
    ny, nx = len(grid), len(grid[0])
    big_y, big_x = (ny - 1) * factor + 1, (nx - 1) * factor + 1
    out = [[0.0] * big_x for _ in range(big_y)]
    for jj in range(big_y):
        fy = jj / factor
        j0 = min(ny - 1, int(fy)); j1 = min(ny - 1, j0 + 1); ty = fy - j0
        for ii in range(big_x):
            fx = ii / factor
            i0 = min(nx - 1, int(fx)); i1 = min(nx - 1, i0 + 1); tx = fx - i0
            a = grid[j0][i0] * (1 - tx) + grid[j0][i1] * tx
            b = grid[j1][i0] * (1 - tx) + grid[j1][i1] * tx
            out[jj][ii] = a * (1 - ty) + b * ty
    meta2 = dict(meta)
    meta2["nx"], meta2["ny"], meta2["spacing_m"] = big_x, big_y, meta["spacing_m"] / factor
    return out, meta2


def grass_terrain(grid_xyz: list[list[Vertex]], *, tile_m: float = 6.0) -> dict:
    """Triangulate the projected terrain grid (ny rows × nx cols of (x,y,z)) into the GRASS mesh.
    UVs are world-planar (x/tile, z/tile) so the grass texture tiles seamlessly over any terrain."""
    ny = len(grid_xyz)
    nx = len(grid_xyz[0])
    verts = [grid_xyz[j][i] for j in range(ny) for i in range(nx)]
    uvs = [(grid_xyz[j][i][0] / tile_m, grid_xyz[j][i][2] / tile_m) for j in range(ny) for i in range(nx)]
    tris: list[tuple[int, int, int]] = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i
            tris.append((a, b, c))
            tris.append((a, c, d))
    return {"vertices": verts, "uvs": uvs, "tris": tris}
