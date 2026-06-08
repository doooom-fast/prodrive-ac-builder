"""Build environment placement from real OSM zones + render the fully dressed track.

Reads data/environment.geojson (zones), centerline.geojson (loop + interior connector), the projected
loop (centerline.local.json) and the heightfield, then generates, in local ENU metres:
  - the interior connector road (layout polish),
  - Sand Creek + basins as water,
  - I-70/I-270/Vasquez as raised visual highway decks,
  - tree billboards scattered in green/wetland zones,
  - streetlight posts along the lap.
Writes data/environment.obj and a dressed 3/4 render. Pure stdlib (reuses the geometry back-half).

Run:  python -m scripts.environment.build_env projects/<slug>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from scripts.config import load_config
from scripts.geometry import kerbs, ribbon
from scripts.geometry.build_mesh import ROAD_LIFT_M, project_grid, read_npy, render_iso, write_mtl, write_obj
from scripts.geometry.projection import _meters_per_degree

Vertex = tuple[float, float, float]


def _grid_sampler(grid, meta, elev0):
    s, w, n, e = meta["bbox_swne"]
    nx, ny, sp = meta["nx"], meta["ny"], meta["spacing_m"]
    midlat = (s + n) / 2
    gy = sp / 111_000.0
    gx = sp / (111_000.0 * math.cos(math.radians(midlat)))

    def y_at(lon, lat):
        j = min(ny - 1, max(0, int(round((n - lat) / gy))))
        i = min(nx - 1, max(0, int(round((lon - w) / gx))))
        return grid[j][i] - elev0
    return y_at


def _line_ribbon(line, project, half_w, y_off=0.0):
    """Sweep a flat ribbon along a projected lon/lat line."""
    pts = [project(lo, la) for lo, la in line]
    verts, tris = [], []
    m = len(pts)
    for i in range(m):
        x, y, z = pts[i]
        a = pts[max(0, i - 1)]; b = pts[min(m - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]
        tl = math.hypot(tx, tz) or 1e-6
        nx, nz = -tz / tl, tx / tl
        verts.append((x + nx * half_w, y + y_off, z + nz * half_w))
        verts.append((x - nx * half_w, y + y_off, z - nz * half_w))
    for i in range(m - 1):
        a0, a1, b0, b1 = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        tris.append((a0, a1, b1)); tris.append((a0, b1, b0))
    return {"vertices": verts, "tris": tris}


def _fan(poly, project, y_off):
    pts = [project(lo, la) for lo, la in poly]
    if len(pts) < 3:
        return {"vertices": [], "tris": []}
    pts = [(x, y + y_off, z) for x, y, z in pts]
    return {"vertices": pts, "tris": [(0, i, i + 1) for i in range(1, len(pts) - 1)]}


def _merge(meshes):
    verts, tris = [], []
    for m in meshes:
        off = len(verts)
        verts += m["vertices"]
        tris += [(a + off, b + off, c + off) for a, b, c in m["tris"]]
    return {"vertices": verts, "tris": tris}


def _pip(x, z, poly):  # ray-cast point-in-polygon (poly = [(x,z)...])
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % n]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1 + 1e-12) + x1:
            inside = not inside
    return inside


def _billboard(x, y, z, h=6.0, w=3.0):  # crude upright tree card (two tris)
    return {"vertices": [(x - w / 2, y, z), (x + w / 2, y, z), (x + w / 2, y + h, z), (x - w / 2, y + h, z)],
            "tris": [(0, 1, 2), (0, 2, 3)]}


def _post(x, y, z, h=9.0, r=0.25):  # streetlight post (thin quad)
    return {"vertices": [(x - r, y, z), (x + r, y, z), (x + r, y + h, z), (x - r, y + h, z)],
            "tris": [(0, 1, 2), (0, 2, 3)]}


def build(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    cfg = load_config(project_dir)
    local = json.loads((data / "centerline.local.json").read_text())
    origin = (local["origin"]["lon"], local["origin"]["lat"])
    elev0 = local["origin"]["elev_m"]
    loop = [tuple(p) for p in local["points_xyz_m"]]
    widths = local["widths_m"]

    grid = read_npy(data / "heightfield.npy")
    meta = json.loads((data / "heightfield.meta.json").read_text())
    y_at = _grid_sampler(grid, meta, elev0)
    m_lon, m_lat = _meters_per_degree(origin[1])

    def project(lon, lat):
        return ((lon - origin[0]) * m_lon, y_at(lon, lat), (lat - origin[1]) * m_lat)

    env = json.loads((data / "environment.geojson").read_text())["features"]
    gj = json.loads((data / "centerline.geojson").read_text())["features"]

    # --- track + interior connector ---
    grid_xyz = project_grid(grid, meta, origin, elev0)
    ribbon.conform_terrain_to_road(grid_xyz, loop)  # grade terrain to the road (no dipping)
    grass = ribbon.grass_terrain(grid_xyz)
    road = ribbon.road_ribbon(loop, widths)
    road["vertices"] = [(x, y + ROAD_LIFT_M, z) for x, y, z in road["vertices"]]
    kerb = kerbs.corner_kerbs(loop, widths)
    kerb["vertices"] = [(x, y + ROAD_LIFT_M + 0.02, z) for x, y, z in kerb["vertices"]]
    conn_feat = next((f for f in gj if f["properties"].get("kind") == "connector"), None)
    connector = (_line_ribbon(conn_feat["geometry"]["coordinates"], project, cfg.default_width_m / 2, ROAD_LIFT_M)
                 if conn_feat else {"vertices": [], "tris": []})

    # --- water (Sand Creek lines + basins) ---
    water = _merge([_line_ribbon(f["coords"], project, 4.0, -0.3) if f["kind"] == "line"
                    else _fan(f["coords"], project, -0.3)
                    for f in env if f["cls"] == "water"])
    # --- raised highway decks (visual only) ---
    highways = _merge([_line_ribbon(f["coords"], project, 8.0, 5.0) for f in env if f["cls"] == "highway"])

    # --- trees scattered in green/wetland polygons (capped) ---
    tree_meshes, ntrees = [], 0
    for f in env:
        if f["cls"] not in ("green", "wetland") or f["kind"] != "poly" or len(f["coords"]) < 3:
            continue
        poly = [(project(lo, la)[0], project(lo, la)[2]) for lo, la in f["coords"]]
        xs = [p[0] for p in poly]; zs = [p[1] for p in poly]
        step = 28.0
        gx = int((max(xs) - min(xs)) / step)
        gz = int((max(zs) - min(zs)) / step)
        for ix in range(gx + 1):
            for iz in range(gz + 1):
                x = min(xs) + ix * step + (iz % 2) * 9
                z = min(zs) + iz * step
                if ntrees < 700 and _pip(x, z, poly):
                    # local x,z -> lon,lat to sample y
                    lon = origin[0] + x / m_lon; lat = origin[1] + z / m_lat
                    tree_meshes.append(_billboard(x, y_at(lon, lat), z))
                    ntrees += 1
    trees = _merge(tree_meshes)

    # --- streetlights along the lap (~ every 48 m, on the right verge) ---
    light_meshes, nlights = [], 0
    acc = 0.0
    for i in range(1, len(loop)):
        acc += math.hypot(loop[i][0] - loop[i - 1][0], loop[i][2] - loop[i - 1][2])
        if acc >= 48.0:
            acc = 0.0
            x, y, z = loop[i]
            a, b = loop[i - 1], loop[min(len(loop) - 1, i + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]
            tl = math.hypot(tx, tz) or 1e-6
            nx, nz = -tz / tl, tx / tl
            off = widths[i] / 2 + 2.0
            light_meshes.append(_post(x - nx * off, y, z - nz * off))
            nlights += 1
    lights = _merge(light_meshes)

    # --- write environment OBJ + dressed render ---
    write_obj(data / "environment.obj", "environment.mtl",
              [("WATER", "grass", water), ("HIGHWAY_visual", "road", highways),
               ("1ROAD_connector", "road", connector), ("TREES", "grass", trees), ("LIGHTS", "road", lights)])
    write_mtl(data / "environment.mtl")
    render_iso([("grass", (0.30, 0.47, 0.22), grass), ("water", (0.16, 0.45, 0.74), water),
                ("highway", (0.40, 0.40, 0.44), highways), ("road", (0.82, 0.83, 0.86), road),
                ("connector", (0.74, 0.76, 0.80), connector), ("kerb", (0.88, 0.24, 0.20), kerb),
                ("trees", (0.18, 0.42, 0.16), trees), ("lights", (0.95, 0.85, 0.35), lights)],
               {}, data / "dressed_render.svg")

    return {"connector_pts": len(connector["vertices"]) // 2, "water_tris": len(water["tris"]),
            "highway_tris": len(highways["tris"]), "trees": ntrees, "streetlights": nlights,
            "render": str(data / "dressed_render.svg")}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.environment.build_env <project-dir>")
    stats = build(sys.argv[1])
    print("wrote data/environment.obj + dressed_render.svg")
    for k, v in stats.items():
        if k != "render":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
