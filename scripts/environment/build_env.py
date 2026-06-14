"""Build the full environment layer from real OSM data + render the dressed track.

Reads data/environment.geojson (zones), scenery.geojson (detail features), buildings.geojson,
the projected loop and the heightfield, then generates — in local ENU metres — everything around
the racing surface:

  water, elevated freeways (decks/skirts/piers/gantries), buildings (3 facade variants + parapets),
  trees/bush billboards (creek + zone scatter), street signs (stop/speed/curve/chevron/blades),
  traffic signals, streetlight poles + emissive heads (CSP light series), power lines, chain-link
  fences, jersey walls (1WALL — real collision), tire stacks, creek-bridge guardrails, storage
  tanks, railways, crosswalks, billboards, the start gantry and a mountain-horizon ring.

Writes data/environment.obj + a dressed 3/4 render. Pure stdlib.

Run:  python -m scripts.environment.build_env projects/<slug>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from scripts.config import load_config
from scripts.environment import buildings, scenery
from scripts.geometry import kerbs, ribbon
from scripts.geometry.build_mesh import ROAD_LIFT_M, orient_up, project_grid, read_npy, render_iso, write_obj
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


def _line_ribbon(line, project, half_w, y_off=0.0, *, up: bool = True):
    """Sweep a flat ribbon along a projected lon/lat line (up-facing by default)."""
    pts = [project(lo, la) for lo, la in line]
    verts, tris = [], []
    m = len(pts)
    for i in range(m):
        x, y, z = pts[i]
        a = pts[max(0, i - 1)]
        b = pts[min(m - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]
        tl = math.hypot(tx, tz) or 1e-6
        nx, nz = -tz / tl, tx / tl
        verts.append((x + nx * half_w, y + y_off, z + nz * half_w))
        verts.append((x - nx * half_w, y + y_off, z - nz * half_w))
    for i in range(m - 1):
        a0, a1, b0, b1 = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        tris.append((a0, a1, b1))
        tris.append((a0, b1, b0))
    mesh = {"vertices": verts, "uvs": [(v[0] / 4, v[2] / 4) for v in verts], "tris": tris}
    return orient_up(mesh) if up else mesh


def _fan(poly, project, y_off):
    pts = [project(lo, la) for lo, la in poly]
    if len(pts) < 3:
        return {"vertices": [], "uvs": [], "tris": []}
    pts = [(x, y + y_off, z) for x, y, z in pts]
    mesh = {"vertices": pts, "uvs": [(p[0] / 4, p[2] / 4) for p in pts],
            "tris": [(0, i, i + 1) for i in range(1, len(pts) - 1)]}
    return orient_up(mesh)


def _poly_area(poly):  # |shoelace| of a [(x,z)...] footprint, in m²
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % n]
        s += x0 * z1 - x1 * z0
    return abs(s) / 2.0


def build(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    cfg = load_config(project_dir)
    env_cfg = cfg.raw.get("environment", {})
    seed = int(env_cfg.get("seed", 10))
    local = json.loads((data / "centerline.local.json").read_text())
    origin = (local["origin"]["lon"], local["origin"]["lat"])
    elev0 = local["origin"]["elev_m"]
    loop = [tuple(p) for p in local["points_xyz_m"]]
    widths = local["widths_m"]

    grid = read_npy(data / "heightfield.npy")
    meta = json.loads((data / "heightfield.meta.json").read_text())
    grid, meta = ribbon.upsample_grid(grid, meta, 3)  # 40 m → ~13 m so grading hugs the road cleanly
    y_at = _grid_sampler(grid, meta, elev0)
    m_lon, m_lat = _meters_per_degree(origin[1])

    def project(lon, lat):
        return ((lon - origin[0]) * m_lon, y_at(lon, lat), (lat - origin[1]) * m_lat)

    def ground_y(x, z):
        return y_at(origin[0] + x / m_lon, origin[1] + z / m_lat)

    env = json.loads((data / "environment.geojson").read_text())["features"]
    gj = json.loads((data / "centerline.geojson").read_text())["features"]
    scn = json.loads((data / "scenery.geojson").read_text()) if (data / "scenery.geojson").exists() else {}
    manifest_path = Path(__file__).resolve().parents[2] / "assets" / "textures" / "generated" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"atlas": {}}
    dummies = json.loads((data / "dummies.json").read_text()) if (data / "dummies.json").exists() else {}

    lap = scenery.Lap(loop, widths)
    runs = scenery.corner_runs(loop)

    # every drivable surface, for placement validation: nothing trackside may stand on tarmac —
    # including the connector road at the infield junctions (the loop's own verge maths can't
    # see it, which is how barriers ended up crossing the junction mouth)
    clearance = scenery.RoadClearance()
    clearance.add_polyline(loop, [w / 2 for w in widths])
    conn_pts: list = []
    conn_feat_pre = next((f for f in gj if f["properties"].get("kind") == "connector"), None)
    if conn_feat_pre:
        from scripts.geometry.kerbs import _fine_stations
        raw = [project(lo, la) for lo, la in conn_feat_pre["geometry"]["coordinates"]]
        conn_pts = [(x, y, z) for x, y, z, _tx, _tz, _arc in _fine_stations(raw, 4.0)]
        clearance.add_polyline(conn_pts, cfg.default_width_m / 2)

    # --- track + interior connector (render context + connector ribbon for the kn5) ---
    grid_xyz = project_grid(grid, meta, origin, elev0)
    ribbon.conform_terrain_to_road(grid_xyz, loop, widths)  # grade terrain to the road (no dipping)
    grass = ribbon.grass_terrain(grid_xyz)
    road = ribbon.road_ribbon(loop, widths)
    road["vertices"] = [(x, y + ROAD_LIFT_M, z) for x, y, z in road["vertices"]]
    kerb = kerbs.corner_kerbs(loop, widths, clearance)
    kerb["vertices"] = [(x, y + ROAD_LIFT_M + 0.02, z) for x, y, z in kerb["vertices"]]
    conn_feat = next((f for f in gj if f["properties"].get("kind") == "connector"), None)
    connector = (_line_ribbon(conn_feat["geometry"]["coordinates"], project, cfg.default_width_m / 2,
                              ROAD_LIFT_M)
                 if conn_feat else {"vertices": [], "uvs": [], "tris": []})

    # --- water (Sand Creek lines + basins) ---
    water = scenery.merge([_line_ribbon(f["coords"], project, 4.0, -0.3) if f["kind"] == "line"
                           else _fan(f["coords"], project, -0.3)
                           for f in env if f["cls"] == "water"])

    # --- elevated freeways: decks + skirts + piers + sign gantries ---
    hw = scenery.build_highways(env, project, ground_y, manifest, clearance,
                                deck_h=float(env_cfg.get("deck_height_m", 5.0)))

    # --- vegetation ---
    veg = scenery.build_vegetation(lap, env, scn, project, ground_y, seed, clearance,
                                   tree_cap=int(env_cfg.get("tree_cap", 2400)),
                                   bush_cap=int(env_cfg.get("bush_cap", 900)))

    # --- signage, signals, lights, power, fences, walls, rails… ---
    signs = scenery.build_signs(lap, runs, scn, manifest, project, seed, clearance)
    signals = scenery.build_traffic_signals(lap, scn, project, clearance)
    lights = scenery.build_streetlights(lap, clearance,
                                        spacing=float(env_cfg.get("light_spacing_m", 48.0)))
    power = scenery.build_power(scn, project, ground_y)
    fences = scenery.build_fences(lap, scn, project, ground_y)
    walls = scenery.build_walls(loop, widths, runs, clearance)
    tires = scenery.build_tirestacks(loop, widths, runs, seed, clearance)
    guards = scenery.build_guardrails(lap, env, project)
    tanks = scenery.build_tanks(scn, project, ground_y, clearance)
    rail = scenery.build_rail(scn, project, ground_y, lap)
    xwalks = scenery.build_crosswalks(lap, scn, project)
    boards = scenery.build_billboards(lap, runs, manifest, seed, clearance)
    gantry = scenery.build_start_gantry(dummies, manifest)
    xs = [p[0] for p in loop]
    zs = [p[2] for p in loop]
    horizon = scenery.build_horizon(((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2),
                                    float(env_cfg.get("horizon_radius_m", 3200.0)))

    # --- buildings from OSM footprints: zone-aware facade variants, parapets, near-lap only ---
    bld_path = data / "buildings.geojson"
    bld = json.loads(bld_path.read_text())["buildings"] if bld_path.exists() else []
    keep_r = float(env_cfg.get("building_radius_m", 330.0))
    # the GPS map decides the look: which zone polygon a building sits in picks its facade family
    zone_polys = [(f["cls"], [(project(lo, la)[0], project(lo, la)[2]) for lo, la in f["coords"]])
                  for f in env
                  if f["kind"] == "poly" and len(f["coords"]) >= 3
                  and f["cls"] in ("industrial", "commercial", "residential")]
    fam_counts = manifest.get("facades", {"ind": 6, "com": 5, "off": 3, "res": 1})
    fam_group = {"ind": "BUILDIN", "com": "BUILDCM", "off": "BUILDOF", "res": "BUILDRS"}
    wall_groups: dict = {}
    fam_stats: dict = {}
    roof_meshes = []
    nbld = 0
    n_dropped = 0
    for b in bld:
        foot = [(project(lo, la)[0], project(lo, la)[2]) for lo, la in b["coords"]]
        area = _poly_area(foot)
        if len(foot) < 3 or area < 35:  # skip tiny sheds / noise
            continue
        cx = sum(p[0] for p in foot) / len(foot)
        cz = sum(p[1] for p in foot) / len(foot)
        d, _ = lap.nearest(cx, cz, reach=max(400.0, keep_r))
        if d > keep_r:
            continue
        # obstruction audit: a building whose footprint reaches the road corridor is a crash
        # hazard — drop it (OSM slop / ribbon wider than the real street)
        probe = []
        for k in range(len(foot)):
            x0, z0 = foot[k]
            x1, z1 = foot[(k + 1) % len(foot)]
            probe += [(x0, z0), ((x0 + x1) / 2, (z0 + z1) / 2)]
        if any(not clearance.clear(px, pz, 0.5) for px, pz in probe):
            n_dropped += 1
            continue
        zone = next((cls for cls, poly in zone_polys if scenery._pip(cx, cz, poly)), None)
        fam = buildings.classify(b, area, zone)
        idx = ((int(round(cx)) * 7919) ^ (int(round(cz)) * 104729)) % max(1, int(fam_counts.get(fam, 1)))
        base = min(y_at(lo, la) for lo, la in b["coords"]) - 0.4  # sink slightly to meet the ground
        out = buildings.extrude(foot, base, b["height_m"], variant=fam)
        wall_groups.setdefault(f"{fam_group[fam]}{idx}", []).append(out["walls"])
        fam_stats[fam] = fam_stats.get(fam, 0) + 1
        roof_meshes.append(orient_up(out["roof"]))
        nbld += 1

    # --- assemble OBJ groups (chunked under the kn5 per-mesh vertex limit) ---
    groups: list[tuple[str, str, dict]] = []

    def add(name: str, mat: str, meshes, single: bool = False):
        if isinstance(meshes, dict):
            meshes = [meshes]
        meshes = [m for m in meshes if m and m["tris"]]
        if not meshes:
            return
        if single:
            for i, m in enumerate(meshes):
                groups.append((f"{name}_{i}", mat, m))
        else:
            chunks = scenery.chunk(meshes)
            for i, m in enumerate(chunks):
                groups.append((name if len(chunks) == 1 else f"{name}_{i}", mat, m))

    add("WATER", "grass", water)
    add("HIGHWAY_deck", "road", hw["decks"])
    add("HWCONC", "kerb", hw["skirts"] + hw["edges"])
    add("PIERS", "kerb", hw["piers"])
    add("GANTRYSTEEL", "kerb", hw["gantry_steel"] + boards["steel"] + gantry["steel"])
    add("ADFACE", "kerb", hw["gantry_faces"] + boards["faces"] + gantry["faces"])
    add("1ROAD_connector", "road", connector)
    for gname in sorted(wall_groups):
        add(gname, "road", wall_groups[gname])
    add("ROOFS", "road", roof_meshes)
    add("TREES", "grass", veg["trees"])
    add("BUSH", "grass", veg["bushes"])
    add("SIGNPOST", "kerb", signs["poles"] + signals["poles"])
    add("SIGNFACE", "kerb", signs["faces"])
    add("TRAFSIG", "kerb", signals["heads"])
    add("POLES", "kerb", lights["poles"])
    add("LIGHTS", "kerb", lights["heads"])
    add("WOODPOLE", "kerb", power["wood"])
    add("WIRES", "kerb", power["wires"])
    add("PYLON", "kerb", power["towers"])
    add("FENCE", "kerb", fences)
    add("1WALL_c", "kerb", walls, single=True)   # one object per corner, real collision
    add("TIRES", "kerb", tires)
    add("GUARD", "kerb", guards["rails"])
    add("GUARDPOST", "kerb", guards["posts"])
    add("TANKS", "kerb", tanks)
    add("RAILBED", "grass", rail["beds"])
    add("RAILS", "kerb", rail["rails"])
    add("CROSSWALK", "kerb", xwalks)
    add("HORIZON", "grass", horizon)

    nv, nf = write_obj(data / "environment.obj", "environment.mtl", groups)
    write_mtl(data / "environment.mtl")

    render_iso([("grass", (0.30, 0.47, 0.22), grass), ("water", (0.16, 0.45, 0.74), water),
                ("highway", (0.40, 0.40, 0.44), scenery.merge(hw["decks"])),
                ("piers", (0.55, 0.55, 0.56), scenery.merge(hw["piers"]) if hw["piers"] else scenery.empty()),
                ("buildings", (0.58, 0.55, 0.50),
                 scenery.merge([w for group in wall_groups.values() for w in group])),
                ("roofs", (0.42, 0.42, 0.45), scenery.merge(roof_meshes)),
                ("road", (0.82, 0.83, 0.86), road),
                ("connector", (0.74, 0.76, 0.80), connector),
                ("kerb", (0.88, 0.24, 0.20), kerb),
                ("walls", (0.78, 0.78, 0.76), scenery.merge(walls) if walls else scenery.empty()),
                ("tanks", (0.80, 0.79, 0.74), scenery.merge(tanks) if tanks else scenery.empty()),
                ("trees", (0.18, 0.42, 0.16), scenery.merge(veg["trees"])),
                ("bush", (0.35, 0.42, 0.20), scenery.merge(veg["bushes"]))],
               {}, data / "dressed_render.svg")

    return {"obj_vertices": nv, "obj_triangles": nf, "groups": len(groups),
            "buildings": nbld, "buildings_dropped_on_road": n_dropped,
            "building_families": ", ".join(f"{k}={v}" for k, v in sorted(fam_stats.items())),
            "trees": len(veg["trees"]), "bushes": len(veg["bushes"]),
            "sign_faces": len(signs["faces"]), "signals": len(signals["heads"]),
            "streetlights": len(lights["heads"]), "fences": len(fences), "walls": len(walls),
            "tanks": len(tanks), "render": str(data / "dressed_render.svg")}


def write_mtl(path: Path) -> None:
    path.write_text(
        "newmtl road\nKd 0.20 0.20 0.23\nKa 0.05 0.05 0.05\n\n"
        "newmtl grass\nKd 0.26 0.44 0.20\nKa 0.05 0.08 0.04\n\n"
        "newmtl kerb\nKd 0.80 0.20 0.18\nKa 0.10 0.03 0.03\n",
        encoding="utf-8",
    )


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
