"""Build the freeroam NETWORK mesh: sweep every edge of data/network.geojson into a 1ROAD ribbon,
lay a conformed GRASS terrain under the whole thing, and place AC dummies at the childhood home.

Unlike build_mesh.py (one closed loop + connectors), this handles a branching street graph spanning
~22 km. Because AC meshes are capped at 65,535 verts (16-bit indices), both the road and the terrain
are TILED into multiple sub-objects (1ROAD_partNN / 1GRASS_rCC) each under the cap.

Outputs (data/): track.obj + track.mtl (1ROAD_* / 1GRASS_* groups), dummies.json, network_mesh.svg.
Consumes: network.geojson (geometry+class+width), network.elevation.json (per-edge z), heightfield.npy.
Writes back true_north_rotation_deg = 0 (the local frame is true-north aligned).

Run:  python -m scripts.geometry.build_network_mesh projects/san-diego-cruise
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.config import load_config  # noqa: E402
from scripts.geometry import ribbon  # noqa: E402
from scripts.geometry.build_mesh import read_npy, project_grid, write_obj, orient_up  # noqa: E402
from scripts.geometry.projection import _meters_per_degree, centroid  # noqa: E402

Vertex = tuple[float, float, float]
ROAD_LIFT_M = 0.12
GRASS_CLEARANCE_M = 0.30
# The kn5 exporter expands every mesh to ~3 unique verts PER TRIANGLE (per-corner normals/uvs), then
# AUTO-SPLITS any mesh whose expanded verts exceed 65,535 — and names BOTH halves the same, producing
# DUPLICATE node names. AC keys physical meshes by name, so a duplicate-named ground mesh gets dropped
# from collision -> the car falls through. So cap every emitted mesh by TRIANGLES (3*tris < 65,535 ->
# tris < 21,845) to guarantee the exporter never splits and every name stays unique.
TRI_CAP = 21000
GRASS_TILE = 95            # cells/tile -> 2*95^2 = 18,050 tris (< TRI_CAP, no split)
FREEWAY_CLS = {"motorway", "trunk"}


def _doubleside(m: dict) -> dict:
    """Make a ground mesh DOUBLE-SIDED (append reversed-winding tris). AC renders + collides on ONE
    side keyed to winding, so a single-sided ground wound the wrong way is an invisible backface with
    no top collision (the car falls through). The environment props that DID render are double-sided —
    so doubling the road/grass/terrain makes them render and collide regardless of winding."""
    m["tris"] = list(m["tris"]) + [(a, c, b) for a, b, c in m["tris"]]
    return m


def _merge(meshes: list[dict]) -> dict:
    """Concatenate ribbon meshes (vertices/uvs/tris) into one, offsetting indices."""
    V: list = []; U: list = []; T: list = []
    for m in meshes:
        off = len(V)
        V.extend(m["vertices"])
        U.extend(m.get("uvs") or [(0.0, 0.0)] * len(m["vertices"]))
        T.extend((a + off, b + off, c + off) for a, b, c in m["tris"])
    return {"vertices": V, "uvs": U, "tris": T}


def _pack_groups(prefix: str, material: str, meshes: list[tuple[str, dict]]) -> list[tuple[str, str, dict]]:
    """Bin (name, mesh) meshes into merged groups each under TRI_CAP triangles, with a UNIQUE name per
    group, so the kn5 exporter never auto-splits (which would duplicate names and break collision)."""
    groups = []
    bucket: list[dict] = []
    tcount = 0
    part = 0
    for _name, m in meshes:
        nt = len(m["tris"])
        if nt > TRI_CAP:                       # a single oversize mesh: split it into uniquely-named subs
            for sub in _split_ribbon(m):
                groups.append((f"{prefix}_{part}", material, sub)); part += 1
            continue
        if tcount + nt > TRI_CAP and bucket:
            groups.append((f"{prefix}_{part}", material, _merge(bucket))); part += 1
            bucket, tcount = [], 0
        bucket.append(m); tcount += nt
    if bucket:
        groups.append((f"{prefix}_{part}", material, _merge(bucket)))
    return groups


def _split_ribbon(m: dict) -> list[dict]:
    """Split one long ribbon (cross-sections of 2 verts) into chunks under TRI_CAP triangles, sharing
    the seam row so there's no gap between chunks."""
    V, U, T = m["vertices"], m.get("uvs") or [], m["tris"]
    rows = len(V) // 2
    max_rows = max(2, TRI_CAP // 2)            # 2 tris per row pair
    out = []
    start = 0
    while start < rows - 1:
        end = min(rows, start + max_rows)
        vs = V[start * 2:end * 2]
        us = U[start * 2:end * 2] if U else None
        ts = []
        r = end - start
        for i in range(r - 1):
            l0, r0, l1, r1 = 2 * i, 2 * i + 1, 2 * (i + 1), 2 * (i + 1) + 1
            ts.append((l0, r0, r1)); ts.append((l0, r1, l1))
        out.append({"vertices": vs, "uvs": us, "tris": ts})
        start = end - 1
    return out


def _grass_tiles(grid_xyz: list[list[Vertex]], *, tile_m: float = 8.0, is_lawn=None) -> list[tuple[str, dict]]:
    """Tile the conformed terrain grid into <VCAP sub-meshes. Adjacent tiles share coincident seam
    verts (identical coords) so there is no hole between them. World-planar UVs tile seamlessly.

    Each tile is tagged 1LAWN (irrigated suburban green) or 1GRASS (dry chaparral) by ``is_lawn(cx, cz,
    relief_m)`` — neighbourhood tiles on gentle ground read green; canyon/hill/freeway-cut tiles read dry."""
    ny = len(grid_xyz); nx = len(grid_xyz[0])
    tiles = []
    for j0 in range(0, ny - 1, GRASS_TILE):
        for i0 in range(0, nx - 1, GRASS_TILE):
            j1 = min(ny, j0 + GRASS_TILE + 1); i1 = min(nx, i0 + GRASS_TILE + 1)
            sub = [grid_xyz[j][i0:i1] for j in range(j0, j1)]
            tny, tnx = len(sub), len(sub[0])
            verts = [sub[j][i] for j in range(tny) for i in range(tnx)]
            uvs = [(sub[j][i][0] / tile_m, sub[j][i][2] / tile_m) for j in range(tny) for i in range(tnx)]
            # classify EACH triangle (≈27 m) as lawn vs dry by its centroid + local slope, so the
            # green/dry boundary follows the neighbourhood, not the coarse 3 km tile.
            buckets = {"1LAWN": [], "1GRASS": []}
            for j in range(tny - 1):
                for i in range(tnx - 1):
                    a, b, c, d = j * tnx + i, j * tnx + i + 1, (j + 1) * tnx + i + 1, (j + 1) * tnx + i
                    for tri in ((a, b, c), (a, c, d)):
                        vs = [verts[t] for t in tri]
                        cx = sum(v[0] for v in vs) / 3; cz = sum(v[2] for v in vs) / 3
                        rel = max(v[1] for v in vs) - min(v[1] for v in vs)
                        key = "1LAWN" if (is_lawn and is_lawn(cx, cz, rel * 6)) else "1GRASS"
                        buckets[key].append(tri)
            for prefix, tris in buckets.items():
                if not tris:
                    continue
                used = sorted({t for tri in tris for t in tri})
                remap = {old: k for k, old in enumerate(used)}
                tiles.append((f"{prefix}_{j0}_{i0}", {
                    "vertices": [verts[u] for u in used],
                    "uvs": [uvs[u] for u in used],
                    "tris": [(remap[a], remap[b], remap[c]) for a, b, c in tris]}))
    return tiles


def _skirt(grid_xyz: list[list[Vertex]], *, skirt_m: float = 800.0) -> dict:
    """A flat low catch-floor ring extruded outward from the grid border (so you never fall off world)."""
    ny = len(grid_xyz); nx = len(grid_xyz[0])
    low = min(v[1] for row in grid_xyz for v in row) - 8.0
    perim: list[tuple[Vertex, float, float]] = []
    for i in range(nx):              perim.append((grid_xyz[0][i], 0.0, skirt_m))
    for j in range(1, ny):           perim.append((grid_xyz[j][nx - 1], skirt_m, 0.0))
    for i in range(nx - 2, -1, -1):  perim.append((grid_xyz[ny - 1][i], 0.0, -skirt_m))
    for j in range(ny - 2, 0, -1):   perim.append((grid_xyz[j][0], -skirt_m, 0.0))
    verts: list[Vertex] = []; tris = []
    P = len(perim)
    for (x, y, z), dx, dz in perim:
        verts.append((x, y, z)); verts.append((x + dx, low, z + dz))
    for k in range(P):
        a0, a1 = 2 * k, 2 * k + 1
        b0, b1 = 2 * ((k + 1) % P), 2 * ((k + 1) % P) + 1
        tris.append((a0, a1, b1)); tris.append((a0, b1, b0))
    return {"vertices": verts, "tris": tris}


def _viaduct_lift(pts, terr_y, *, smooth_win=60, max_lift=26.0, taper_frac=0.16, base_lift=0.0):
    """Lift a freeway edge onto an elevated deck. Two components: (1) BRIDGE — ride a smoothed profile
    over canyon dips; (2) BASE — a constant Shutoko-style elevation so the expressway runs up on a deck
    even over flat ground. Both tapered to 0 at the ends so the edge still meets its junctions at grade
    (ramps connect there). Returns a per-vertex lift[]."""
    n = len(pts)
    natural = [p[1] for p in pts]
    half = smooth_win // 2
    smooth = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        smooth.append(sum(natural[lo:hi]) / (hi - lo))
    lift = [min(max_lift, base_lift + max(0.0, smooth[i] - natural[i])) for i in range(n)]
    # taper the ends to 0 so junctions stay at grade
    t = max(1, int(n * taper_frac))
    for i in range(n):
        f = min(1.0, i / t, (n - 1 - i) / t)
        lift[i] *= f
    return lift


def _viaduct_struct(pts, terr_y, half, *, pier_step=24.0, gap_min=3.0, deck_thick=0.9, pier_w=1.5):
    """Concrete viaduct structure under a lifted freeway: an underside slab + square piers down to the
    ground every ~pier_step where the deck clears the terrain by gap_min. pts are the LIFTED deck pts."""
    import math as _m
    V, T = [], []

    def quad(a, b, c, d):
        o = len(V); V.extend([a, b, c, d]); T.extend([(o, o + 1, o + 2), (o, o + 2, o + 3)])

    def column(cx, cz, y0, y1):
        h = pier_w / 2
        c = [(cx - h, cz - h), (cx + h, cz - h), (cx + h, cz + h), (cx - h, cz + h)]
        o = len(V)
        V.extend([(x, y0, z) for x, z in c] + [(x, y1, z) for x, z in c])
        for k in range(4):
            j = (k + 1) % 4
            T.extend([(o + k, o + j, o + j + 4), (o + k, o + j + 4, o + k + 4)])
    rows = []
    for i in range(len(pts)):
        x, y, z = pts[i]
        a = pts[max(0, i - 1)]; b = pts[min(len(pts) - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]; tl = _m.hypot(tx, tz) or 1.0
        nx, nz = -tz / tl, tx / tl
        rows.append(((x + nx * half, y - deck_thick, z + nz * half),
                     (x - nx * half, y - deck_thick, z - nz * half), (x, y, z)))
    for k in range(len(rows) - 1):       # underside slab
        L0, R0, _ = rows[k]; L1, R1, _ = rows[k + 1]
        quad(R0, L0, L1, R1)
    acc = pier_step
    for i in range(len(pts)):
        if i > 0:
            acc += _m.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2])
        x, y, z = pts[i]
        gy = terr_y(x, z)
        if y - gy > gap_min and acc >= pier_step:
            acc = 0.0
            column(x, z, gy - 0.5, y - deck_thick)
    return {"vertices": V, "tris": T}


def build(project_dir: str | Path) -> dict:
    proj = Path(project_dir)
    data = proj / "data"
    cfg = load_config(proj)
    mirror_x = bool(cfg.raw.get("mirror_x", True))

    fc = json.loads((data / "network.geojson").read_text())
    F = fc["features"]
    elev = json.loads((data / "network.elevation.json").read_text())
    zmap = {e["id"]: e["z_smooth_m"] for e in elev["edges"]}

    # origin = centroid of ALL edge vertices; elev0 = min z (so Y >= 0)
    all_ll = [(lon, lat) for f in F for lon, lat in f["geometry"]["coordinates"]]
    origin = centroid(all_ll)
    elev0 = min(min(z) for z in zmap.values())
    lon0, lat0 = origin
    m_lon, m_lat = _meters_per_degree(lat0)
    sx = -1.0 if mirror_x else 1.0

    def to_local(lon, lat, z):
        return (sx * (lon - lon0) * m_lon, z - elev0, (lat - lat0) * m_lat)

    # viaduct knobs (config-driven): base_lift = constant Shutoko-style deck height even over flat ground;
    # bridge component adds more over canyon dips; both taper to grade at junctions.
    _vcfg = (cfg.raw.get("scenery", {}) or {}).get("viaduct", {}) or {}
    via_base = float(_vcfg.get("base_lift_m", 0.0))
    via_max = float(_vcfg.get("max_lift_m", 26.0))
    via_win = int(_vcfg.get("smooth_win", 60))
    via_taper = float(_vcfg.get("taper_frac", 0.16))

    # --- terrain sampler (local, mirror-aware) so freeway edges can ride an elevated deck over canyons ---
    raw_grid = read_npy(data / "heightfield.npy")
    raw_meta = json.loads((data / "heightfield.meta.json").read_text())
    _s, _w, _n, _e = raw_meta["bbox_swne"]; _nx, _ny, _sp = raw_meta["nx"], raw_meta["ny"], raw_meta["spacing_m"]
    _gy = _sp / 111_000.0; _gx = _sp / (111_000.0 * math.cos(math.radians((_s + _n) / 2)))

    def terr_y(x, z):
        lon = lon0 + sx * x / m_lon; lat = lat0 + z / m_lat
        j = min(_ny - 1, max(0, int(round((_n - lat) / _gy))))
        i = min(_nx - 1, max(0, int(round((lon - _w) / _gx))))
        return raw_grid[j][i] - elev0

    # --- sweep each edge into a ribbon (freeway edges lifted onto a viaduct deck where they bridge dips) ---
    road_meshes: list[tuple[str, dict]] = []
    edge_local: list[tuple[dict, list[Vertex], float]] = []  # (props, AT-GRADE pts, width) for conform+dummies
    viaduct_meshes: list[dict] = []
    viaduct_profiles: dict[str, list[float]] = {}   # edge_id -> per-vertex lift (shared with build_network_env)
    for f in F:
        c = f["geometry"]["coordinates"]
        z = zmap.get(f["properties"]["id"]) or [0.0] * len(c)
        if len(z) != len(c):  # safety: pad/truncate
            z = (z + [z[-1]] * len(c))[:len(c)]
        pts = [to_local(lon, lat, zz) for (lon, lat), zz in zip(c, z)]
        w = float(f["properties"].get("width_m") or cfg.default_width_m)
        if len(pts) < 2:
            continue
        is_fw = f["properties"].get("road_class") in FREEWAY_CLS
        deck_pts = pts
        if is_fw:
            lift = _viaduct_lift(pts, terr_y, base_lift=via_base, max_lift=via_max,
                                 smooth_win=via_win, taper_frac=via_taper)
            if max(lift) > 1.0:
                deck_pts = [(x, y + lift[i], z2) for i, (x, y, z2) in enumerate(pts)]
                viaduct_meshes.append(_viaduct_struct(deck_pts, terr_y, w / 2.0))
                viaduct_profiles[str(f["properties"]["id"])] = [round(v, 2) for v in lift]
        rib = ribbon.road_ribbon(deck_pts, [w] * len(deck_pts), tile_m=8.0)
        rib["vertices"] = [(x, y + ROAD_LIFT_M, z2) for x, y, z2 in rib["vertices"]]
        orient_up(rib)
        road_meshes.append((f"e{f['properties']['id']}", rib))
        edge_local.append((f["properties"], pts, w))   # AT-GRADE pts: terrain conforms to the ground, not the deck

    # --- terrain grid: project, upsample for road-hugging, conform to ALL edges (at-grade) ---
    grid, meta = ribbon.upsample_grid(raw_grid, raw_meta, 2)   # 55 m -> ~27 m
    grid_xyz = project_grid(grid, meta, origin, elev0, mirror_x=mirror_x)
    # conform: grade terrain to the nearest road sample across the whole network. corridor must exceed
    # the grid half-diagonal (~19 m at 27 m spacing); 22 m keeps near-road nodes pinned to road height.
    extra = [(p, [w] * len(p)) for _pr, p, w in edge_local]
    main_pts, main_w = (extra[0][0], extra[0][1]) if extra else ([], [])
    ribbon.conform_terrain_to_road(grid_xyz, main_pts, main_w, corridor=22.0, blend=26.0,
                                   extra_roads=extra[1:], clearance=GRASS_CLEARANCE_M)

    # green-vs-dry classifier: a tile is irrigated LAWN if it sits near a SURFACE street (not just a
    # freeway) on gentle ground; canyon/hill/freeway-cut tiles stay dry chaparral. Spatial-hash the
    # surface-street vertices so the test is O(1) per tile.
    from collections import defaultdict
    SCELL = 80.0
    street_h: dict = defaultdict(list)
    for pr, p, _w in edge_local:
        if pr.get("road_class") in FREEWAY_CLS:
            continue
        for x, _y, z in p:
            street_h[(int(x // SCELL), int(z // SCELL))].append((x, z))

    def is_lawn(cx, cz, relief):
        if relief > 16.0:                 # steep tile = hillside/canyon -> dry
            return False
        ci, cj = int(cx // SCELL), int(cz // SCELL)
        for di in range(-2, 3):           # within ~160 m of a surface street -> neighbourhood -> green
            for dj in range(-2, 3):
                for sx2, sz2 in street_h.get((ci + di, cj + dj), ()):
                    if (cx - sx2) ** 2 + (cz - sz2) ** 2 < 160.0 * 160.0:
                        return True
        return False

    # OCEAN BASIN: 3DEP returns nodata over water (filled by interpolation -> spurious "land" at the
    # coast). Carve any terrain west of the coast longitude down below sea level so the ocean plane
    # (build_network_env) reads as water, not a flat plain. real-lon = lon0 + sx*x/m_lon.
    _oc = (cfg.raw.get("scenery", {}) or {}).get("ocean", {}) or {}
    if _oc.get("enabled"):
        coast_lon = float(_oc.get("lon_from", -117.238))
        sea_local = float(_oc.get("sea_level_m", 0.0)) - elev0 - 4.0
        for row in grid_xyz:
            for k in range(len(row)):
                gx, gy, gz = row[k]
                lon = lon0 + sx * gx / m_lon
                if lon < coast_lon:                  # west of the coast -> ocean floor
                    row[k] = (gx, min(gy, sea_local), gz)

    grass_tiles = _grass_tiles(grid_xyz, is_lawn=is_lawn)
    for _n, g in grass_tiles:
        orient_up(g)
    skirt = _skirt(grid_xyz)
    orient_up(skirt)

    # viaduct structure (concrete underside slab + piers) — double-sided (seen from below), HWYSTRUCT
    # maps to the concrete building texture in pbr.py. Packed under the vertex cap.
    via_groups = []
    if viaduct_meshes:
        for m in viaduct_meshes:
            m["tris"] = m["tris"] + [(a, c, b) for a, b, c in m["tris"]]   # double-side
            m["uvs"] = [(0.0, 0.0)] * len(m["vertices"])
        via_groups = _pack_groups("HWYSTRUCT_via", "concrete", [(f"v{i}", m) for i, m in enumerate(viaduct_meshes)])

    # --- pack under the vertex cap ---
    groups: list[tuple[str, str, dict]] = []
    groups += [(n, ("lawn" if n.startswith("1LAWN") else "grass"), g) for n, g in grass_tiles]
    groups.append(("1GRASS_skirt", "grass", skirt))
    groups += _pack_groups("1ROAD_part", "road", road_meshes)
    groups += via_groups

    nv, nf = write_obj(data / "track.obj", "track.mtl", groups)
    _write_mtl(data / "track.mtl")

    dummies = _freeroam_dummies(cfg, edge_local, to_local)
    (data / "dummies.json").write_text(json.dumps(dummies, indent=1), encoding="utf-8")
    # share the viaduct lift so build_network_env raises guardrails/poles/gantries onto the deck
    (data / "network.viaduct.json").write_text(json.dumps(viaduct_profiles), encoding="utf-8")

    cfg.write_back(true_north_rotation_deg=0.0)
    _write_local_meta(data, origin, elev0, mirror_x, len(F))

    road_groups = sum(1 for g in groups if g[0].startswith("1ROAD"))
    grass_groups = sum(1 for g in groups if g[0].startswith("1GRASS"))
    stats = {"edges": len(road_meshes), "vertices": nv, "triangles": nf,
             "road_groups": road_groups, "grass_groups": grass_groups, "viaducts": len(viaduct_meshes),
             "viaduct_groups": len(via_groups), "grid": f"{meta['nx']}x{meta['ny']}", "dummies": len(dummies),
             "origin_lonlat": [round(lon0, 6), round(lat0, 6)], "elev0_m": round(elev0, 1)}
    print("network mesh:", json.dumps(stats))
    return stats


def _freeroam_dummies(cfg, edge_local, to_local) -> dict[str, list[float]]:
    """Spawn the car SOLIDLY on a normal street near the childhood home, facing down the road.

    Must land on a continuous road ribbon: NOT at an edge tip (the ragged end of a ribbon — the car
    drops through there), NOT on a freeway (could be an elevated viaduct), and ABOVE the road surface
    (the ribbon sits ROAD_LIFT_M above the centreline + a spawn clearance, so the car drops onto it
    rather than spawning embedded under the one-sided collision plane)."""
    hl = cfg.location
    home = to_local(hl["lon"], hl["lat"], 0.0)
    SPAWN_CLEAR = 0.6   # car origin this far ABOVE the road surface -> settles down onto solid road

    # nearest INTERIOR vertex of a non-freeway edge (>= 12 pts so there's a solid mid-section)
    best_pts = best_i = None; best_d = 1e18; best_w = 9.0
    for pr, pts, w in edge_local:
        if pr.get("road_class") in FREEWAY_CLS or len(pts) < 12:
            continue
        lo, hi = 5, len(pts) - 6   # stay well clear of both tips
        for i in range(lo, hi):
            d = (pts[i][0] - home[0]) ** 2 + (pts[i][2] - home[2]) ** 2
            if d < best_d:
                best_d, best_pts, best_i, best_w = d, pts, i, w
    if best_pts is None:   # fallback: any edge interior
        for pr, pts, w in edge_local:
            if len(pts) < 4:
                continue
            i = len(pts) // 2
            d = (pts[i][0] - home[0]) ** 2 + (pts[i][2] - home[2]) ** 2
            if d < best_d:
                best_d, best_pts, best_i, best_w = d, pts, i, w

    sp = best_pts[best_i]
    j = min(best_i + 1, len(best_pts) - 1)
    dx, dz = best_pts[j][0] - sp[0], best_pts[j][2] - sp[2]
    L = math.hypot(dx, dz) or 1.0
    dx, dz = dx / L, dz / L
    nx, nz = -dz, dx
    y = sp[1] + ROAD_LIFT_M + SPAWN_CLEAR    # above the actual road surface
    out: dict[str, list[float]] = {}
    out["AC_START_0"] = [round(sp[0], 3), round(y, 3), round(sp[2], 3)]
    out["AC_HOTLAP_START_0"] = list(out["AC_START_0"])
    for k, ahead in ((0, 12.0), (1, 60.0)):
        gi = min(best_i + int(ahead / 4), len(best_pts) - 1)   # step along the ribbon (~4 m spacing)
        gx, gy, gz = best_pts[gi]
        gy = gy + ROAD_LIFT_M + SPAWN_CLEAR
        out[f"AC_TIME_{k}_L"] = [round(gx + nx * best_w / 2, 3), round(gy, 3), round(gz + nz * best_w / 2, 3)]
        out[f"AC_TIME_{k}_R"] = [round(gx - nx * best_w / 2, 3), round(gy, 3), round(gz - nz * best_w / 2, 3)]
    for p in range(4):
        out[f"AC_PIT_{p}"] = [round(sp[0] + nx * (best_w / 2 + 3.0 + p * 0.1), 3), round(y, 3),
                              round(sp[2] - dx * (6.0 + p * 6.0), 3)]
    return out


def _write_local_meta(data: Path, origin, elev0, mirror_x, n_edges) -> None:
    (data / "network.local.json").write_text(json.dumps({
        "frame": "ENU local meters (X=east, Y=up, Z=north), mirror_x=%s" % mirror_x,
        "origin": {"lon": origin[0], "lat": origin[1], "elev_m": round(elev0, 2)},
        "mirror_x": mirror_x, "true_north_rotation_deg": 0.0, "edge_count": n_edges,
    }), encoding="utf-8")


def _write_mtl(path: Path) -> None:
    path.write_text(
        "newmtl road\nKd 0.22 0.22 0.24\nKa 0.05 0.05 0.05\n\n"
        "newmtl grass\nKd 0.42 0.43 0.24\nKa 0.06 0.07 0.03\n\n"
        "newmtl lawn\nKd 0.30 0.42 0.20\nKa 0.05 0.07 0.03\n\n"
        "newmtl concrete\nKd 0.62 0.62 0.60\nKa 0.08 0.08 0.08\n\n"
        "newmtl kerb\nKd 0.80 0.78 0.72\nKa 0.10 0.10 0.09\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "projects/san-diego-cruise")
