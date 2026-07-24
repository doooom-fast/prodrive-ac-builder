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
CONFORM_GRADE = 0.06       # max grade for a connector ramping onto a track deck — steeper would launch the car
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


def _grass_tiles(grid_xyz: list[list[Vertex]], *, tile_m: float = 8.0, is_lawn=None,
                 keep_tile=None, pad_reject=None) -> list[tuple[str, dict]]:
    """Tile the conformed terrain grid into <VCAP sub-meshes. Adjacent tiles share coincident seam
    verts (identical coords) so there is no hole between them. World-planar UVs tile seamlessly.

    Each tile is tagged 1LAWN (irrigated suburban green) or 1GRASS (dry chaparral) by ``is_lawn(cx, cz,
    relief_m)`` — neighbourhood tiles on gentle ground read green; canyon/hill/freeway-cut tiles read dry.

    ``keep_tile(x0, z0, x1, z1)`` (tile xz bbox) prunes tiles with NO road nearby — over a long thin
    corridor (Sand Creek->Dacono) the full bounding box is mostly empty land far from any drivable road,
    so grassing it wastes ~1M triangles. Pruned tiles are >buffer from every road (undrivable), so no
    grass is lost under any road."""
    ny = len(grid_xyz); nx = len(grid_xyz[0])
    tiles = []
    for j0 in range(0, ny - 1, GRASS_TILE):
        for i0 in range(0, nx - 1, GRASS_TILE):
            j1 = min(ny, j0 + GRASS_TILE + 1); i1 = min(nx, i0 + GRASS_TILE + 1)
            sub = [grid_xyz[j][i0:i1] for j in range(j0, j1)]
            tny, tnx = len(sub), len(sub[0])
            if keep_tile is not None:   # prune far-from-road tiles (empty-middle bloat on a long corridor)
                cxs = [sub[0][0][0], sub[0][-1][0], sub[-1][0][0], sub[-1][-1][0]]
                czs = [sub[0][0][2], sub[0][-1][2], sub[-1][0][2], sub[-1][-1][2]]
                if not keep_tile(min(cxs), min(czs), max(cxs), max(czs)):
                    continue
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
                        if pad_reject is not None and pad_reject(cx, cz):
                            continue                 # inside a detailed track footprint -> drop (its own ground shows)
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


def _viaduct_struct(pts, terr_y, half, *, pier_step=24.0, gap_min=3.0, deck_thick=0.9, pier_w=1.5,
                    skip_column=None):
    """Concrete viaduct structure under a lifted freeway: an underside slab + square piers down to the
    ground every ~pier_step where the deck clears the terrain by gap_min. pts are the LIFTED deck pts.

    ``skip_column(cx, cz, y_top)`` -> True drops a pier that would stand in a road passing UNDER the deck
    (a clear span instead), so no support column spears a crossing road. Returns (mesh, placed_piers)."""
    import math as _m
    V, T = [], []
    # extend the slab one short step past BOTH ends: a ribbon tip at a junction node otherwise sits
    # exactly on (or just before) the slab's first row and misses barycentric support
    if len(pts) >= 2:
        (x0, y0, z0), (x1, y1, z1) = pts[0], pts[1]
        L0 = _m.hypot(x1 - x0, z1 - z0) or 1.0
        (xa, ya, za), (xb, yb, zb) = pts[-2], pts[-1]
        L1 = _m.hypot(xb - xa, zb - za) or 1.0
        pts = ([(x0 - (x1 - x0) / L0 * 1.2, y0, z0 - (z1 - z0) / L0 * 1.2)] + list(pts)
               + [(xb + (xb - xa) / L1 * 1.2, yb, zb + (zb - za) / L1 * 1.2)])

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
    slab_half = half + 0.4      # slab slightly proud of the deck edge (decks overhang their
    #                             structure) — an edge vert exactly on the slab's 2D hull otherwise
    #                             misses barycentric containment and voids the support exemption
    for i in range(len(pts)):
        x, y, z = pts[i]
        a = pts[max(0, i - 1)]; b = pts[min(len(pts) - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]; tl = _m.hypot(tx, tz) or 1.0
        nx, nz = -tz / tl, tx / tl
        rows.append(((x + nx * slab_half, y - deck_thick, z + nz * slab_half),
                     (x - nx * slab_half, y - deck_thick, z - nz * slab_half), (x, y, z)))
    for k in range(len(rows) - 1):       # underside slab
        L0, R0, _ = rows[k]; L1, R1, _ = rows[k + 1]
        quad(R0, L0, L1, R1)
    piers = []
    acc = pier_step
    for i in range(len(pts)):
        if i > 0:
            acc += _m.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2])
        x, y, z = pts[i]
        gy = terr_y(x, z)
        if y - gy > gap_min and acc >= pier_step:
            acc = 0.0
            if skip_column is not None and skip_column(x, z, y - deck_thick):
                continue      # a road passes under the deck here -> clear span, don't spear it
            column(x, z, gy - 0.5, y - deck_thick)
            piers.append((round(x, 2), round(z, 2), round(y - deck_thick, 2)))
    return {"vertices": V, "tris": T}, piers


def _smooth_series(vals, win):
    """Moving-average smooth a per-vertex scalar series (window = total span in vertices)."""
    n = len(vals)
    if n < 3 or win < 2:
        return list(vals)
    half = win // 2
    return [sum(vals[max(0, i - half):min(n, i + half + 1)]) /
            (min(n, i + half + 1) - max(0, i - half)) for i in range(n)]


def _layer_lift(pts, layer_profile, *, layer_h=5.5, smooth_win=28):
    """Lift a freeway edge onto its OSM bridge LAYER so it grade-separates from the road crossing beneath.
    ``layer_profile[i]`` is the integer OSM layer at vertex i (0 = at grade, 1/2/3 = stacked flyover). The
    raw ``layer*layer_h`` step is smoothed into drivable ramps but NOT tapered to 0 at the ends — a flyover
    meets its approach ramps up on the deck, not back at grade. Returns per-vertex lift in metres."""
    n = len(pts)
    if not layer_profile or len(layer_profile) != n:
        return [0.0] * n
    raw = [max(0, int(l)) * layer_h for l in layer_profile]
    if not any(raw):
        return [0.0] * n
    return _smooth_series(raw, smooth_win)


def _grade_cap_y(pts, *, max_grade=0.065):
    """Clamp a swept profile's vertex-to-vertex slope to ``max_grade`` (by real segment distance), forward
    then backward, so a lifted deck ramps up/down at a drivable grade instead of launching the car."""
    out = list(pts)
    for _ in range(2):
        for i in range(1, len(out)):
            cap = max_grade * max(0.5, math.hypot(out[i][0] - out[i - 1][0], out[i][2] - out[i - 1][2]))
            y = out[i - 1][1] + max(-cap, min(cap, out[i][1] - out[i - 1][1]))
            out[i] = (out[i][0], y, out[i][2])
        for i in range(len(out) - 2, -1, -1):
            cap = max_grade * max(0.5, math.hypot(out[i + 1][0] - out[i][0], out[i + 1][2] - out[i][2]))
            y = out[i + 1][1] + max(-cap, min(cap, out[i][1] - out[i + 1][1]))
            out[i] = (out[i][0], y, out[i][2])
    return out


def _wall(pts, half, *, off, h, base_drop=0.35, tile_m=3.0, keep=None):
    """Physical barrier (1WALL) swept up BOTH edges of a freeway, from just below the road surface to ``h``
    above the deck centreline. Double-sided so AC collides from either face. ``off`` = lateral gap past the
    half-width (place it just outside the graded shoulder). Rides ``deck_pts`` so it follows the viaduct/
    flyover. This is what keeps a launched car on the road instead of off into the desert.

    ``keep[i]`` (optional per-vertex bool) opens a GAP in the barrier at an at-grade crossing: a wall
    panel is emitted only where both of its vertices are kept, so a road crossing at the same height can
    pass through instead of being trapped. Outer walls (open dirt beyond) stay fully closed."""
    V, U, T = [], [], []
    for side in (1.0, -1.0):
        rows = []
        arc = 0.0
        for i in range(len(pts)):
            if i > 0:
                arc += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2])
            x, y, z = pts[i]
            a = pts[max(0, i - 1)]; b = pts[min(len(pts) - 1, i + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]; tl = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / tl * side, tx / tl * side
            px, pz = x + nx * (half + off), z + nz * (half + off)
            r = len(V)
            V.append((px, y - base_drop, pz)); U.append((arc / tile_m, 0.0))
            V.append((px, y + h, pz)); U.append((arc / tile_m, 1.0))
            rows.append(r)
        for k in range(len(rows) - 1):
            if keep is not None and not (keep[k] and keep[k + 1]):
                continue      # gap the barrier through an at-grade crossing
            a0, a1, b0, b1 = rows[k], rows[k] + 1, rows[k + 1], rows[k + 1] + 1
            T += [(a0, a1, b1), (a0, b1, b0)]
    if not T:
        return {"vertices": [], "uvs": [], "tris": []}
    # PRUNE orphan verts: a gapped panel leaves its verts unreferenced; drop them so the mesh (and the
    # audit) carry no wall cruft where the barrier was opened over a road/crossing.
    used = sorted({i for tri in T for i in tri})
    remap = {o: n for n, o in enumerate(used)}
    V = [V[o] for o in used]; U = [U[o] for o in used]
    T = [(remap[a], remap[b], remap[c]) for a, b, c in T]
    T = T + [(a, c, b) for a, b, c in T]   # double-side for collision from either face
    return {"vertices": V, "uvs": U, "tris": T}


LANE_W = 3.66   # US freeway lane width (12 ft)


def _lane_markings(pts, half, lanes, *, lift, line_w=0.14, dash_on=3.0, dash_gap=9.0, mark_lift=0.03):
    """Paint white lane lines on a road: two SOLID edge lines + (lanes-1) DASHED interior lane dividers,
    over the painted span (lanes*LANE_W, centred; shoulders left bare). Visual-only (MARKINGS), lifted a
    hair above the ribbon. ``pts`` are the deck centreline; ``lift`` is ROAD_LIFT_M."""
    n = len(pts)
    lanes = max(1, int(lanes))
    span = min(lanes * LANE_W, 2.0 * half - 0.8)
    lines = [(-span / 2, False), (span / 2, False)]                      # solid edges
    lines += [(-span / 2 + k * (span / lanes), True) for k in range(1, lanes)]   # dashed dividers
    arc = [0.0]
    for i in range(1, n):
        arc.append(arc[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2]))

    def nrm(i):
        a = pts[max(0, i - 1)]; b = pts[min(n - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]; tl = math.hypot(tx, tz) or 1.0
        return -tz / tl, tx / tl

    V, T = [], []
    hw = line_w / 2.0
    for o, dashed in lines:
        for i in range(n - 1):
            if dashed and (arc[i] % (dash_on + dash_gap)) > dash_on:
                continue
            (x0, y0, z0), (nx0, nz0) = pts[i], nrm(i)
            (x1, y1, z1), (nx1, nz1) = pts[i + 1], nrm(i + 1)
            cx0, cz0 = x0 + nx0 * o, z0 + nz0 * o
            cx1, cz1 = x1 + nx1 * o, z1 + nz1 * o
            yy0, yy1 = y0 + lift + mark_lift, y1 + lift + mark_lift
            b = len(V)
            V.append((cx0 - nx0 * hw, yy0, cz0 - nz0 * hw)); V.append((cx0 + nx0 * hw, yy0, cz0 + nz0 * hw))
            V.append((cx1 + nx1 * hw, yy1, cz1 + nz1 * hw)); V.append((cx1 - nx1 * hw, yy1, cz1 - nz1 * hw))
            T.append((b, b + 1, b + 2)); T.append((b, b + 2, b + 3))
    T = T + [(a, c, b) for a, b, c in T]     # double-side flat markings
    return {"vertices": V, "uvs": [(0.0, 0.0)] * len(V), "tris": T}


def _trim_ramp_merge(deck_pts, road_hash, self_eid, *, cell=12.0, dy=3.0):
    """Stop a ramp CROSSING OVER a road it connects to: drop the ramp deck vertices that fall inside
    ANOTHER road's footprint at a SIMILAR height (a real merge/at-grade crossing), keeping the longest
    contiguous run. A ramp that FLIES OVER (grade-separated, different height) or its OWN points
    (``self_eid``) are untouched. Returns the trimmed pts."""
    n = len(deck_pts)
    keep = [True] * n
    for i in range(n):
        x, y, z = deck_pts[i]
        ci, cj = int(x // cell), int(z // cell)
        hit = False
        for di in (-2, -1, 0, 1, 2):
            for dj in (-2, -1, 0, 1, 2):
                for (rx, ry, rz, rhalf, reid) in road_hash.get((ci + di, cj + dj), ()):
                    if reid == self_eid:
                        continue
                    if (x - rx) ** 2 + (z - rz) ** 2 <= (rhalf + 2.0) ** 2 and abs(y - ry) < dy:
                        hit = True    # +2 m past the centreline footprint: catch crossings near the road EDGE
                        break
                if hit:
                    break
            if hit:
                break
        keep[i] = not hit
    best = (0, 0); i = 0
    while i < n:
        if keep[i]:
            j = i
            while j < n and keep[j]:
                j += 1
            if j - i > best[1] - best[0]:
                best = (i, j)
            i = j
        else:
            i += 1
    return deck_pts[best[0]:best[1]]


def _save_ground_local(data: Path, grid_xyz) -> None:
    """Write the conformed ground as a regular local X-Z height grid for build_network_env to sample."""
    ny = len(grid_xyz); nx = len(grid_xyz[0])
    x0 = grid_xyz[0][0][0]; z0 = grid_xyz[0][0][2]
    dx = (grid_xyz[0][nx - 1][0] - x0) / max(1, nx - 1)
    dz = (grid_xyz[ny - 1][0][2] - z0) / max(1, ny - 1)
    ys = [[round(grid_xyz[j][i][1], 2) for i in range(nx)] for j in range(ny)]
    (data / "ground.local.json").write_text(json.dumps(
        {"x0": round(x0, 2), "z0": round(z0, 2), "dx": round(dx, 4), "dz": round(dz, 4),
         "nx": nx, "ny": ny, "y": ys}), encoding="utf-8")


def _run_mesh(run):
    """One flat quad ribbon between two parallel road edges (run = [(a_edge_pt, b_edge_pt), ...])."""
    V, U, T = [], [], []
    for aep, bep in run:
        V.append(aep); V.append(bep); U.append((0.0, 0.0)); U.append((1.0, 0.0))
    for k in range(len(run) - 1):
        a0, b0 = 2 * k, 2 * k + 1
        a1, b1 = 2 * (k + 1), 2 * (k + 1) + 1
        T.append((a0, b0, b1)); T.append((a0, b1, a1))
    return {"vertices": V, "uvs": U, "tris": T}


def _median_fill(fw_edges, *, cell=8.0, max_gap=17.0, dy=2.5, ang=math.radians(26)):
    """Fill the NARROW MEDIAN between two close, parallel carriageways with a FLAT drivable surface spanning
    edge-to-edge (heights ramp linearly across, so there is no step) — so crossing the median never drops
    the car into the verge dip or bounces it over the coarse grass. fw_edges = [(eid, road-surface pts,
    half)]. Only the lower-eid road of a pair builds the strip (no double). Returns a LIST of run meshes."""
    from collections import defaultdict
    ep_hash = defaultdict(list)
    for eid, dp, half in fw_edges:
        for i in range(len(dp)):
            x, y, z = dp[i]
            a = dp[max(0, i - 1)]; b = dp[min(len(dp) - 1, i + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]; tl = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / tl, tx / tl
            t = math.atan2(tz, tx)
            for sgn in (1.0, -1.0):
                ex, ez = x + nx * half * sgn, z + nz * half * sgn
                ep_hash[(int(ex // cell), int(ez // cell))].append((eid, (ex, y, ez), t))

    def nearest_other(eid, ep, tang):
        ex, ey, ez = ep
        ci, cj = int(ex // cell), int(ez // cell); best = None; bd = max_gap * max_gap
        for di in (-2, -1, 0, 1, 2):
            for dj in (-2, -1, 0, 1, 2):
                for (e2, p2, t2) in ep_hash.get((ci + di, cj + dj), ()):
                    if e2 == eid:
                        continue
                    d = (ex - p2[0]) ** 2 + (ez - p2[2]) ** 2
                    if d < bd and abs(ey - p2[1]) < dy:
                        da = abs((tang - t2 + math.pi) % (2 * math.pi) - math.pi); da = min(da, math.pi - da)
                        if da < ang:                      # parallel (opposing carriageway reads parallel)
                            bd = d; best = (e2, p2)
        return best

    meshes = []
    for eid, dp, half in fw_edges:
        for sgn in (1.0, -1.0):
            run = []
            for i in range(len(dp)):
                x, y, z = dp[i]
                a = dp[max(0, i - 1)]; b = dp[min(len(dp) - 1, i + 1)]
                tx, tz = b[0] - a[0], b[2] - a[2]; tl = math.hypot(tx, tz) or 1.0
                nx, nz = -tz / tl, tx / tl
                ep = (x + nx * half * sgn, y, z + nz * half * sgn)
                other = nearest_other(eid, ep, math.atan2(tz, tx))
                if other and eid < other[0]:
                    run.append((ep, other[1]))
                else:
                    if len(run) >= 2:
                        meshes.append(_run_mesh(run))
                    run = []
            if len(run) >= 2:
                meshes.append(_run_mesh(run))
    return meshes


def _merge_taper(deck_pts, base_w, road_hash, self_eid, *, cell=12.0, dy=3.0, taper_len=34.0, tip=0.7):
    """Per-vertex width that tapers a ramp to a near-point at the end(s) where it MERGES into another road,
    so it joins that road's EDGE as a lane (at whatever angle it approaches) instead of a full-width ribbon
    overlapping the through-lanes. An end that touches another road tapers base_w -> tip over taper_len m;
    the middle stays base_w. Ends that just dead-end in the desert are left full width."""
    n = len(deck_pts)
    w = [base_w] * n
    if n < 3:
        return w
    seg = [0.0]
    for i in range(1, n):
        seg.append(seg[-1] + math.hypot(deck_pts[i][0] - deck_pts[i - 1][0], deck_pts[i][2] - deck_pts[i - 1][2]))
    total = seg[-1]

    def touches_road(pt):
        x, y, z = pt
        ci, cj = int(x // cell), int(z // cell)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for (rx, ry, rz, rhalf, reid) in road_hash.get((ci + di, cj + dj), ()):
                    if reid == self_eid:
                        continue
                    if (x - rx) ** 2 + (z - rz) ** 2 <= (rhalf + 4.0) ** 2 and abs(y - ry) < dy:
                        return True
        return False

    start_m = touches_road(deck_pts[0])
    end_m = touches_road(deck_pts[-1])
    if not (start_m or end_m):
        return w
    frac_tip = tip / base_w if base_w > 1e-6 else 0.0
    for i in range(n):
        f = 1.0
        if start_m and seg[i] < taper_len:
            f = min(f, frac_tip + (1 - frac_tip) * (seg[i] / taper_len))
        if end_m and (total - seg[i]) < taper_len:
            f = min(f, frac_tip + (1 - frac_tip) * ((total - seg[i]) / taper_len))
        w[i] = base_w * f
    return w


def _densify(pts, max_step=6.0):
    """Interpolate extra samples so consecutive points are <= max_step apart. OSM vertex spacing on
    straights reaches 50+ m — every radius test against RAW vertices (carve, verge filter) has holes
    midway between them at that spacing (the residual-88-pokes lesson). Yields (x, y, z)."""
    prev = None
    for p in pts:
        if prev is not None:
            d = math.hypot(p[0] - prev[0], p[2] - prev[2])
            n = int(d // max_step)
            for k in range(1, n + 1):
                t = k / (n + 1)
                yield (prev[0] + (p[0] - prev[0]) * t, prev[1] + (p[1] - prev[1]) * t,
                       prev[2] + (p[2] - prev[2]) * t)
        yield p
        prev = p


def _carve_cut_corridor(grid_xyz, edge_local, *, clear=0.30, bench=None, slope=0.5,
                        grid_spacing=27.5, depth_reach=60.0):
    """CUT CARVE — one-sided: terrain never crosses ABOVE a road deck, and where the road runs in a
    CUT below natural ground the corridor is carved DOWN to deck-clearance with a real cut face,
    instead of the grass sheet chording straight across the cut (the sunken-freeway "grass ceiling"
    the vertex-only anti-poke provably missed: clamped VERTICES were legal while the 27 m triangles
    BETWEEN them bridged the cut +9 m over the deck).

    Cone-field formulation (chord-proof by construction): every terrain node's allowed height is
        min over at-grade road samples of  (road_y - clear + slope * max(0, d_past_edge - bench))
    - ``bench`` >= HALF THE GRID DIAGONAL (default 0.72 * spacing): with every node within the bench
      held at deck-clearance, NO linear interpolation across a grid triangle can rise above the deck
      over the pavement (for any point p inside a triangle, the barycentric mean of vertex distances
      to p is <= half the cell diagonal — so the cone term vanishes over the footprint).
    - beyond the bench the limit RECOVERS at ``slope`` (2:1 default) — a realistic excavated batter,
      not a reach-wide shaved moat (the CO dark-moat lesson); at-grade/fill sections are untouched
      because natural ground already sits below the cone there.
    - ONE-SIDED: only pushes DOWN. Underpasses can never be filled, natural dips survive, and the
      layer question resolves itself: the MIN over samples keeps terrain at the LOWEST road through
      a stacked interchange (the upper deck bridges the cut; pier suppression protects the road below).
    Road heights are the AT-GRADE ``edge_local`` samples so terrain stays low under flyover decks.
    Mutates grid_xyz in place."""
    from collections import defaultdict
    if bench is None:
        # half the cell diagonal (0.7071..) + the sample-lateral slack: cone distances are measured
        # to the ~6 m-spaced CENTRELINE samples, up to ~3-4 m to the side of the pavement point a
        # chord crosses — without the extra term the bound leaks ~0.3 m chords at the bench rim.
        bench = 0.72 * grid_spacing + 4.0
    half_max = max((float(w) / 2.0 for _pr, _p, w in edge_local), default=6.0)
    reach = half_max + bench + depth_reach     # depth_reach: horizontal run of the deepest cut face
    cell = max(24.0, reach / 3.0)
    R = int(reach // cell) + 1
    buckets = defaultdict(list)
    for _pr, pts, w in edge_local:
        half = float(w) / 2.0
        for x, y, z in _densify(pts):          # <=6 m sampling: no cone holes between sparse OSM verts
            buckets[(int(x // cell), int(z // cell))].append((x, y, z, half))
    reach2 = reach * reach
    for row in grid_xyz:
        for k in range(len(row)):
            gx, gy, gz = row[k]
            ci, cj = int(gx // cell), int(gz // cell)
            lim = None                 # min cone/bench limit over carving samples
            own = None                 # shelf of the NEAREST sample of any height (the "owning" road)
            own_d2 = 1e18
            in_bench_of_carver = False
            for di in range(-R, R + 1):
                for dj in range(-R, R + 1):
                    for rx, ry, rz, half in buckets.get((ci + di, cj + dj), ()):
                        d2 = (gx - rx) ** 2 + (gz - rz) ** 2
                        if d2 > reach2:
                            continue
                        if d2 < own_d2:
                            own_d2, own = d2, ry - clear
                        shelf = ry - clear
                        if shelf >= gy:        # this sample can only carve DOWN — fills/at-grade skip
                            continue
                        past = math.sqrt(d2) - half - bench
                        if past <= 0.0:
                            in_bench_of_carver = True
                        t = shelf + slope * max(0.0, past)
                        if t < gy and (lim is None or t < lim):
                            lim = t
            if lim is None:
                continue
            # OWN-GRADE FLOOR: chord-proofness only needs nodes INSIDE a carving road's bench held at
            # its shelf (any face over that pavement has all verts within the bench radius). A node
            # merely in the CONE zone that belongs to a *higher* neighbouring road (parallel ramp /
            # frontage split) must stay at ITS road's grade — without the floor, the lower road's
            # cone dragged the upper road's own verge ground 1–3 m under its deck (600 gate samples).
            if not in_bench_of_carver and own is not None:
                lim = max(lim, own)
            if gy > lim:
                row[k] = (gx, lim, gz)


def _road_tri_hash(road_meshes, *, cell=8.0):
    """Spatial hash of the ACTUAL built 1ROAD triangles (each registered across its XZ bbox cells) —
    the same ground truth the mesh audit measures against."""
    from collections import defaultdict
    h = defaultdict(list)
    for _nm, m in road_meshes:
        V, T = m["vertices"], m["tris"]
        for a, b, c in T:
            t = (V[a], V[b], V[c])
            xs = (t[0][0], t[1][0], t[2][0]); zs = (t[0][2], t[1][2], t[2][2])
            for ci in range(int(min(xs) // cell), int(max(xs) // cell) + 1):
                for cj in range(int(min(zs) // cell), int(max(zs) // cell) + 1):
                    h[(ci, cj)].append(t)
    return h


HANG_MAX_M = 3.5    # a verge vert more than this above the ground beneath = a bridge edge, not a shoulder
#                     (same threshold as the bridge detector's BRIDGE_MIN_H_M: past it you SPAN, not fill)


def _filter_verge_over_roads(verge_meshes, road_th, *, cell=8.0, above=0.05, dy_max=40.0,
                             ground_at=None):
    """Gap the freeway GRASS VERGE wherever it hangs over pavement — the "grass sheeted over sunken
    decks" defect: at a grade-separated crossing the upper road's 3 m shoulder strip swept straight
    across the cut, putting physical 1GRASS 0.2–20 m above the sunken carriageway (14k kn5 pokes +
    every double-sheet cell); tight loop ramps did the same over their OWN lower winding. A real
    overpass edge is concrete/barrier, not grass — the viaduct slab and walls already provide it.

    TRIANGLE-EXACT against the built road ribbons (``road_th`` from _road_tri_hash) — the identical
    criterion the audit's check B applies, so verge B-pokes are impossible by construction: drop each
    triangle with ANY vertex sitting ``above``..``dy_max`` over a road surface at its own XZ, then
    prune orphaned verts (no cruft into the audit). A verge UNDER a flyover is untouched; the vert's
    own ribbon edge shares its height (delta 0), so legitimate shoulders never trip the test.

    ``ground_at(x, z) -> y`` (optional, the CARVED terrain): additionally drop tris HANGING more than
    HANG_MAX_M above the ground beneath — a viaduct/overpass edge riding a canyon or a carved cut is
    a bridge edge (concrete slab + barrier), not a grass shoulder floating in the sky (these were
    every residual double-sheet cell: verge at deck height + canyon floor 30 m below in one XZ cell)."""
    def _over_road(v):
        vx, vy, vz = v
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for a, b, c in road_th.get((int(vx // cell) + di, int(vz // cell) + dj), ()):
                    d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
                    if abs(d) < 1e-12:
                        continue
                    w0 = ((b[2] - c[2]) * (vx - c[0]) + (c[0] - b[0]) * (vz - c[2])) / d
                    w1 = ((c[2] - a[2]) * (vx - c[0]) + (a[0] - c[0]) * (vz - c[2])) / d
                    w2 = 1.0 - w0 - w1
                    if w0 >= -1e-6 and w1 >= -1e-6 and w2 >= -1e-6:
                        yy = w0 * a[1] + w1 * b[1] + w2 * c[1]
                        if above < vy - yy < dy_max:
                            return True
        return False

    def _hanging(v):
        if ground_at is None:
            return False
        g = ground_at(v[0], v[2])
        return g is not None and v[1] - g > HANG_MAX_M

    out = []
    n_tris_dropped = 0
    for name, m in verge_meshes:
        V, U, T = m["vertices"], m.get("uvs"), m["tris"]
        drop = set()
        for ti, (a, b, c) in enumerate(T):
            if _over_road(V[a]) or _over_road(V[b]) or _over_road(V[c]) \
                    or _hanging(V[a]) or _hanging(V[b]) or _hanging(V[c]):
                drop.add(ti)
        if not drop:
            out.append((name, m))
            continue
        n_tris_dropped += len(drop)
        keep_t = [t for ti, t in enumerate(T) if ti not in drop]
        used = sorted({i for tri in keep_t for i in tri})
        remap = {o: n for n, o in enumerate(used)}
        m2 = {"vertices": [V[o] for o in used],
              "uvs": [U[o] for o in used] if U else None,
              "tris": [(remap[a], remap[b], remap[c]) for a, b, c in keep_t]}
        if m2["tris"]:
            out.append((name, m2))
    if n_tris_dropped:
        print(f"  verge gap: {n_tris_dropped} shoulder tris dropped over pavement (no grass over a deck)")
    return out


def _track_road_sampler(data: Path, conform_r: float = 30.0):
    """A CONNECTOR that crosses a detailed track's footprint must ride ONTO that track's deck (meet it at
    grade), not stay at the flat field height and fly over/under it. This returns conform(x,y,z)->y' which,
    within conform_r of any merged-track (track_*.obj) road surface, blends the connector's Y toward that
    track's local road height (full on the track, tapering to the field at conform_r). Requires merge_detailed
    to have run first (track_*.obj present). Only touches connector vertices NEAR a track, so it fixes the
    crossings without warping a connector that merely passes through a large pad far from the track's roads."""
    from collections import defaultdict
    CELL = conform_r
    H: dict = defaultdict(list); n = 0
    for tf in sorted(data.glob("track_*.obj")):
        V: list = []; keep: set = set(); road = False
        for ln in tf.read_text().splitlines():
            if ln.startswith("v "):
                _, a, b, c = ln.split()[:4]; V.append((float(a), float(b), float(c)))
            elif ln.startswith("o "):
                road = ln[2:].strip().upper().startswith("1ROAD")
            elif ln.startswith("f ") and road:
                for tok in ln.split()[1:]:
                    keep.add(int(tok.split("/")[0]) - 1)
        for i in keep:
            x, y, z = V[i]; H[(int(x // CELL), int(z // CELL))].append((x, y, z)); n += 1

    def conform(x, y, z):
        ci, cj = int(x // CELL), int(z // CELL); best = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for tx, ty, tz in H.get((ci + di, cj + dj), ()):
                    d = (x - tx) ** 2 + (z - tz) ** 2
                    if best is None or d < best[0]:
                        best = (d, ty)
        if best is None or best[0] >= conform_r * conform_r:
            return y
        w = 1.0 - (best[0] ** 0.5) / conform_r     # 1 on the track road -> 0 at conform_r
        return w * best[1] + (1.0 - w) * y
    return conform, n


def build(project_dir: str | Path) -> dict:
    proj = Path(project_dir)
    data = proj / "data"
    cfg = load_config(proj)
    mirror_x = bool(cfg.raw.get("mirror_x", True))

    fc = json.loads((data / "network.geojson").read_text())
    F = fc["features"]
    elev = json.loads((data / "network.elevation.json").read_text())
    zmap = {e["id"]: e["z_smooth_m"] for e in elev["edges"]}

    # origin = centroid of ALL edge vertices; elev0 = min z (so Y >= 0). config.origin may pin a SHARED
    # {lon,lat,elev_m} origin so detailed merged tracks (loop/aerial) build in the SAME frame -> one kn5.
    all_ll = [(lon, lat) for f in F for lon, lat in f["geometry"]["coordinates"]]
    _og = cfg.raw.get("origin", "centroid")
    if isinstance(_og, dict) and "lon" in _og and "lat" in _og:
        origin = (float(_og["lon"]), float(_og["lat"]))
        elev0 = float(_og.get("elev_m", min(min(z) for z in zmap.values())))
    else:
        origin = centroid(all_ll)
        elev0 = min(min(z) for z in zmap.values())
    lon0, lat0 = origin
    m_lon, m_lat = _meters_per_degree(lat0)
    sx = -1.0 if mirror_x else 1.0

    def to_local(lon, lat, z):
        return (sx * (lon - lon0) * m_lon, z - elev0, (lat - lat0) * m_lat)

    # banking regions (e.g. the PPIR oval): roll any edge vertex that falls in the annulus [r_in,r_out]
    # around a centre by bank_deg (ramped over 25 m at each annulus edge for a smooth transition). The
    # annulus isolates the banked oval RING from the flat road-course INFIELD inside it.
    import bisect as _bisect
    _bank = []
    for b in ((cfg.raw.get("scenery", {}) or {}).get("banking", []) or []):
        bx, _by, bz = to_local(b["center_lon"], b["center_lat"], 0.0)
        _bank.append((bx, bz, float(b.get("r_in_m", 150)), float(b.get("r_out_m", 350)),
                      math.radians(float(b.get("bank_deg", 0.0)))))

    def _vertex_bank(x, z):
        best = 0.0
        for bx, bz, ri, ro, ba in _bank:
            d = math.hypot(x - bx, z - bz)
            if ri <= d <= ro:
                best = max(best, ba * max(0.0, min(1.0, (d - ri) / 25.0, (ro - d) / 25.0)))
        return best

    # viaduct knobs (config-driven): base_lift = constant Shutoko-style deck height even over flat ground;
    # bridge component adds more over canyon dips; both taper to grade at junctions.
    _vcfg = (cfg.raw.get("scenery", {}) or {}).get("viaduct", {}) or {}
    via_base = float(_vcfg.get("base_lift_m", 0.0))
    via_max = float(_vcfg.get("max_lift_m", 26.0))
    via_win = int(_vcfg.get("smooth_win", 60))
    via_taper = float(_vcfg.get("taper_frac", 0.16))
    layer_h = float(_vcfg.get("layer_height_m", 5.5))       # per OSM bridge layer -> flyover deck height

    # physical WALL knobs: a collidable concrete barrier up both edges of every freeway edge so a launched
    # car stays on the road instead of flying off into the desert (build a swept 1WALL ribbon per edge).
    _wcfg = (cfg.raw.get("scenery", {}) or {}).get("walls", {}) or {}
    want_walls = bool(_wcfg.get("enabled", False))
    wall_h = float(_wcfg.get("height_m", 1.0))
    wall_off = float(_wcfg.get("offset_m", 3.2))
    want_markings = bool(((cfg.raw.get("scenery", {}) or {}).get("markings", {}) or {}).get("enabled", True))
    want_merge_trim = bool(((cfg.raw.get("scenery", {}) or {}).get("merge_trim", {}) or {}).get("enabled", True))

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
    # connector->track conform: lift a connector onto any detailed track's deck where it crosses. With REAL
    # road elevations the connectors and tracks already share the real ground, so they meet naturally within
    # each track's small entrance relief — the conform is off by default (it re-introduced steep launch ramps
    # where a connector crossed a track's interior relief). Enable via scenery.elevation.conform_tracks.
    _do_conform = bool(((cfg.raw.get("scenery", {}) or {}).get("elevation", {}) or {}).get("conform_tracks", False))
    conform_track, _ncf = _track_road_sampler(data) if _do_conform else (None, 0)
    if _ncf:
        print(f"  connector conform: {_ncf} track road verts loaded (connectors ride onto tracks at crossings)")

    road_meshes: list[tuple[str, dict]] = []
    edge_local: list[tuple[dict, list[Vertex], float]] = []  # (props, AT-GRADE pts, width) for conform+dummies
    viaduct_meshes: list[dict] = []
    viaduct_profiles: dict[str, list[float]] = {}   # edge_id -> per-vertex lift (shared with build_network_env)
    kerb_meshes: list[tuple[str, dict]] = []        # 1KERB curb+sidewalk on surface streets + race tracks
    verge_meshes: list[tuple[str, dict]] = []       # graded shoulder on freeways -> road never hovers
    wall_meshes: list[tuple[str, dict]] = []        # 1WALL physical barrier up both freeway edges
    marking_meshes: list[tuple[str, dict]] = []     # MARKINGS lane lines (visual)
    wall_jobs: list[tuple[str, list, float]] = []   # (eid, deck_pts, half) — walls built AFTER the loop
    via_jobs: list[tuple[str, list, float]] = []     # (eid, deck_pts, half) — viaduct structs built AFTER the loop
    deck_all: list[tuple[str, list, float]] = []     # (eid, deck_pts, half) — EVERY freeway deck (bridge runs)
    fw_edge_decks: list[tuple[str, list, float]] = []  # (eid, road-surface pts, half) — mainlines, for median fill
    from collections import defaultdict as _wdd
    fw_road_hash = _wdd(list)                        # deck pts (eid,x,y,z,tangent,half) for crossing/pier tests
    WCELL = 8.0
    # ROAD pre-pass hash (at-grade centreline + half + edge id) so a ramp can be trimmed where it would
    # cross OVER any road it connects to (mainline OR another ramp), keeping grade-separated flyovers.
    MCELL = 12.0
    road_trim_hash = _wdd(list)
    for f in F:
        p = f["properties"]
        if p.get("road_class") not in FREEWAY_CLS:
            continue
        c = f["geometry"]["coordinates"]; zz = zmap.get(p["id"]) or [0.0] * len(c)
        if len(zz) != len(c):
            zz = (zz + [zz[-1]] * len(c))[:len(c)]
        mhalf = float(p.get("width_m") or cfg.default_width_m) / 2.0
        for (lo, la), z1 in zip(c, zz):
            mx, my, mz = to_local(lo, la, z1)
            road_trim_hash[(int(mx // MCELL), int(mz // MCELL))].append((mx, my, mz, mhalf, p["id"]))
    for f in F:
        c = f["geometry"]["coordinates"]
        z = zmap.get(f["properties"]["id"]) or [0.0] * len(c)
        if len(z) != len(c):  # safety: pad/truncate
            z = (z + [z[-1]] * len(c))[:len(c)]
        pts = [to_local(lon, lat, zz) for (lon, lat), zz in zip(c, z)]
        if _ncf:                                    # ride onto any track deck this connector crosses
            pts = [(x, conform_track(x, y, z2), z2) for x, y, z2 in pts]
            # grade-cap the conformed profile (by ACTUAL segment distance) so ramping onto a track deck — or
            # crossing a track's interior relief — never exceeds CONFORM_GRADE and launches the car.
            for _ in range(2):
                for i in range(1, len(pts)):
                    cap = CONFORM_GRADE * max(0.5, math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2]))
                    pts[i] = (pts[i][0], pts[i - 1][1] + max(-cap, min(cap, pts[i][1] - pts[i - 1][1])), pts[i][2])
                for i in range(len(pts) - 2, -1, -1):
                    cap = CONFORM_GRADE * max(0.5, math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2]))
                    pts[i] = (pts[i][0], pts[i + 1][1] + max(-cap, min(cap, pts[i][1] - pts[i + 1][1])), pts[i][2])
        w = float(f["properties"].get("width_m") or cfg.default_width_m)
        if len(pts) < 2:
            continue
        is_fw = f["properties"].get("road_class") in FREEWAY_CLS
        deck_pts = pts
        if is_fw:
            dip = _viaduct_lift(pts, terr_y, base_lift=via_base, max_lift=via_max,
                                smooth_win=via_win, taper_frac=via_taper)
            lay = _layer_lift(pts, f["properties"].get("layer_profile"), layer_h=layer_h)
            lift = [dip[i] + lay[i] for i in range(len(pts))]
            if max(lift) > 1.0:
                deck_pts = [(x, y + lift[i], z2) for i, (x, y, z2) in enumerate(pts)]
                deck_pts = _grade_cap_y(deck_pts, max_grade=0.065)   # drivable ramps onto the flyover deck
                via_jobs.append((f["properties"]["id"], list(deck_pts), w / 2.0))   # struct built AFTER loop
                # store the ACTUALLY-applied lift (post grade-cap) so env furniture rides the real deck
                viaduct_profiles[str(f["properties"]["id"])] = [round(deck_pts[i][1] - pts[i][1], 2)
                                                                for i in range(len(pts))]
        # RAMP MERGE: trim a ramp where it would cross OVER the mainline it joins, then TAPER its width to a
        # point at the merge end(s) so it joins the mainline edge as a lane (at whatever angle) instead of a
        # full-width ribbon over the through-lanes. Grade-separated flyover crossings are untouched.
        if is_fw and want_merge_trim and f["properties"].get("is_ramp"):
            trimmed = _trim_ramp_merge(deck_pts, road_trim_hash, f["properties"]["id"])
            if len(trimmed) >= 2:
                deck_pts = trimmed
            w_arr = _merge_taper(deck_pts, w, road_trim_hash, f["properties"]["id"])
        else:
            w_arr = [w] * len(deck_pts)
        bank_at = None
        if _bank:
            bv = [_vertex_bank(p[0], p[2]) for p in deck_pts]
            if any(bv):
                arcs = [0.0]
                for i in range(1, len(deck_pts)):
                    arcs.append(arcs[-1] + math.hypot(deck_pts[i][0] - deck_pts[i - 1][0],
                                                      deck_pts[i][2] - deck_pts[i - 1][2]))
                bank_at = (lambda a, arcs=arcs, bv=bv: bv[min(len(bv) - 1, _bisect.bisect_left(arcs, a))])
        rib = ribbon.road_ribbon(deck_pts, w_arr, tile_m=8.0, bank_at=bank_at)
        rib["vertices"] = [(x, y + ROAD_LIFT_M, z2) for x, y, z2 in rib["vertices"]]
        orient_up(rib)
        road_meshes.append((f"e{f['properties']['id']}", rib))
        # lane lines on MAINLINES only (a tapering ramp has no lanes to paint; keeps markings off the taper)
        if want_markings and not f["properties"].get("is_ramp"):
            _lanes = int(f["properties"].get("lanes") or 0) or max(1, int(round(w / LANE_W)) - 1)
            marking_meshes.append((f"m{f['properties']['id']}",
                                   _lane_markings(deck_pts, w / 2.0, _lanes, lift=ROAD_LIFT_M)))
        # ROAD EDGE — kills the "floating road" + "no kerbs": a continuous strip from the road edge
        # (lift proud, sharing the ribbon edge height) down to the conformed grass, so nothing hovers.
        # Freeways get a plain graded SHOULDER; surface streets + race tracks get a mountable CURB +
        # narrow sidewalk (1KERB). lift is already in the profile, so DON'T re-add ROAD_LIFT_M.
        eid = f["properties"]["id"]
        if is_fw:
            sh = ribbon.road_shoulder(deck_pts, w_arr, lift=ROAD_LIFT_M, verge_w=3.0,
                                      ground_drop=GRASS_CLEARANCE_M, bank_at=bank_at)
            orient_up(sh)   # physical surface -> face up (NOT double-sided: verify wants drivable face-up)
            verge_meshes.append((f"v{eid}", sh))
            deck_all.append((eid, deck_pts, w / 2.0))   # every freeway deck: bridge-run detection
            # deck hash ALWAYS (walls, pier suppression, crossing tests all read it): (eid,x,y,z,tan,half)
            for wi in range(len(deck_pts)):
                rx, ry, rz = deck_pts[wi]
                a = deck_pts[max(0, wi - 1)]; b = deck_pts[min(len(deck_pts) - 1, wi + 1)]
                fw_road_hash[(int(rx // WCELL), int(rz // WCELL))].append(
                    (eid, rx, ry, rz, math.atan2(b[2] - a[2], b[0] - a[0]), w / 2.0))
            if want_walls:   # defer wall build until every deck is known (so crossings can be gapped)
                wall_jobs.append((eid, deck_pts, w / 2.0))
            # ALL freeway edges (mainlines AND ramps) feed the median/gore fill: a gore wedge between
            # a ramp and its mainline is paved in the real world, and filling it keeps the gap the
            # verge-gap opens there covered by drivable 1RUNOFF instead of a bare drop to the bench.
            fw_edge_decks.append((eid, [(x, y + ROAD_LIFT_M, z2) for x, y, z2 in deck_pts], w / 2.0))
        else:
            cb = ribbon.curb_sidewalk(deck_pts, [w] * len(deck_pts), lift=ROAD_LIFT_M, curb_h=0.12,
                                      curb_face_w=0.06, sidewalk_w=1.0, grade_w=1.0,
                                      grass_clearance=GRASS_CLEARANCE_M, tile_m=2.0, bank_at=bank_at)
            # VISUAL curb (double-sided, no 1-prefix): its vertical face can't pass the drivable face-up
            # check and you don't ride a street curb. It still renders + closes the hover; the conformed
            # grass provides the physical edge. (Detailed SC/IMI keep their physical loop-path kerbs.)
            kerb_meshes.append((f"k{eid}", _doubleside(cb)))
        edge_local.append((f["properties"], pts, w))   # AT-GRADE pts: terrain conforms to the ground, not the deck

    # --- WALLS: built now that every freeway deck is known. Gap the barrier where ANOTHER freeway crosses
    # at a large angle at nearly the same height (a residual at-grade interchange crossing that the OSM
    # bridge-layer lift didn't grade-separate) so the car passes through instead of being trapped; keep the
    # full barrier where the ground beyond is open (dirt) or the crosser is grade-separated (a flyover). ---
    if want_walls and wall_jobs:
        WALL_R = 8.0
        WALL_ANGLE = math.radians(28.0)     # >this between crossing tangents = a real crossing, not a parallel median
        n_gap = 0
        for eid, dp, half in wall_jobs:
            n = len(dp)
            keep = [True] * n
            for i in range(n):
                x, y, z = dp[i]
                a = dp[max(0, i - 1)]; b = dp[min(n - 1, i + 1)]
                tx, tz = b[0] - a[0], b[2] - a[2]; tl = math.hypot(tx, tz) or 1.0
                nx, nz = -tz / tl, tx / tl
                st = math.atan2(tz, tx)
                blocked = False
                for side in (1.0, -1.0):
                    wx, wz = x + nx * (half + wall_off) * side, z + nz * (half + wall_off) * side
                    ci, cj = int(wx // WCELL), int(wz // WCELL)
                    for di in (-2, -1, 0, 1, 2):
                        for dj in (-2, -1, 0, 1, 2):
                            for (eid2, rx, ry, rz, rt, rhalf) in fw_road_hash.get((ci + di, cj + dj), ()):
                                if eid2 == eid:
                                    continue
                                d2 = (wx - rx) ** 2 + (wz - rz) ** 2
                                on_road_r = rhalf + 3.5   # gap the wall out past the road edge + its shoulder
                                if d2 >= max(WALL_R, on_road_r) ** 2:
                                    continue
                                if not (-2.0 < (ry - y) < 1.2):
                                    continue     # crosser too far above/below to trap -> keep the wall
                                # (item 2) the wall sits ON/over another road's drivable surface -> gap it
                                #  (any angle; this is what removes median walls landing on the opposing
                                #  carriageway, and walls tangling across roads at interchanges).
                                if d2 <= on_road_r * on_road_r:
                                    blocked = True; break
                                # (item 1) near an at-grade CROSSING at a large angle -> gap so the barriers
                                #  don't cross each other irrationally.
                                if d2 <= WALL_R * WALL_R:
                                    da = abs((st - rt + math.pi) % (2 * math.pi) - math.pi)
                                    da = min(da, math.pi - da)   # 180deg (oncoming carriageway) reads parallel
                                    if da > WALL_ANGLE:
                                        blocked = True; break
                            if blocked:
                                break
                        if blocked:
                            break
                    if blocked:
                        break
                if blocked:
                    keep[i] = False; n_gap += 1
            wm = _wall(dp, half, off=wall_off, h=wall_h, keep=keep)
            if wm["tris"]:
                wall_meshes.append((f"w{eid}", wm))
        print(f"  walls: {len(wall_jobs)} freeway edges, {n_gap} vertices gapped at at-grade crossings")

    # --- VIADUCT STRUCTURES built now that every deck is known: a pier that would stand in a road passing
    # UNDER the deck is dropped (clear span) so no support column spears a crossing road (audit check A). ---
    def _col_blocks(cx, cz, y_top):
        # Scan reach must COVER the widest clearance radius: ±2 cells (16 m) missed piers in the
        # (16 .. rhalf+4.5≈17.3] m annulus of wide mainlines — 6 downtown piers speared I-5. ±3 = 24 m.
        ci, cj = int(cx // WCELL), int(cz // WCELL)
        for di in (-3, -2, -1, 0, 1, 2, 3):
            for dj in (-3, -2, -1, 0, 1, 2, 3):
                for (_eid2, rx, ry, rz, _rt, rhalf) in fw_road_hash.get((ci + di, cj + dj), ()):
                    if (cx - rx) ** 2 + (cz - rz) ** 2 > (rhalf + 4.5) ** 2:
                        continue
                    # Same band the AUDIT calls a speared crossing (y_top-45 .. y_top-1.5). The old
                    # terrain-based gate (gy-2.0 < ry) missed roads running in a CUT below the pier-base
                    # terrain (downtown underpasses) — the pier built anyway and stood in the road.
                    if y_top - 45.0 < ry < y_top - 1.5:
                        return True                        # a road runs under the deck here -> clear span
        return False
    # NOTE: the structs themselves are built AFTER the terrain grid is conformed+carved (below), so
    # piers reach the CARVED ground in a cut instead of hanging from the raw-DEM height.

    # MEDIAN FILL: flat drivable 1RUNOFF between close parallel carriageways so crossing the median doesn't
    # bounce the car over the verge dip / coarse grass (the strip left open when median walls were removed).
    median_meshes: list[tuple[str, dict]] = []
    if bool(((cfg.raw.get("scenery", {}) or {}).get("median_fill", {}) or {}).get("enabled", True)) and fw_edge_decks:
        meds = _median_fill(fw_edge_decks)
        for mi, m in enumerate(meds):
            orient_up(m)
            median_meshes.append((f"med{mi}", m))
        print(f"  median fill: {len(meds)} strips between close carriageways")

    # --- terrain grid: project, upsample for road-hugging, conform to ALL edges (at-grade) ---
    grid, meta = ribbon.upsample_grid(raw_grid, raw_meta, 2)   # 55 m -> ~27 m
    grid_xyz = project_grid(grid, meta, origin, elev0, mirror_x=mirror_x)
    # conform: grade terrain to the nearest road sample across the whole network. corridor must exceed
    # the grid half-diagonal (~19 m at 27 m spacing); 22 m keeps near-road nodes pinned to road height.
    extra = [(p, [w] * len(p)) for _pr, p, w in edge_local]
    main_pts, main_w = (extra[0][0], extra[0][1]) if extra else ([], [])
    ribbon.conform_terrain_to_road(grid_xyz, main_pts, main_w, corridor=22.0, blend=26.0,
                                   extra_roads=extra[1:], clearance=GRASS_CLEARANCE_M)
    # CUT CARVE (audit check B + the sunken-deck grass ceiling): after conform, carve the corridor so
    # terrain NEVER crosses above a deck — deck-clearance bench under+beside the footprint (wide enough
    # that no coarse-grid triangle can chord over the pavement), then a 2:1 cut face back to natural.
    # One-sided (only pushes DOWN): underpasses are never filled, dips survive, flyovers keep their
    # at-grade ground (AT-GRADE edge_local samples).
    _grid_sp = float(meta.get("spacing_m", 55.0))
    _carve_cut_corridor(grid_xyz, edge_local, clear=GRASS_CLEARANCE_M, grid_spacing=_grid_sp)

    # VIADUCT STRUCTURES (deferred from the edge loop): built against the CARVED ground so piers land
    # on the terrain that actually ships — a pier based on the raw DEM hangs in the air once the cut
    # is carved beneath it. Sampler = min(raw DEM, carved grid).
    _cg_x0 = grid_xyz[0][0][0]; _cg_z0 = grid_xyz[0][0][2]
    _cg_nx = len(grid_xyz[0]); _cg_ny = len(grid_xyz)
    _cg_dx = (grid_xyz[0][_cg_nx - 1][0] - _cg_x0) / max(1, _cg_nx - 1)
    _cg_dz = (grid_xyz[_cg_ny - 1][0][2] - _cg_z0) / max(1, _cg_ny - 1)

    def _carved_y(x, z):
        fi = (x - _cg_x0) / _cg_dx if _cg_dx else 0.0
        fj = (z - _cg_z0) / _cg_dz if _cg_dz else 0.0
        if not (0 <= fi < _cg_nx - 1 and 0 <= fj < _cg_ny - 1):
            return terr_y(x, z)
        i0, j0 = int(fi), int(fj)
        ti, tj = fi - i0, fj - j0
        a = grid_xyz[j0][i0][1] * (1 - ti) + grid_xyz[j0][i0 + 1][1] * ti
        b = grid_xyz[j0 + 1][i0][1] * (1 - ti) + grid_xyz[j0 + 1][i0 + 1][1] * ti
        return a * (1 - tj) + b * tj

    def _carved_low(x, z):
        """PESSIMISTIC carved ground: the LOWEST of the four surrounding grid nodes. The bilinear
        under a deck's own bench nodes averages the cut away — the grass FACES beneath still dip to
        the low node via the triangulation, so span detection must see the node, not the average."""
        fi = (x - _cg_x0) / _cg_dx if _cg_dx else 0.0
        fj = (z - _cg_z0) / _cg_dz if _cg_dz else 0.0
        if not (0 <= fi < _cg_nx - 1 and 0 <= fj < _cg_ny - 1):
            return terr_y(x, z)
        i0, j0 = int(fi), int(fj)
        return min(grid_xyz[j0][i0][1], grid_xyz[j0][i0 + 1][1],
                   grid_xyz[j0 + 1][i0][1], grid_xyz[j0 + 1][i0 + 1][1])

    def _terr_min(x, z):
        return min(terr_y(x, z), _carved_y(x, z))

    # BRIDGE RUNS: a deck riding high over the CARVED ground with no viaduct lift of its own — an
    # at-grade road crossing a freeway cut — is a real bridge. Give the run the same underside slab
    # + piers, so the crossing is structurally supported instead of a bare ribbon floating over the
    # carve (and the kn5 gate can see that support).
    via_ids = {str(e) for e, _p, _h in via_jobs}
    n_runs = 0
    RUN_H = 2.8       # clears-ground threshold: BELOW the verge hang-drop (3.5) so every stretch
    #                   whose grass shoulder is dropped as "a bridge edge" is guaranteed its slab
    RUN_ARC = 4.0     # short culvert-sized spans still get structure (12 m left slabless gaps)
    for eid, dp, half in deck_all:
        if str(eid) in via_ids:
            continue
        dens = list(_densify(dp))              # raw OSM spacing (50 m+) chopped runs + missed spans
        high = [y - min(terr_y(x, z2), _carved_low(x, z2)) > RUN_H for x, y, z2 in dens]
        i = 0
        while i < len(dens):
            if not high[i]:
                i += 1
                continue
            j = i
            while j < len(dens) and high[j]:
                j += 1
            a = max(0, i - 1); b = min(len(dens), j + 1)   # pad one sample past each hang edge
            run = dens[a:b]
            arc = sum(math.hypot(run[k][0] - run[k - 1][0], run[k][2] - run[k - 1][2])
                      for k in range(1, len(run)))
            if len(run) >= 2 and arc >= RUN_ARC:
                via_jobs.append((eid, run, half)); n_runs += 1
            i = j
    if n_runs:
        print(f"  bridge runs: {n_runs} at-grade deck spans over carved ground get slab + piers")
    all_piers = []
    for _veid, dpts, vhalf in via_jobs:
        struct, piers = _viaduct_struct(dpts, _terr_min, vhalf, skip_column=_col_blocks)
        viaduct_meshes.append(struct)
        all_piers.extend(piers)
    (data / "network.piers.json").write_text(json.dumps(all_piers), encoding="utf-8")
    print(f"  viaducts: {len(via_jobs)} decks, {len(all_piers)} piers (columns under roads suppressed)")

    # VERGE GAP: no physical grass over a deck, no grass shoulder hanging in the sky. Drop shoulder
    # triangles over pavement (grade-separated crossings, loop ramps over their own lower winding,
    # superelevated parallel overlaps) and triangles hanging >HANG_MAX_M over the carved ground
    # (viaduct/overpass edges are concrete, not grass). Triangle-exact vs the built ribbons.
    verge_meshes = _filter_verge_over_roads(verge_meshes, _road_tri_hash(road_meshes),
                                            ground_at=_carved_y)

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

    _dry_only = bool((cfg.raw.get("scenery", {}) or {}).get("dry_only", False))

    def is_lawn(cx, cz, relief):
        if _dry_only:                     # Colorado high plains: all dry chaparral, no irrigated green lawn
            return False
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

    # corridor mask: keep only grass tiles within GBUF of a road, so the empty middle between far-apart
    # tracks (Sand Creek <-> Second Creek/IMI) doesn't bloat the mesh by ~1M tris of undrivable grass.
    from collections import defaultdict as _dd2
    RCELL2, GBUF = 500.0, 500.0
    _rb = _dd2(list)
    for _pr, _p, _w in edge_local:
        for _x, _y, _z in _p:
            _rb[(int(_x // RCELL2), int(_z // RCELL2))].append((_x, _z))

    # track discs: drop network grass from UNDER each merged detailed track (Sand Creek, IMI, ...) so its
    # OWN dry-grass heightfield shows at the reconciled height instead of the coarse network ground z-fighting
    # or poking through. Footprints are horizontal-only (no heightfield needed), shared with merge_detailed.
    # Clear network grass TIGHTLY around each merged track's ROADS (not a coarse circle — that left grass
    # over the deck at the near side and voids in the track's corners). CLEAR_R ~ the track's own grass
    # margin, so its own ground takes over exactly where the network grass stops. Road points are horizontal.
    CLEAR_R = 34.0
    _troad_hash = defaultdict(list)
    try:
        from scripts.ac.merge_detailed import track_road_points
        for _tx, _tz in track_road_points(proj):
            _troad_hash[(int(_tx // CLEAR_R), int(_tz // CLEAR_R))].append((_tx, _tz))
    except Exception as _e:  # noqa: BLE001 — never let the pad-clear fail the whole build
        print(f"  (track grass clear skipped: {_e})")
    if _troad_hash:
        print(f"  clearing network grass within {CLEAR_R:.0f} m of {sum(len(v) for v in _troad_hash.values())} track road pts")

    def pad_reject(cx, cz):     # per-triangle: drop network grass hugging any detailed-track road (its own ground shows)
        ci, cj = int(cx // CLEAR_R), int(cz // CLEAR_R)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for tx, tz in _troad_hash.get((ci + di, cj + dj), ()):
                    if (cx - tx) ** 2 + (cz - tz) ** 2 < CLEAR_R * CLEAR_R:
                        return True
        return False

    def keep_tile(x0, z0, x1, z1):     # prune tiles with NO road nearby (empty-middle bloat on the long corridor)
        for ci in range(int((x0 - GBUF) // RCELL2), int((x1 + GBUF) // RCELL2) + 1):
            for cj in range(int((z0 - GBUF) // RCELL2), int((z1 + GBUF) // RCELL2) + 1):
                for rx, rz in _rb.get((ci, cj), ()):
                    if x0 - GBUF <= rx <= x1 + GBUF and z0 - GBUF <= rz <= z1 + GBUF:
                        return True
        return False
    # Save the FINAL conformed+clamped ground (axis-aligned regular grid in local X-Z) so build_network_env
    # can sit trees/bushes/water ON the real grass mesh instead of the raw heightfield — else props float
    # wherever the terrain was conformed to a road or clamped for poke.
    _save_ground_local(data, grid_xyz)
    grass_tiles = _grass_tiles(grid_xyz, is_lawn=is_lawn, keep_tile=keep_tile, pad_reject=pad_reject)
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
    groups += _pack_groups("KERB_edge", "kerb", kerb_meshes)   # visual curbs (no 1-prefix -> not physical)
    groups += _pack_groups("1GRASS_verge", "grass", verge_meshes)
    groups += _pack_groups("1WALL_part", "barrier", wall_meshes)   # physical freeway barrier (KEY=WALL)
    groups += _pack_groups("1RUNOFF_median", "runoff", median_meshes)   # flat drivable median between carriageways
    groups += _pack_groups("MARKINGS_part", "markings", marking_meshes)   # visual lane lines (no 1-prefix)
    groups += via_groups

    nv, nf = write_obj(data / "track.obj", "track.mtl", groups)
    _write_mtl(data / "track.mtl")

    # Per-track spawns: each layout with a "spawn" anchor gets its OWN dummy set, written to
    # dummies_<id>.json -> exported as a tiny per-layout spawn kn5 (scripts/ac/build_spawn_kn5.py) that
    # models_<id>.ini loads ALONGSIDE the shared main kn5. The MAIN kn5 then carries NO spawns (empty
    # dummies.json) so there is no duplicate-AC_START conflict across the two models. This is how
    # "a start point at each track" works on one shared geometry mesh (CLAUDE.md layouts-share-one-kn5).
    layouts = cfg.raw.get("layouts", []) or []
    spawn_layouts = [lo for lo in layouts if lo.get("spawn")]
    if spawn_layouts:
        for lo in spawn_layouts:
            sp = lo["spawn"]
            dset = _freeroam_dummies(cfg, edge_local, to_local, anchor={"lon": sp["lon"], "lat": sp["lat"]})
            (data / f"dummies_{lo['id']}.json").write_text(json.dumps(dset, indent=1), encoding="utf-8")
        dummies = {}
        (data / "dummies.json").write_text(json.dumps(dummies), encoding="utf-8")
        print(f"per-layout spawns: {[lo['id'] for lo in spawn_layouts]} (main kn5 carries no spawns)")
    else:
        dummies = _freeroam_dummies(cfg, edge_local, to_local)
        (data / "dummies.json").write_text(json.dumps(dummies, indent=1), encoding="utf-8")
    # share the viaduct lift so build_network_env raises guardrails/poles/gantries onto the deck
    (data / "network.viaduct.json").write_text(json.dumps(viaduct_profiles), encoding="utf-8")

    # SUN FIX: resolve the model yaw that aligns the exported track with AC's world-fixed sun
    # (mirror_x tracks are spun 180deg vs the sun -> a 180deg counter-yaw applied at export). This is
    # written back + stored in local.json so build_kn5 (model) and track_folder (minimap) apply it.
    from scripts.lighting.csp_config import resolve_true_north
    yaw = resolve_true_north(cfg)
    cfg.write_back(true_north_rotation_deg=yaw)
    _write_local_meta(data, origin, elev0, mirror_x, len(F), yaw)

    road_groups = sum(1 for g in groups if g[0].startswith("1ROAD"))
    grass_groups = sum(1 for g in groups if g[0].startswith("1GRASS"))
    stats = {"edges": len(road_meshes), "vertices": nv, "triangles": nf,
             "road_groups": road_groups, "grass_groups": grass_groups, "viaducts": len(viaduct_meshes),
             "viaduct_groups": len(via_groups), "grid": f"{meta['nx']}x{meta['ny']}", "dummies": len(dummies),
             "origin_lonlat": [round(lon0, 6), round(lat0, 6)], "elev0_m": round(elev0, 1)}
    print("network mesh:", json.dumps(stats))
    # AUDIT at the end of every generative pass (mesh-audit skill): support-in-road / terrain-poke /
    # junction-crossing on the geometry just written. Reports; never fails the build (gate via the CLI).
    try:
        from scripts.geometry.audit_mesh import audit as _audit
        _audit(proj)
    except Exception as _ae:  # noqa: BLE001
        print(f"  (mesh audit skipped: {_ae})")
    return stats


def _freeroam_dummies(cfg, edge_local, to_local, anchor=None) -> dict[str, list[float]]:
    """Spawn the car SOLIDLY on a normal street near ``anchor`` (default cfg.location), facing the road.

    Must land on a continuous road ribbon: NOT at an edge tip (the ragged end of a ribbon — the car
    drops through there), NOT on a freeway (could be an elevated viaduct), and ABOVE the road surface
    (the ribbon sits ROAD_LIFT_M above the centreline + a spawn clearance, so the car drops onto it
    rather than spawning embedded under the one-sided collision plane)."""
    hl = anchor if anchor is not None else cfg.location
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
    # pit boxes: step BACK along the actual ribbon (so they follow curves on tight tracks) with a small
    # lateral offset that stays ON the asphalt — offsetting onto the verge drops the car / fails verify.
    for p in range(4):
        bi = max(0, best_i - (2 + p * 2))                 # ~4 m ribbon spacing -> ~8..32 m back
        bx, by, bz = best_pts[bi]
        j2 = min(bi + 1, len(best_pts) - 1)
        ex, ez = best_pts[j2][0] - bx, best_pts[j2][2] - bz
        el = math.hypot(ex, ez) or 1.0
        pnx, pnz = -ez / el, ex / el                       # local normal at bi (follows the curve)
        lat = (best_w * 0.30) * (1.0 if p % 2 else -1.0)   # alternate sides, stay on the ribbon
        out[f"AC_PIT_{p}"] = [round(bx + pnx * lat, 3), round(by + ROAD_LIFT_M + SPAWN_CLEAR, 3),
                              round(bz + pnz * lat, 3)]
    return out


def _write_local_meta(data: Path, origin, elev0, mirror_x, n_edges, true_north_deg=0.0) -> None:
    (data / "network.local.json").write_text(json.dumps({
        "frame": "ENU local meters (X=east, Y=up, Z=north), mirror_x=%s" % mirror_x,
        "origin": {"lon": origin[0], "lat": origin[1], "elev_m": round(elev0, 2)},
        "mirror_x": mirror_x, "true_north_rotation_deg": true_north_deg, "edge_count": n_edges,
    }), encoding="utf-8")


def _write_mtl(path: Path) -> None:
    path.write_text(
        "newmtl road\nKd 0.22 0.22 0.24\nKa 0.05 0.05 0.05\n\n"
        "newmtl grass\nKd 0.42 0.43 0.24\nKa 0.06 0.07 0.03\n\n"
        "newmtl lawn\nKd 0.30 0.42 0.20\nKa 0.05 0.07 0.03\n\n"
        "newmtl concrete\nKd 0.62 0.62 0.60\nKa 0.08 0.08 0.08\n\n"
        "newmtl barrier\nKd 0.70 0.69 0.66\nKa 0.09 0.09 0.09\n\n"
        "newmtl runoff\nKd 0.26 0.25 0.25\nKa 0.05 0.05 0.05\n\n"
        "newmtl markings\nKd 0.90 0.90 0.87\nKa 0.20 0.20 0.20\n\n"
        "newmtl kerb\nKd 0.80 0.78 0.72\nKa 0.10 0.10 0.09\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "projects/san-diego-cruise")
