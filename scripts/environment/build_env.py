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
from scripts.environment import buildings, signs

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
    verts, uvs, tris = [], [], []
    has_uv = bool(meshes) and all(m.get("uvs") for m in meshes)
    for m in meshes:
        off = len(verts)
        verts += m["vertices"]
        if has_uv:
            uvs += m["uvs"]
        tris += [(a + off, b + off, c + off) for a, b, c in m["tris"]]
    out = {"vertices": verts, "tris": tris}
    if has_uv:
        out["uvs"] = uvs
    return out


def _poly_area(poly):  # |shoelace| of a [(x,z)...] footprint, in m²
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % n]
        s += x0 * z1 - x1 * z0
    return abs(s) / 2.0


def _pip(x, z, poly):  # ray-cast point-in-polygon (poly = [(x,z)...])
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % n]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1 + 1e-12) + x1:
            inside = not inside
    return inside


def _corridor_rejecter(loop, widths, extra_lines=(), *, margin=3.0, cell=20.0):
    """Return ``on_road(x, z)`` → True when (x,z) is within (local road half-width + ``margin``) of ANY
    road centreline point — the MAIN loop plus any interior connectors. Spatial-hashed for speed.

    A purely local perpendicular offset (what the scatters use) keeps foliage off the road *next to the
    current point*, but not where the road folds back on itself (the corkscrew) or runs parallel a few
    metres away (the interior grid) — there a 7–40 m sideways throw lands on a DIFFERENT segment. Testing
    against the whole network fixes the 'bushes/trees through the road' clipping for any track."""
    pts = [(loop[i][0], loop[i][2], (widths[i] / 2.0 if i < len(widths) else 4.5)) for i in range(len(loop))]
    for ln, lw in extra_lines:
        for j, p in enumerate(ln):
            pts.append((p[0], p[2], (lw[j] / 2.0 if j < len(lw) else 4.5)))
    buckets = {}
    for px, pz, hw in pts:
        buckets.setdefault((int(px // cell), int(pz // cell)), []).append((px, pz, hw))

    def on_road(x, z):
        ci, cj = int(x // cell), int(z // cell)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for px, pz, hw in buckets.get((ci + di, cj + dj), ()):
                    if math.hypot(x - px, z - pz) < hw + margin:
                        return True
        return False

    return on_road


def _billboard(x, y, z, h=7.0, w=5.5, yaw=0.0):  # crossed tree billboards (two perpendicular cards) + UVs
    hw = w / 2
    c, s = math.cos(yaw), math.sin(yaw)               # per-instance yaw so the cross-quads aren't all
    ax, az = c * hw, s * hw                            # axis-aligned identical clones
    bx, bz = -s * hw, c * hw                           # perpendicular card
    verts = [(x - ax, y, z - az), (x + ax, y, z + az), (x + ax, y + h, z + az), (x - ax, y + h, z - az),
             (x - bx, y, z - bz), (x + bx, y, z + bz), (x + bx, y + h, z + bz), (x - bx, y + h, z - bz)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0), (1, 0), (1, 1), (0, 1)]  # V=0 trunk → V=1 canopy
    tris = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    return {"vertices": verts, "uvs": uvs, "tris": tris}


def _billboard_cell(x, y, z, col, row, ncols, nrows, h, w, yaw=0.0):
    """Crossed billboard mapped to one cell of a foliage atlas (ncols x nrows). V=0 (base) → bottom of
    the cell. Used for the dry scrub bushes (one random plant per billboard). yaw varies orientation."""
    hw = w / 2
    c, s = math.cos(yaw), math.sin(yaw)
    ax, az = c * hw, s * hw
    bx, bz = -s * hw, c * hw
    verts = [(x - ax, y, z - az), (x + ax, y, z + az), (x + ax, y + h, z + az), (x - ax, y + h, z - az),
             (x - bx, y, z - bz), (x + bx, y, z + bz), (x + bx, y + h, z + bz), (x - bx, y + h, z - bz)]
    u0, u1 = col / ncols, (col + 1) / ncols
    vb, vt = (nrows - 1 - row) / nrows, (nrows - row) / nrows   # bottom/top of cell (v=0 = image bottom)
    uvs = [(u0, vb), (u1, vb), (u1, vt), (u0, vt), (u0, vb), (u1, vb), (u1, vt), (u0, vt)]
    tris = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    return {"vertices": verts, "uvs": uvs, "tris": tris}


def _post(x, y, z, h=9.0, r=0.25):  # streetlight post (thin quad)
    return {"vertices": [(x - r, y, z), (x + r, y, z), (x + r, y + h, z), (x - r, y + h, z)],
            "tris": [(0, 1, 2), (0, 2, 3)]}


def _resample_xz(pts, step=8.0):
    """Resample a polyline of (x,y,z) to ~step spacing in the X-Z plane (y zeroed)."""
    seg = [0.0]
    for i in range(1, len(pts)):
        seg.append(seg[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2]))
    total = seg[-1]
    if total < step:
        return pts
    n = max(2, int(total / step))
    out, si = [], 1
    for s in range(n + 1):
        d = total * s / n
        while si < len(pts) - 1 and seg[si] < d:
            si += 1
        a, b = pts[si - 1], pts[si]
        den = (seg[si] - seg[si - 1]) or 1.0
        t = (d - seg[si - 1]) / den
        out.append((a[0] + (b[0] - a[0]) * t, 0.0, a[2] + (b[2] - a[2]) * t))
    return out


def _build_highways(env, project, ground_y, *, half_w=11.0, parapet=0.85, pier_w=1.4,
                    pier_step=24.0, min_len=240.0, smooth_win=22, bridge_gap=2.5):
    """Re-build the I-70 / US-36 decks ALONGSIDE the route from real OSM geometry. The deck rides the
    terrain crests but stays LEVEL over the dips, carried on PIERS (bridges) — instead of the old flat
    +5 m deck that floated over everything. Returns (deck[asphalt], struct[concrete parapets+slab+piers])."""
    dv, duv, dt = [], [], []
    sv, suv, stt = [], [], []

    def quad(V, UV, T, a, b, c, d, uvs):
        base = len(V); V += [a, b, c, d]; UV += uvs
        T += [(base, base + 1, base + 2), (base, base + 2, base + 3)]

    def column(cx, cz, y0, y1, w):
        h2 = w / 2.0
        c = [(cx - h2, cz - h2), (cx + h2, cz - h2), (cx + h2, cz + h2), (cx - h2, cz + h2)]
        base = len(sv)
        for bx, bz in c:
            sv.append((bx, y0, bz)); suv.append((0, 0))
        for bx, bz in c:
            sv.append((bx, y1, bz)); suv.append((0, 1))
        for i in range(4):
            j = (i + 1) % 4
            stt.extend([(base + i, base + j, base + j + 4), (base + i, base + j + 4, base + i + 4)])

    for f in env:
        if f.get("cls") != "highway" or f.get("kind") != "line" or len(f.get("coords", [])) < 2:
            continue
        raw = [project(lo, la) for lo, la in f["coords"]]
        if sum(math.hypot(raw[i][0] - raw[i - 1][0], raw[i][2] - raw[i - 1][2])
               for i in range(1, len(raw))) < min_len:
            continue
        pts = _resample_xz(raw)
        terr = [ground_y(x, z) for x, _, z in pts]
        sm = [sum(terr[max(0, i - smooth_win):i + smooth_win + 1]) /
              len(terr[max(0, i - smooth_win):i + smooth_win + 1]) for i in range(len(terr))]
        deck_e = [max(sm[i], terr[i] + 0.2) for i in range(len(terr))]   # ride crests, bridge dips
        edges = []
        for i in range(len(pts)):
            x, _, z = pts[i]
            a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]; tl = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / tl, tx / tl
            de = deck_e[i]
            edges.append(((x + nx * half_w, de, z + nz * half_w), (x - nx * half_w, de, z - nz * half_w),
                          (x, de, z), terr[i], nx, nz))
        for k in range(len(edges) - 1):
            L0, R0, C0, t0, _, _ = edges[k]
            L1, R1, C1, t1, _, _ = edges[k + 1]
            quad(dv, duv, dt, L0, R0, R1, L1, [(0, k), (1, k), (1, k + 1), (0, k + 1)])          # deck top
            bL0 = (L0[0], L0[1] - 0.7, L0[2]); bR0 = (R0[0], R0[1] - 0.7, R0[2])
            bL1 = (L1[0], L1[1] - 0.7, L1[2]); bR1 = (R1[0], R1[1] - 0.7, R1[2])
            quad(sv, suv, stt, bR0, bL0, bL1, bR1, [(0, 0), (1, 0), (1, 1), (0, 1)])             # underside
            quad(sv, suv, stt, L0, (L0[0], L0[1] + parapet, L0[2]),
                 (L1[0], L1[1] + parapet, L1[2]), L1, [(0, 0), (0, 1), (1, 1), (1, 0)])          # L parapet
            quad(sv, suv, stt, R1, (R1[0], R1[1] + parapet, R1[2]),
                 (R0[0], R0[1] + parapet, R0[2]), R0, [(0, 0), (0, 1), (1, 1), (1, 0)])          # R parapet
        acc = pier_step
        for k in range(len(edges)):
            if k > 0:
                acc += math.hypot(edges[k][2][0] - edges[k - 1][2][0], edges[k][2][2] - edges[k - 1][2][2])
            _, _, C, t, _, _ = edges[k]
            if C[1] - t > bridge_gap and acc >= pier_step:
                acc = 0.0
                column(C[0], C[2], t - 0.4, C[1] - 0.6, pier_w)                                  # bridge pier
    return {"vertices": dv, "uvs": duv, "tris": dt}, {"vertices": sv, "uvs": suv, "tris": stt}


def _box_column(cx, cz, y0, y1, w):
    """A square concrete column from y0 to y1 (4 sides). Returns (verts, tris) to append into a mesh."""
    h = w / 2.0
    c = [(cx - h, cz - h), (cx + h, cz - h), (cx + h, cz + h), (cx - h, cz + h)]
    verts = [(x, y0, z) for x, z in c] + [(x, y1, z) for x, z in c]
    tris = []
    for i in range(4):
        j = (i + 1) % 4
        tris += [(i, j, j + 4), (i, j + 4, i + 4)]
    return verts, tris


def _creek_bridge(loop, widths, env, project, ground_y, *, parapet=1.0, thick=0.7, pad=4):
    """Dress the route's creek crossing (Quebec over Sand Creek) as a bridge: concrete parapets along
    both road edges, an underside slab, and piers down into the water. The drivable road surface stays
    (it's the track mesh); this is the structure around/under it. Returns a concrete mesh."""
    wp = [project(lo, la) for f in env if f.get("cls") == "water" for lo, la in f.get("coords", [])]
    from collections import defaultdict
    C = 40.0
    wb = defaultdict(list)
    for x, _, z in wp:
        wb[(int(x // C), int(z // C))].append((x, z))

    def near_w(x, z):
        ci, cj = int(x // C), int(z // C); best = 1e18
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for wx, wz in wb.get((ci + di, cj + dj), ()):
                    best = min(best, (x - wx) ** 2 + (z - wz) ** 2)
        return math.sqrt(best)

    n = len(loop)
    flag = [near_w(loop[i][0], loop[i][2]) < widths[i] / 2 + 8 for i in range(n)]
    spans, i = [], 0
    while i < n:
        if flag[i]:
            j = i
            while j < n and flag[j]:
                j += 1
            spans.append((max(1, i - pad), min(n - 1, j + pad))); i = j
        else:
            i += 1
    V, UV, T = [], [], []

    def quad(a, b, c, d):
        base = len(V); V.extend([a, b, c, d]); UV.extend([(0, 0), (1, 0), (1, 1), (0, 1)])
        T.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])

    for a, b in spans:
        rows = []
        for k in range(a, b + 1):
            x, y, z = loop[k]
            pa, pb = loop[max(0, k - 1)], loop[min(n - 1, k + 1)]
            tx, tz = pb[0] - pa[0], pb[2] - pa[2]; tl = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / tl, tx / tl
            hw = widths[k] / 2 + 0.3
            rows.append(((x + nx * hw, y + ROAD_LIFT_M, z + nz * hw),
                         (x - nx * hw, y + ROAD_LIFT_M, z - nz * hw), (x, y, z)))
        for k in range(len(rows) - 1):
            L0, R0, _ = rows[k]; L1, R1, _ = rows[k + 1]
            quad(L0, (L0[0], L0[1] + parapet, L0[2]), (L1[0], L1[1] + parapet, L1[2]), L1)   # L rail
            quad(R1, (R1[0], R1[1] + parapet, R1[2]), (R0[0], R0[1] + parapet, R0[2]), R0)   # R rail
            bL0 = (L0[0], L0[1] - thick, L0[2]); bR0 = (R0[0], R0[1] - thick, R0[2])
            bL1 = (L1[0], L1[1] - thick, L1[2]); bR1 = (R1[0], R1[1] - thick, R1[2])
            quad(bR0, bL0, bL1, bR1)                                                          # underside
        for frac in (0.33, 0.66):                                                            # piers in the water
            x, y, z = loop[int(a + (b - a) * frac)]
            cv, ct = _box_column(x, z, ground_y(x, z) - 0.6, y - thick, 1.1)
            base = len(V); V.extend(cv); UV.extend([(0, 0)] * len(cv)); T.extend([(base + p, base + q, base + r) for p, q, r in ct])
    return {"vertices": V, "uvs": UV, "tris": T}


def build(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    cfg = load_config(project_dir)
    local = json.loads((data / "centerline.local.json").read_text())
    origin = (local["origin"]["lon"], local["origin"]["lat"])
    elev0 = local["origin"]["elev_m"]
    loop = [tuple(p) for p in local["points_xyz_m"]]
    widths = local["widths_m"]

    # MIRROR_X (must match build_mesh): mirror the east axis of everything so the scenery lines up with
    # the mirrored track. Visual mesh winding is reversed at the end (a mirror flips it inside-out).
    mirror_x = bool(cfg.raw.get("mirror_x", False))
    sx = -1.0 if mirror_x else 1.0
    if mirror_x:
        loop = [(-x, y, z) for (x, y, z) in loop]

    grid = read_npy(data / "heightfield.npy")
    meta = json.loads((data / "heightfield.meta.json").read_text())
    grid, meta = ribbon.upsample_grid(grid, meta, 3)  # 40 m → ~13 m so grading hugs the road cleanly
    y_at = _grid_sampler(grid, meta, elev0)
    m_lon, m_lat = _meters_per_degree(origin[1])

    def project(lon, lat):
        return (sx * (lon - origin[0]) * m_lon, y_at(lon, lat), (lat - origin[1]) * m_lat)

    def ground_y(x, z):
        """Terrain height under a LOCAL (mirrored) x,z — inverts the projection (incl. mirror) before
        sampling the heightfield, so scattered foliage sits on the real ground, not a mirror-image of it."""
        return y_at(origin[0] + sx * x / m_lon, origin[1] + z / m_lat)

    env = json.loads((data / "environment.geojson").read_text())["features"]
    gj = json.loads((data / "centerline.geojson").read_text())["features"]

    # --- track + interior connector ---
    grid_xyz = project_grid(grid, meta, origin, elev0, mirror_x=mirror_x)
    ribbon.conform_terrain_to_road(grid_xyz, loop, widths)  # grade terrain to the road (no dipping)
    grass = ribbon.grass_terrain(grid_xyz)
    road = ribbon.road_ribbon(loop, widths)
    road["vertices"] = [(x, y + ROAD_LIFT_M, z) for x, y, z in road["vertices"]]
    kerb = kerbs.corner_kerbs(loop, widths)
    kerb["vertices"] = [(x, y + ROAD_LIFT_M + 0.02, z) for x, y, z in kerb["vertices"]]
    # connector "side roads" DISABLED — they were bare raised ribbons with no shoulders, reading as
    # concrete slabs jutting out of the ground, and aren't part of the drivable lap. (If interior
    # connectors become real layout variants later, they need shoulders + terrain blend like 1ROAD.)
    connector = {"vertices": [], "uvs": [], "tris": []}

    # --- water (Sand Creek lines + basins) ---
    water = _merge([_line_ribbon(f["coords"], project, 4.0, -0.3) if f["kind"] == "line"
                    else _fan(f["coords"], project, -0.3)
                    for f in env if f["cls"] == "water"])
    # --- highways: I-70 / US-36 decks ALONGSIDE the route (real OSM geometry), riding the terrain
    #     crests but staying LEVEL over the dips on piers (bridges). Re-enabled + fixed (the old version
    #     floated a flat +5 m deck over the track). hwy_struct = parapets + underside slab + piers. ---
    hwy_deck, hwy_struct = _build_highways(env, project, ground_y)
    # Quebec-over-Sand-Creek bridge: parapets + underside + piers around the route's creek crossing.
    bridge = _creek_bridge(loop, widths, env, project, ground_y)

    # --- scenery knobs (per-track, config-driven; defaults reproduce the original Sand Creek look) and
    #     the road-corridor index that keeps every scatter OFF the asphalt for ANY track ---
    import random
    scn = cfg.raw.get("scenery", {})
    connector_lines = []
    cpath = data / "connectors.local.json"
    if cpath.exists():
        for c in json.loads(cpath.read_text()).get("connectors", []):
            cp = c.get("points_xyz_m", [])
            cw = c.get("widths_m", [])
            if mirror_x:
                cp = [(-p[0], p[1], p[2]) for p in cp]
            connector_lines.append((cp, cw))
    on_road = _corridor_rejecter(loop, widths, connector_lines,
                                 margin=float(scn.get("corridor_margin_m", 3.0)))

    # --- trees scattered in green/wetland polygons (capped) ---
    tree_meshes, ntrees = [], 0
    _tg = random.Random(55)
    t_step = float(scn.get("tree_step_m", 28.0))
    t_cap = int(scn.get("tree_cap", 700))
    for f in env:
        if f["cls"] not in ("green", "wetland") or f["kind"] != "poly" or len(f["coords"]) < 3:
            continue
        poly = [(project(lo, la)[0], project(lo, la)[2]) for lo, la in f["coords"]]
        xs = [p[0] for p in poly]; zs = [p[1] for p in poly]
        step = t_step
        gx = int((max(xs) - min(xs)) / step)
        gz = int((max(zs) - min(zs)) / step)
        for ix in range(gx + 1):
            for iz in range(gz + 1):
                x = min(xs) + ix * step + (iz % 2) * 9
                z = min(zs) + iz * step
                if ntrees < t_cap and _pip(x, z, poly) and not on_road(x, z):
                    h = 5.5 + _tg.random() * 4.0                  # 5.5..9.5 m (was a fixed 7) — break the clones
                    tree_meshes.append(_billboard(x, ground_y(x, z), z, h=h, w=h * 0.72,
                                                  yaw=_tg.random() * math.pi))
                    ntrees += 1

    # DENSE riparian trees along Sand Creek (the green corridor — cottonwoods/willows on the banks).
    import random as _trnd
    _tr = _trnd.Random(77)
    nriver = 0
    for f in env:
        if f.get("cls") != "water" or f.get("kind") != "line" or len(f.get("coords", [])) < 2:
            continue
        pls = [project(lo, la) for lo, la in f["coords"]]
        for i in range(1, len(pls)):
            x0, _, z0 = pls[i - 1]; x1, _, z1 = pls[i]
            seg = math.hypot(x1 - x0, z1 - z0)
            tx, tz = (x1 - x0) / (seg or 1), (z1 - z0) / (seg or 1)
            nx, nz = -tz, tx
            for s in range(max(1, int(seg / 8))):           # ~ every 8 m along the bank
                t = s / max(1, int(seg / 8))
                bx, bz = x0 + (x1 - x0) * t, z0 + (z1 - z0) * t
                for side in (1.0, -1.0):
                    if _tr.random() > 0.8:                  # dense but not a solid wall
                        continue
                    off = 5.0 + _tr.random() * 18.0         # 5..23 m off the water, on the banks
                    rx, rz = bx + nx * off * side, bz + nz * off * side
                    if on_road(rx, rz):                     # the road crosses the creek (bridge) — keep off it
                        continue
                    h = 6.0 + _tr.random() * 5.0            # 6..11 m cottonwoods
                    tree_meshes.append(_billboard(rx, ground_y(rx, rz), rz, h=h, w=h * 0.7,
                                                  yaw=_tr.random() * math.pi))
                    nriver += 1
    trees = _merge(tree_meshes)

    # --- dry scrub bushes scattered trackside (the dry-prairie look: sparse low shrubs on dirt) ---
    _r = random.Random(1234)                        # seeded → reproducible
    bush_meshes, nbush = [], 0
    NC, NR = 3, 3                                    # bo_bushes_11 atlas = 3x3 dry plants
    b_spacing = float(scn.get("bush_spacing_m", 6.0))
    b_density = float(scn.get("bush_density", 0.55))
    b_off_min = float(scn.get("bush_off_min_m", 7.0))
    b_off_span = float(scn.get("bush_off_span_m", 33.0))
    b_sz_min = float(scn.get("bush_size_min_m", 1.2))
    b_sz_span = float(scn.get("bush_size_span_m", 1.4))
    acc = 0.0
    for i in range(1, len(loop)):
        acc += math.hypot(loop[i][0] - loop[i - 1][0], loop[i][2] - loop[i - 1][2])
        if acc < b_spacing:
            continue
        acc = 0.0
        x, y, z = loop[i]
        a, b = loop[i - 1], loop[min(len(loop) - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]
        tl = math.hypot(tx, tz) or 1e-6
        nx, nz = -tz / tl, tx / tl
        for side in (1.0, -1.0):
            if _r.random() > b_density:             # sparse — dry prairie, not a hedge
                continue
            off = widths[i] / 2 + b_off_min + _r.random() * b_off_span   # off the road, out on the grass
            bx, bz = x + nx * off * side, z + nz * off * side
            if on_road(bx, bz):                     # reject where the throw lands on a fold-back/parallel road
                continue
            by = ground_y(bx, bz) - 0.4             # seat into the ground (correct height even when mirrored)
            sz = b_sz_min + _r.random() * b_sz_span
            bush_meshes.append(_billboard_cell(bx, by, bz, _r.randint(0, NC - 1), _r.randint(0, NR - 1),
                                               NC, NR, sz * 0.78, sz, yaw=_r.random() * math.pi))
            nbush += 1
    bushes = _merge(bush_meshes)

    # --- streetlights along the lap (~ every 48 m, on the right verge) ---
    light_meshes, nlights = [], 0
    l_spacing = float(scn.get("light_spacing_m", 48.0))
    acc = 0.0
    for i in range(1, len(loop)):
        acc += math.hypot(loop[i][0] - loop[i - 1][0], loop[i][2] - loop[i - 1][2])
        if acc >= l_spacing:
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

    # --- Front Range backdrop: hazy ridges far to the (real) WEST. Placed by real longitude so the
    #     projection + mirror drop it at true west in-game, and the physical CSP sun (true-north, real
    #     lat/lon) then SETS BEHIND it. Flat double-sided silhouettes; CSP aerial haze blurs them. ---
    import random as _mrnd
    _mr = _mrnd.Random(9)
    mnt_v, mnt_t = [], []
    for layer, (dlon, base_h, amp) in enumerate([(-0.10, 560.0, 240.0), (-0.15, 920.0, 340.0)]):
        wlon = origin[0] + dlon                      # west of the origin
        prev = None
        for i in range(81):
            lat = origin[1] - 0.11 + 0.22 * i / 80
            x = sx * (wlon - origin[0]) * m_lon       # mirror-aware: ends up at true west in-game
            z = (lat - origin[1]) * m_lat
            h = base_h + amp * (0.5 * math.sin(i * 0.4 + layer) + 0.3 * math.sin(i * 1.3 + layer * 2)
                                + 0.2 * (2 * _mr.random() - 1))
            b = len(mnt_v)
            mnt_v.append((x, -200.0, z)); mnt_v.append((x, max(250.0, h), z))
            if prev is not None:
                p0, p1 = prev
                mnt_t += [(p0, p1, b + 1), (p0, b + 1, b), (p0, b + 1, p1), (p0, b, b + 1)]  # double-sided
            prev = (b, b + 1)
    mountains = {"vertices": mnt_v, "tris": mnt_t}

    # --- buildings from OSM footprints (extruded boxes: walls + corrugated roofs) ---
    bld_path = data / "buildings.geojson"
    bld = json.loads(bld_path.read_text())["buildings"] if bld_path.exists() else []
    loop_xz = [(p[0], p[2]) for p in loop[::4]]
    # Commerce City reads as industrial: big footprints = metal WAREHOUSES (corrugated skin), smaller
    # ones = concrete/commercial. Splitting the walls by footprint area gives that variety instead of a
    # field of identical grey boxes. Bury the base 2.5 m so boxes never float off sloped ground.
    warehouse_walls, commercial_walls, roof_meshes, nbld = [], [], [], 0
    for b in bld:
        foot = [(project(lo, la)[0], project(lo, la)[2]) for lo, la in b["coords"]]
        if len(foot) < 3 or _poly_area(foot) < 35:  # skip tiny sheds / noise
            continue
        cx = sum(p[0] for p in foot) / len(foot)
        cz = sum(p[1] for p in foot) / len(foot)
        if min(math.hypot(cx - lx, cz - lz) for lx, lz in loop_xz) > 330:  # keep near-lap only
            continue
        # ...but never ON the track: drop any building whose footprint crowds the drivable surface
        # (within 16 m of the racing line) so buildings don't sit over the road.
        if min(math.hypot(fx - lx, fz - lz) for fx, fz in foot for lx, lz in loop_xz) < 16.0:
            continue
        bury = 2.5
        base = min(y_at(lo, la) for lo, la in b["coords"]) - bury  # sink so it meets the ground on slopes
        box = buildings.extrude(foot, base, b["height_m"] + bury)   # +bury so the roof stays at true height
        (warehouse_walls if _poly_area(foot) > 700 else commercial_walls).append(box["walls"])
        roof_meshes.append(box["roof"])
        nbld += 1
    bld_warehouse = _merge(warehouse_walls)
    bld_commercial = _merge(commercial_walls)
    bld_roofs = _merge(roof_meshes)

    # --- street-name signs: DISABLED — the corner->street mapping was wrong (mislabeled) and the
    #     panel UVs were flipped. Redo with real OSM road-name matching + corrected UVs before re-enabling.
    #     (signs.build_signs / render_atlas remain for that pass.)

    # mirroring the east axis flips every face inside-out; reverse the visual meshes' winding so they
    # render front-side again (the drivable track handles this via orient_up in build_mesh).
    if mirror_x:
        for _m in (water, bld_commercial, bld_warehouse, bld_roofs, trees, bushes, lights,
                   hwy_deck, hwy_struct, bridge):
            _m["tris"] = [(a, c, b) for (a, b, c) in _m["tris"]]

    # --- write environment OBJ + dressed render ---
    write_obj(data / "environment.obj", "environment.mtl",
              [("WATER", "grass", water), ("BUILDINGS", "road", bld_commercial),
               ("WAREHOUSE", "road", bld_warehouse), ("ROOFS", "road", bld_roofs),
               ("TREES", "grass", trees), ("BUSHES", "grass", bushes), ("LIGHTS", "road", lights),
               ("MOUNTAINS", "grass", mountains), ("HIGHWAY", "road", hwy_deck),
               ("HWYSTRUCT", "road", hwy_struct), ("HWYSTRUCT_bridge", "road", bridge)])
    write_mtl(data / "environment.mtl")
    render_iso([("grass", (0.30, 0.47, 0.22), grass), ("water", (0.16, 0.45, 0.74), water),
                ("buildings", (0.58, 0.55, 0.50), bld_commercial), ("warehouse", (0.50, 0.52, 0.55), bld_warehouse),
                ("roofs", (0.42, 0.42, 0.45), bld_roofs), ("road", (0.82, 0.83, 0.86), road),
                ("connector", (0.74, 0.76, 0.80), connector), ("kerb", (0.88, 0.24, 0.20), kerb),
                ("trees", (0.18, 0.42, 0.16), trees), ("lights", (0.95, 0.85, 0.35), lights)],
               {}, data / "dressed_render.svg")

    return {"connector_pts": len(connector["vertices"]) // 2, "water_tris": len(water["tris"]),
            "highway_deck_tris": len(hwy_deck["tris"]), "highway_struct_tris": len(hwy_struct["tris"]),
            "buildings": nbld, "trees": ntrees, "bushes": nbush, "river_trees": nriver,
            "streetlights": nlights, "render": str(data / "dressed_render.svg")}


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
