"""Trackside scenery geometry — signs, lights, fences, walls, highway structures, tanks, rail.

Every builder is a pure function over local-ENU-metre inputs (X-east, Y-up, Z-north) returning
``{"vertices", "uvs", "tris"}`` meshes, deterministic via seeded ``random.Random``. Placement is
data-driven: OSM nodes/ways from ``scenery_fetch``, curvature runs from the centerline, atlas UV
rects from ``texgen``'s manifest. Pure stdlib (runs on the build host's system Python).

Winding: AC renders/collides one-sided; the convention here (matching ``orient_up``) is
counter-clockwise seen from the front in the Y-up right-handed OBJ frame. Thin geometry (sign
faces, fences, billboards, walls) is emitted double-sided.
"""

from __future__ import annotations

import math
import random

Vertex = tuple[float, float, float]
Mesh = dict


def empty() -> Mesh:
    return {"vertices": [], "uvs": [], "tris": []}


def merge(meshes: list[Mesh]) -> Mesh:
    out = empty()
    for m in meshes:
        off = len(out["vertices"])
        out["vertices"] += m["vertices"]
        out["uvs"] += m.get("uvs") or [(0.0, 0.0)] * len(m["vertices"])
        out["tris"] += [(a + off, b + off, c + off) for a, b, c in m["tris"]]
    return out


def chunk(meshes: list[Mesh], max_verts: int = 60000) -> list[Mesh]:
    """Merge meshes into as few buckets as possible while keeping each under the kn5 vertex limit."""
    out: list[list[Mesh]] = [[]]
    count = 0
    for m in meshes:
        n = len(m["vertices"])
        if count + n > max_verts and out[-1]:
            out.append([])
            count = 0
        out[-1].append(m)
        count += n
    return [merge(group) for group in out if group]


def quad(bl: Vertex, br: Vertex, tr: Vertex, tl: Vertex,
         uv: tuple = ((0, 0), (1, 0), (1, 1), (0, 1)), *, double: bool = False) -> Mesh:
    """Front face = CCW(bl→br→tr→tl). ``double`` emits the back face too."""
    verts = [bl, br, tr, tl]
    uvs = list(uv)
    tris = [(0, 1, 2), (0, 2, 3)]
    if double:
        tris += [(0, 2, 1), (0, 3, 2)]
    return {"vertices": verts, "uvs": uvs, "tris": tris}


def box(cx: float, base: float, cz: float, w: float, d: float, h: float, *,
        ry: float = 0.0, uv_scale: float = 1.0, top: bool = True) -> Mesh:
    """Axis-aligned box rotated ``ry`` about Y, outward-facing, perimeter-mapped UVs."""
    hw, hd = w / 2.0, d / 2.0
    c, s = math.cos(ry), math.sin(ry)

    def pt(x, y, z):
        return (cx + x * c - z * s, y, cz + x * s + z * c)

    t = base + h
    walls = [
        quad(pt(-hw, base, hd), pt(hw, base, hd), pt(hw, t, hd), pt(-hw, t, hd),
             ((0, 0), (w / uv_scale, 0), (w / uv_scale, h / uv_scale), (0, h / uv_scale))),
        quad(pt(hw, base, -hd), pt(-hw, base, -hd), pt(-hw, t, -hd), pt(hw, t, -hd),
             ((0, 0), (w / uv_scale, 0), (w / uv_scale, h / uv_scale), (0, h / uv_scale))),
        quad(pt(hw, base, hd), pt(hw, base, -hd), pt(hw, t, -hd), pt(hw, t, hd),
             ((0, 0), (d / uv_scale, 0), (d / uv_scale, h / uv_scale), (0, h / uv_scale))),
        quad(pt(-hw, base, -hd), pt(-hw, base, hd), pt(-hw, t, hd), pt(-hw, t, -hd),
             ((0, 0), (d / uv_scale, 0), (d / uv_scale, h / uv_scale), (0, h / uv_scale))),
    ]
    if top:
        walls.append(quad(pt(-hw, t, hd), pt(hw, t, hd), pt(hw, t, -hd), pt(-hw, t, -hd),
                          ((0, 0), (w / uv_scale, 0), (w / uv_scale, d / uv_scale), (0, d / uv_scale))))
    return merge(walls)


def cylinder(cx: float, base: float, cz: float, r: float, h: float, *, segs: int = 16,
             cap: bool = True, u_tiles: float | None = None, v01: bool = True) -> Mesh:
    """Vertical cylinder, outward-facing. U spans ``u_tiles`` around (default circumference/4 m),
    V spans 0..1 up the height (or metres/4 if ``v01`` False)."""
    if u_tiles is None:
        u_tiles = max(1.0, round(2 * math.pi * r / 4.0))
    vmax = 1.0 if v01 else h / 4.0
    verts: list[Vertex] = []
    uvs = []
    tris = []
    for i in range(segs + 1):
        a = 2 * math.pi * i / segs
        x, z = cx + r * math.cos(a), cz + r * math.sin(a)
        verts += [(x, base, z), (x, base + h, z)]
        u = u_tiles * i / segs
        uvs += [(u, 0.0), (u, vmax)]
    for i in range(segs):
        b = 2 * i
        # angle increases CCW seen from above; swap order so faces point outward
        tris += [(b + 2, b, b + 1), (b + 2, b + 1, b + 3)]
    if cap:
        c0 = len(verts)
        for i in range(segs):
            a = 2 * math.pi * i / segs
            verts.append((cx + r * math.cos(a), base + h, cz + r * math.sin(a)))
            uvs.append((0.5 + 0.45 * math.cos(a), 0.5 + 0.45 * math.sin(a)))
        for i in range(1, segs - 1):
            tris.append((c0, c0 + i + 1, c0 + i))  # up-facing fan
    return {"vertices": verts, "uvs": uvs, "tris": tris}


# ------------------------------------------------------------------ lap stations

class Lap:
    """Arc-length lookup over the closed centerline: position/tangent/left-normal/width at any s."""

    def __init__(self, loop: list[Vertex], widths: list[float]):
        self.pts = loop
        self.widths = widths
        self.arc = [0.0]
        for i in range(1, len(loop)):
            self.arc.append(self.arc[-1] + math.hypot(loop[i][0] - loop[i - 1][0],
                                                      loop[i][2] - loop[i - 1][2]))
        self.total = self.arc[-1]
        # spatial buckets for distance queries
        self._cell = 60.0
        self._buckets: dict = {}
        for i, p in enumerate(loop):
            self._buckets.setdefault((int(p[0] // self._cell), int(p[2] // self._cell)), []).append(i)

    def sample(self, s: float) -> tuple[Vertex, tuple[float, float], float]:
        """(point, unit XZ tangent, width) at arc-length s (wraps)."""
        s %= self.total
        lo, hi = 0, len(self.arc) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.arc[mid] < s:
                lo = mid + 1
            else:
                hi = mid
        i = max(1, lo)
        t = (s - self.arc[i - 1]) / max(1e-6, self.arc[i] - self.arc[i - 1])
        a, b = self.pts[i - 1], self.pts[i]
        p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
        tx, tz = b[0] - a[0], b[2] - a[2]
        L = math.hypot(tx, tz) or 1e-6
        w = self.widths[i - 1] + (self.widths[i] - self.widths[i - 1]) * t
        return p, (tx / L, tz / L), w

    def nearest(self, x: float, z: float, reach: float = 130.0) -> tuple[float, int]:
        """(distance, index) of the nearest centerline vertex within ``reach`` (else (inf, -1))."""
        ci, cj = int(x // self._cell), int(z // self._cell)
        n = int(reach // self._cell) + 1
        best, bi = float("inf"), -1
        for di in range(-n, n + 1):
            for dj in range(-n, n + 1):
                for i in self._buckets.get((ci + di, cj + dj), ()):
                    p = self.pts[i]
                    d = math.hypot(p[0] - x, p[2] - z)
                    if d < best:
                        best, bi = d, i
        return best, bi


def corner_runs(loop: list[Vertex], *, thr: float = 0.007, min_run: int = 5) -> list[dict]:
    """Curvature runs: [{i0, i1, side(+1 left), peak}]. Unlike the kerb detector, a run BREAKS
    when the turn direction flips — an S-complex is two runs with their own sides, otherwise the
    "outside" of the second half is wrong and anything placed there lands on the road."""
    from scripts.geometry.kerbs import _smooth, _turn_rate
    rate = _smooth(_turn_rate(loop))
    runs = []
    i, n = 0, len(loop)
    while i < n:
        if abs(rate[i]) <= thr:
            i += 1
            continue
        j = i
        s0 = 1.0 if rate[i] > 0 else -1.0
        while j < n and abs(rate[j]) > thr and (rate[j] > 0) == (s0 > 0):
            j += 1
        if j - i >= min_run:
            runs.append({"i0": i, "i1": j, "side": s0,
                         "peak": max(abs(rate[k]) for k in range(i, j))})
        i = j
    return runs


# the clearance index lives in the geometry layer (build_mesh needs it for kerbs too);
# re-exported here for the environment builders
from scripts.geometry.clearance import RoadClearance  # noqa: E402,F401


def _seg_hit(p1, p2, q1, q2):
    """XZ segment intersection point or None."""
    x1, z1, x2, z2 = p1[0], p1[1], p2[0], p2[1]
    x3, z3, x4, z4 = q1[0], q1[1], q2[0], q2[1]
    den = (x1 - x2) * (z3 - z4) - (z1 - z2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    t = ((x1 - x3) * (z3 - z4) - (z1 - z3) * (x3 - x4)) / den
    u = ((x1 - x3) * (z1 - z2) - (z1 - z3) * (x1 - x2)) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (x1 + t * (x2 - x1), z1 + t * (z2 - z1))
    return None


# ------------------------------------------------------------------ sign assemblies

def _sign_face(x: float, y: float, z: float, w: float, h: float, facing: tuple[float, float],
               uv_rect: list[float], *, mirror_u: bool = False) -> Mesh:
    """Double-sided sign plate centred at (x,y,z), front toward ``facing`` (unit XZ)."""
    fx, fz = facing
    rx, rz = -fz, fx  # right vector when looking along -facing (viewer in front)
    u0, v0, u1, v1 = uv_rect
    if mirror_u:
        u0, u1 = u1, u0
    bl = (x - rx * w / 2, y - h / 2, z - rz * w / 2)
    br = (x + rx * w / 2, y - h / 2, z + rz * w / 2)
    tr = (x + rx * w / 2, y + h / 2, z + rz * w / 2)
    tl = (x - rx * w / 2, y + h / 2, z - rz * w / 2)
    return quad(bl, br, tr, tl, ((u0, v0), (u1, v0), (u1, v1), (u0, v1)), double=True)


def _post(x: float, y: float, z: float, h: float, w: float = 0.07) -> Mesh:
    return box(x, y, z, w, w, h, uv_scale=max(h, 0.5), top=False)


def sign_assembly(p: Vertex, facing: tuple[float, float], uv_rect: list[float], *,
                  w: float = 0.75, h: float = 0.75, pole_h: float = 2.6,
                  mirror_u: bool = False) -> tuple[Mesh, Mesh]:
    """(pole mesh, face mesh) — face top sits at pole top."""
    pole = _post(p[0], p[1], p[2], pole_h)
    face = _sign_face(p[0], p[1] + pole_h - h / 2, p[2], w, h, facing, uv_rect, mirror_u=mirror_u)
    return pole, face


# ------------------------------------------------------------------ builders

def build_signs(lap: Lap, runs: list[dict], scenery: dict, manifest: dict,
                to_local, seed: int, clearance: "RoadClearance | None" = None) -> dict:
    """All roadside signage. Returns {"poles": [...], "faces": [...]} mesh lists."""
    rects = manifest["atlas"]["signs"]
    rng = random.Random(seed * 7 + 1)
    poles: list[Mesh] = []
    faces: list[Mesh] = []

    def plant(p, facing, rect, **kw):
        if clearance is not None and not clearance.clear(p[0], p[2], 0.35):
            return                              # would stand on a road surface — skip
        po, fa = sign_assembly(p, facing, rect, **kw)
        poles.append(po)
        faces.append(fa)

    def verge_point(s: float, side: float, extra: float = 1.6):
        p, (tx, tz), w = lap.sample(s)
        nx, nz = -tz * side, tx * side
        off = w / 2 + extra
        return (p[0] + nx * off, p[1], p[2] + nz * off), (tx, tz)

    # --- speed limits every ~650 m on the right verge, facing oncoming traffic
    s = 120.0
    i = 0
    while s < lap.total - 100:
        p, (tx, tz) = verge_point(s, -1.0)
        plant(p, (-tx, -tz), rects["speed35" if i % 2 == 0 else "speed45"],
              w=0.65, h=0.65, pole_h=2.8)
        s += 650.0
        i += 1

    # --- curve warnings ~95 m before each corner + chevrons at the apex (sharp corners only)
    for run in runs:
        if run["peak"] < 0.012:
            continue
        s0 = lap.arc[run["i0"]]
        s1 = lap.arc[min(run["i1"], len(lap.arc) - 1)]
        warn_rect = rects["curve_L"] if run["side"] > 0 else rects["curve_R"]
        p, (tx, tz) = verge_point(s0 - 95.0, -1.0)
        plant(p, (-tx, -tz), warn_rect, w=0.75, h=0.75, pole_h=2.6)
        if run["peak"] > 0.030:
            # chevron(s) on the OUTSIDE of the corner, facing the approach
            mid = (s0 + s1) / 2
            for ds in (-8.0, 0.0, 8.0):
                p, (tx, tz) = verge_point(mid + ds, -run["side"], 2.2)
                plant(p, (-tx, -tz), rects["chevron"], w=0.62, h=0.78, pole_h=1.9,
                      mirror_u=run["side"] < 0)  # atlas chevron points left
            # 100/50 brake boards on the right verge before the corner
            for dist, key in ((100.0, "board100"), (50.0, "board50")):
                p, (tx, tz) = verge_point(s0 - dist, -1.0)
                plant(p, (-tx, -tz), rects[key], w=0.85, h=0.45, pole_h=1.6)

    # --- stop signs from OSM nodes near the lap
    for lon, lat in scenery.get("stops", []):
        x, y, z = to_local(lon, lat)
        d, i = lap.nearest(x, z)
        if d > 40.0:
            continue
        p = lap.pts[i]
        a, b = lap.pts[max(0, i - 1)], lap.pts[min(len(lap.pts) - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]
        L = math.hypot(tx, tz) or 1e-6
        plant((x, y, z), (-tx / L, -tz / L), rects["stop"], w=0.75, h=0.75, pole_h=2.4)

    # --- street blades at named-road junctions with the lap
    n_blades = int(manifest["atlas"]["signs"].get("n_blades", 0))
    blade_i = 0
    used: list[tuple[float, float]] = []
    for road in scenery.get("roads", []):
        if not road.get("name") or n_blades == 0:
            continue
        pts = [to_local(lo, la) for lo, la in road["coords"]]
        for k in range(0, len(pts), 3):
            x, _, z = pts[k]
            d, i = lap.nearest(x, z)
            if d < 14.0:
                if any(math.hypot(x - ux, z - uz) < 90 for ux, uz in used):
                    break
                used.append((x, z))
                p = lap.pts[i]
                a, b = lap.pts[max(0, i - 1)], lap.pts[min(len(lap.pts) - 1, i + 1)]
                tx, tz = b[0] - a[0], b[2] - a[2]
                L = math.hypot(tx, tz) or 1e-6
                tx, tz = tx / L, tz / L
                nx, nz = -tz, tx
                off = lap.widths[i] / 2 + 1.4
                bx, bz = p[0] - nx * off, p[2] - nz * off
                if clearance is not None and not clearance.clear(bx, bz, 0.35):
                    break
                rect = rects[f"blade{blade_i % n_blades}"]
                pole = _post(bx, p[1], bz, 3.4)
                poles.append(pole)
                faces.append(_sign_face(bx, p[1] + 3.15, bz, 1.7, 0.42, (tx, tz), rect))
                faces.append(_sign_face(bx, p[1] + 2.75, bz, 1.7, 0.42, (nx, nz),
                                        rects[f"blade{(blade_i + 1) % n_blades}"]))
                blade_i += 2
                break
    return {"poles": poles, "faces": faces}


def build_traffic_signals(lap: Lap, scenery: dict, to_local,
                          clearance: "RoadClearance | None" = None) -> dict:
    """Mast-arm traffic signals at OSM signal nodes on the lap: pole + arm over the road + heads."""
    poles: list[Mesh] = []
    heads: list[Mesh] = []
    seen: list[tuple[float, float]] = []
    for lon, lat in scenery.get("signals", []):
        x, y, z = to_local(lon, lat)
        d, i = lap.nearest(x, z)
        if d > 26.0 or any(math.hypot(x - sx, z - sz) < 45 for sx, sz in seen):
            continue
        seen.append((x, z))
        p = lap.pts[i]
        a, b = lap.pts[max(0, i - 1)], lap.pts[min(len(lap.pts) - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]
        L = math.hypot(tx, tz) or 1e-6
        tx, tz = tx / L, tz / L
        nx, nz = -tz, tx                       # left normal
        w = lap.widths[i]
        bx, bz = p[0] - nx * (w / 2 + 1.2), p[2] - nz * (w / 2 + 1.2)  # right verge
        if clearance is not None and not clearance.clear(bx, bz, 0.3):
            continue
        poles.append(box(bx, p[1], bz, 0.28, 0.28, 6.2, uv_scale=6.2, top=False))
        # arm: segmented box reaching over the near lane
        arm_len = w * 0.55
        segs = 3
        for k in range(segs):
            t0 = k / segs
            ax = bx + nx * arm_len * (t0 + 0.5 / segs)
            az = bz + nz * arm_len * (t0 + 0.5 / segs)
            poles.append(box(ax, p[1] + 5.9 - 0.1 * k, az, 0.16, arm_len / segs + 0.02, 0.16,
                             ry=math.atan2(nx, nz), uv_scale=2.0))
        for t in (0.55, 0.95):
            hx, hz = bx + nx * arm_len * t, bz + nz * arm_len * t
            heads.append(box(hx, p[1] + 5.0, hz, 0.30, 0.22, 0.95, uv_scale=1.0))
    return {"poles": poles, "heads": heads}


def build_streetlights(lap: Lap, clearance: "RoadClearance | None" = None,
                       *, spacing: float = 48.0) -> dict:
    """Cobra-head lights down the right verge: tapered pole + mast arm + head (heads separate so
    the CSP light series lands one light per head island)."""
    poles: list[Mesh] = []
    heads: list[Mesh] = []
    s = spacing / 2
    while s < lap.total:
        p, (tx, tz), w = lap.sample(s)
        nx, nz = -tz, tx
        off = w / 2 + 1.8
        bx, bz = p[0] - nx * off, p[2] - nz * off      # right verge
        if clearance is not None and not clearance.clear(bx, bz, 0.3):
            s += spacing                               # junction mouth / connector — skip this one
            continue
        poles.append(box(bx, p[1], bz, 0.22, 0.22, 9.0, uv_scale=9.0, top=False))
        arm = 2.6
        ry = math.atan2(nx, nz)
        poles.append(box(bx + nx * arm * 0.5, p[1] + 8.8, bz + nz * arm * 0.5,
                         0.12, arm, 0.12, ry=ry, uv_scale=2.0))
        heads.append(box(bx + nx * arm, p[1] + 8.72, bz + nz * arm, 0.34, 0.85, 0.18,
                         ry=ry, uv_scale=1.0))
        s += spacing
    return {"poles": poles, "heads": heads}


def build_power(scenery: dict, to_local, ground_y, *, max_spans: int = 320) -> dict:
    """Wood distribution poles + crossarms + sagging conductor ribbons along OSM power lines,
    plus lattice-ish transmission towers at tower nodes."""
    woods: list[Mesh] = []
    wires: list[Mesh] = []
    towers: list[Mesh] = []
    spans = 0
    for line in scenery.get("power_lines", []):
        pts = [to_local(lo, la) for lo, la in line["coords"]]
        big = line.get("kind") == "line"
        ph = 16.0 if big else 11.0
        for k, (x, _, z) in enumerate(pts):
            y = ground_y(x, z)
            woods.append(box(x, y, z, 0.30, 0.30, ph, uv_scale=ph, top=False))
            # crossarm perpendicular to the run
            a = pts[max(0, k - 1)]
            b = pts[min(len(pts) - 1, k + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]
            L = math.hypot(tx, tz) or 1e-6
            ry = math.atan2(-tz / L, tx / L)
            woods.append(box(x, y + ph - 1.0, z, 0.14, 2.4, 0.14, ry=ry, uv_scale=1.0))
        for k in range(len(pts) - 1):
            if spans >= max_spans:
                break
            spans += 1
            (x0, _, z0), (x1, _, z1) = pts[k], pts[k + 1]
            y0 = ground_y(x0, z0) + ph - 1.05
            y1 = ground_y(x1, z1) + ph - 1.05
            a = pts[max(0, k - 1)]
            b = pts[min(len(pts) - 1, k + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]
            L = math.hypot(tx, tz) or 1e-6
            nx, nz = -tz / L, tx / L
            for woff in (-0.9, 0.0, 0.9):
                wires.append(_catenary((x0 + nx * woff, y0, z0 + nz * woff),
                                       (x1 + nx * woff, y1, z1 + nz * woff), sag=1.3))
    for tower in scenery.get("power_towers", []):
        if tower.get("kind") != "tower":
            continue
        lon, lat = tower["pt"]
        x, _, z = to_local(lon, lat)
        y = ground_y(x, z)
        towers.append(box(x, y, z, 3.4, 3.4, 6.0, uv_scale=3.0, top=False))
        towers.append(box(x, y + 6.0, z, 2.2, 2.2, 9.0, uv_scale=3.0, top=False))
        towers.append(box(x, y + 15.0, z, 1.2, 1.2, 7.0, uv_scale=3.0, top=False))
        towers.append(box(x, y + 17.5, z, 9.0, 0.7, 0.7, uv_scale=3.0))
    return {"wood": woods, "wires": wires, "towers": towers}


def _catenary(p0: Vertex, p1: Vertex, *, sag: float = 1.2, segs: int = 8, w: float = 0.05) -> Mesh:
    """A drooping wire as a thin vertical ribbon (double-sided)."""
    verts: list[Vertex] = []
    uvs = []
    tris = []
    for i in range(segs + 1):
        t = i / segs
        x = p0[0] + (p1[0] - p0[0]) * t
        z = p0[2] + (p1[2] - p0[2]) * t
        y = p0[1] + (p1[1] - p0[1]) * t - sag * 4 * t * (1 - t)
        verts += [(x, y - w / 2, z), (x, y + w / 2, z)]
        uvs += [(t, 0.0), (t, 1.0)]
    for i in range(segs):
        b = 2 * i
        tris += [(b, b + 2, b + 3), (b, b + 3, b + 1), (b, b + 3, b + 2), (b, b + 1, b + 3)]
    return {"vertices": verts, "uvs": uvs, "tris": tris}


def build_fences(lap: Lap, scenery: dict, to_local, ground_y, *, max_m: float = 14000.0) -> list[Mesh]:
    """Chain-link ribbons along OSM fence/wall ways near the lap (double-sided, alpha-tested)."""
    out: list[Mesh] = []
    budget = max_m
    for fence in scenery.get("fences", []):
        pts = [to_local(lo, la) for lo, la in fence["coords"]]
        if not pts:
            continue
        mx = sum(p[0] for p in pts) / len(pts)
        mz = sum(p[2] for p in pts) / len(pts)
        d, _ = lap.nearest(mx, mz, reach=400.0)
        if d > 320.0:
            continue
        h = 1.85 if fence.get("kind") == "fence" else 1.1
        verts: list[Vertex] = []
        uvs = []
        tris = []
        arc = 0.0
        for k, (x, _, z) in enumerate(pts):
            y = ground_y(x, z) - 0.15
            if k > 0:
                seg = math.hypot(x - pts[k - 1][0], z - pts[k - 1][2])
                arc += seg
                budget -= seg
            b = len(verts)
            verts += [(x, y, z), (x, y + h, z)]
            uvs += [(arc / 3.0, 0.0), (arc / 3.0, 1.0)]
            if k > 0:
                tris += [(b - 2, b, b + 1), (b - 2, b + 1, b - 1),
                         (b - 2, b + 1, b), (b - 2, b - 1, b + 1)]
        out.append({"vertices": verts, "uvs": uvs, "tris": tris})
        if budget <= 0:
            break
    return out


JERSEY_PROFILE = [(-0.30, 0.0), (-0.30, 0.08), (-0.09, 0.46), (-0.055, 0.81),
                  (0.055, 0.81), (0.09, 0.46), (0.30, 0.08), (0.30, 0.0)]


def build_walls(loop: list[Vertex], widths: list[float], runs: list[dict],
                clearance: "RoadClearance | None" = None,
                *, off: float = 1.7, pad: int = 5, lift: float = 0.3) -> list[Mesh]:
    """Jersey barriers on the outside of significant corners — swept profile, double-sided,
    one mesh per continuous stretch (named 1WALL_* by the caller → real collision).

    City-circuit correctness: every station of the sweep must clear EVERY road surface (the
    clearance index covers the loop and the connector), so at junctions and S-complexes the
    barrier follows the verge in separate segments instead of cutting across the tarmac."""
    from scripts.geometry.kerbs import _fine_stations
    out: list[Mesh] = []
    n = len(loop)

    def emit(seg: list) -> None:
        if len(seg) < 3:                        # too short to read as a barrier
            return
        verts: list[Vertex] = []
        uvs = []
        tris = []
        rows = []
        np_ = len(JERSEY_PROFILE)
        for bx, base, bz, nx, nz, arc in seg:
            row = len(verts)
            for pi, (po, ph) in enumerate(JERSEY_PROFILE):
                verts.append((bx + nx * po, base + ph, bz + nz * po))
                uvs.append((pi / (np_ - 1), arc / 2.0))
            rows.append(row)
        for r in range(len(rows) - 1):
            p0, p1 = rows[r], rows[r + 1]
            for k in range(np_ - 1):
                tris += [(p0 + k, p1 + k, p1 + k + 1), (p0 + k, p1 + k + 1, p0 + k + 1),
                         (p0 + k, p1 + k + 1, p1 + k), (p0 + k, p0 + k + 1, p1 + k + 1)]
        for rr, flipcap in ((rows[0], False), (rows[-1], True)):
            c = len(verts)
            for k in range(np_):
                verts.append(verts[rr + k])
                uvs.append((k / (np_ - 1), 0.0))
            for k in range(1, np_ - 1):
                tris.append((c, c + k + 1, c + k) if not flipcap else (c, c + k, c + k + 1))
        out.append({"vertices": verts, "uvs": uvs, "tris": tris})

    for run in runs:
        if run["peak"] < 0.013 or (run["i1"] - run["i0"]) < 7:
            continue
        side = -run["side"]                     # outside of the turn
        idx = list(range(max(0, run["i0"] - pad), min(n, run["i1"] + pad)))
        sts = _fine_stations([loop[k] for k in idx], 1.6)
        if len(sts) < 2:
            continue
        half = widths[idx[len(idx) // 2]] / 2.0
        seg: list = []
        for x, y, z, tx, tz, arc in sts:
            nx, nz = -tz * side, tx * side
            bx, bz = x + nx * (half + off), z + nz * (half + off)
            # the wall's own verge sits half+off out, so a margin below ``off`` keeps it while
            # rejecting any station that strays onto another stretch of road
            if clearance is not None and not clearance.clear(bx, bz, 0.35):
                emit(seg)
                seg = []
                continue
            seg.append((bx, y + lift - 0.25, bz, nx, nz, arc))
        emit(seg)
    return out


def build_tirestacks(loop: list[Vertex], widths: list[float], runs: list[dict],
                     seed: int, clearance: "RoadClearance | None" = None,
                     *, top_n: int = 3) -> list[Mesh]:
    """Tire-wall clusters in front of the barriers at the sharpest corners (verge only)."""
    rng = random.Random(seed * 7 + 5)
    out: list[Mesh] = []
    for run in sorted(runs, key=lambda r: -r["peak"])[:top_n]:
        side = -run["side"]
        mid = (run["i0"] + run["i1"]) // 2
        for k in range(-2, 3):
            i = min(len(loop) - 1, max(0, mid + k * 3))
            x, y, z = loop[i]
            a, b = loop[max(0, i - 1)], loop[min(len(loop) - 1, i + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]
            L = math.hypot(tx, tz) or 1e-6
            nx, nz = -tz / L * side, tx / L * side
            off = widths[i] / 2 + 1.05
            cx_, cz_ = x + nx * off, z + nz * off
            if clearance is not None and not clearance.clear(cx_, cz_, 0.3):
                continue
            out.append(cylinder(cx_ + rng.uniform(-0.1, 0.1), y + 0.05,
                                cz_ + rng.uniform(-0.1, 0.1), 0.55,
                                1.05, segs=10, cap=True, u_tiles=3.0))
    return out


def build_guardrails(lap: Lap, env_feats: list[dict], to_local) -> dict:
    """W-beam guardrail + posts where the lap crosses water (bridge edges)."""
    rails: list[Mesh] = []
    posts: list[Mesh] = []
    water_lines = [f for f in env_feats if f["cls"] == "water" and f["kind"] == "line"]
    crossings: list[float] = []
    loop_xz = [(p[0], p[2]) for p in lap.pts]
    for f in water_lines:
        wpts = [to_local(lo, la) for lo, la in f["coords"]]
        for k in range(len(wpts) - 1):
            q1 = (wpts[k][0], wpts[k][2])
            q2 = (wpts[k + 1][0], wpts[k + 1][2])
            step = 6
            for i in range(0, len(loop_xz) - step, step):
                hit = _seg_hit(loop_xz[i], loop_xz[i + step], q1, q2)
                if hit:
                    s = lap.arc[i]
                    if not any(abs(s - c) < 60 for c in crossings):
                        crossings.append(s)
    for s0 in crossings:
        for side in (1.0, -1.0):
            verts: list[Vertex] = []
            uvs = []
            tris = []
            steps = 16
            for k in range(steps + 1):
                s = s0 - 28.0 + k * 56.0 / steps
                p, (tx, tz), w = lap.sample(s)
                nx, nz = -tz * side, tx * side
                bx, bz = p[0] + nx * (w / 2 + 0.5), p[2] + nz * (w / 2 + 0.5)
                b = len(verts)
                verts += [(bx, p[1] + 0.45, bz), (bx, p[1] + 0.76, bz)]
                u = (s - s0) / 4.0
                uvs += [(u, 0.0), (u, 1.0)]
                if k > 0:
                    tris += [(b - 2, b, b + 1), (b - 2, b + 1, b - 1),
                             (b - 2, b + 1, b), (b - 2, b - 1, b + 1)]
                if k % 2 == 0:
                    posts.append(box(bx, p[1] - 0.2, bz, 0.12, 0.12, 0.68, uv_scale=1.0, top=False))
            rails.append({"vertices": verts, "uvs": uvs, "tris": tris})
    return {"rails": rails, "posts": posts}


def build_highways(env_feats: list[dict], to_local, ground_y, manifest: dict,
                   clearance: "RoadClearance | None" = None,
                   *, deck_h: float = 5.0, half_w: float = 8.0) -> dict:
    """Elevated freeway structure: deck + fascia skirts + jersey edges + piers + sign gantries."""
    decks: list[Mesh] = []
    skirts: list[Mesh] = []
    edges: list[Mesh] = []
    piers: list[Mesh] = []
    gantry_steel: list[Mesh] = []
    gantry_faces: list[Mesh] = []
    rects = manifest["atlas"]["ads"]
    pier_gap = 0.0
    gantry_gap = 350.0
    n_gantry = 0
    for f in [f for f in env_feats if f["cls"] == "highway"]:
        pts = [to_local(lo, la) for lo, la in f["coords"]]
        if len(pts) < 2:
            continue
        verts: list[Vertex] = []
        uvs = []
        tris = []
        sk_v: list[Vertex] = []
        sk_uv = []
        sk_t = []
        arc = 0.0
        prev = None
        for k, (x, _, z) in enumerate(pts):
            gy = ground_y(x, z)
            y = gy + deck_h
            a = pts[max(0, k - 1)]
            b = pts[min(len(pts) - 1, k + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]
            L = math.hypot(tx, tz) or 1e-6
            tx, tz = tx / L, tz / L
            nx, nz = -tz, tx
            if k > 0:
                seg = math.hypot(x - pts[k - 1][0], z - pts[k - 1][2])
                arc += seg
                pier_gap -= seg
                gantry_gap -= seg
            bd = len(verts)
            verts += [(x + nx * half_w, y, z + nz * half_w), (x - nx * half_w, y, z - nz * half_w)]
            uvs += [(half_w / 4, arc / 4), (-half_w / 4, arc / 4)]
            if k > 0:
                # double-sided: the deck is seen from below at track level, from above in renders
                tris += [(bd - 2, bd + 1, bd - 1), (bd - 2, bd, bd + 1),
                         (bd - 2, bd - 1, bd + 1), (bd - 2, bd + 1, bd)]
            # fascia skirts down both edges
            for sgn in (1.0, -1.0):
                ex, ez = x + nx * half_w * sgn, z + nz * half_w * sgn
                bs = len(sk_v)
                sk_v += [(ex, y - 1.5, ez), (ex, y, ez)]
                sk_uv += [(arc / 2, 0.0), (arc / 2, 0.75)]
                if k > 0:
                    sk_t += [(bs - 2, bs, bs + 1), (bs - 2, bs + 1, bs - 1),
                             (bs - 2, bs + 1, bs), (bs - 2, bs - 1, bs + 1)]
            # jersey edge barriers (simple vertical strips on the deck edges)
            for sgn in (1.0, -1.0):
                ex, ez = x + nx * (half_w - 0.4) * sgn, z + nz * (half_w - 0.4) * sgn
                bs = len(sk_v)
                sk_v += [(ex, y, ez), (ex, y + 0.85, ez)]
                sk_uv += [(arc / 2, 0.0), (arc / 2, 0.42)]
                if k > 0:
                    sk_t += [(bs - 2, bs, bs + 1), (bs - 2, bs + 1, bs - 1),
                             (bs - 2, bs + 1, bs), (bs - 2, bs - 1, bs + 1)]
            # piers — never on a drivable surface (the loop passes under these decks)
            if pier_gap <= 0 and deck_h > 2.5:
                pier_gap = 26.0
                if clearance is None or clearance.clear(x, z, 1.4):
                    piers.append(box(x, gy - 0.4, z, 1.7, 1.3, deck_h - 0.6,
                                     ry=math.atan2(tx, tz), uv_scale=3.0, top=False))
            # overhead sign gantry
            if gantry_gap <= 0 and len(pts) > 8 and n_gantry < 8:
                gantry_gap = 700.0
                gy_t = y + 5.6
                for sgn in (1.0, -1.0):
                    gantry_steel.append(box(x + nx * (half_w + 0.6) * sgn, y,
                                            z + nz * (half_w + 0.6) * sgn, 0.45, 0.45, 6.4,
                                            uv_scale=4.0, top=False))
                gantry_steel.append(box(x, gy_t, z, 0.5, (half_w + 0.6) * 2, 0.5,
                                        ry=math.atan2(nx, nz), uv_scale=4.0))
                rect = rects[f"gantry{n_gantry % 2}"]
                gantry_faces.append(_sign_face(x + tx * 0.3, gy_t - 1.3, z + tz * 0.3,
                                               12.0, 2.6, (tx, tz), rect))
                n_gantry += 1
            prev = (x, z)
        decks.append({"vertices": verts, "uvs": uvs, "tris": tris})
        skirts.append({"vertices": sk_v, "uvs": sk_uv, "tris": sk_t})
    return {"decks": decks, "skirts": skirts, "edges": edges, "piers": piers,
            "gantry_steel": gantry_steel, "gantry_faces": gantry_faces}


def build_tanks(scenery: dict, to_local, ground_y,
                clearance: "RoadClearance | None" = None) -> list[Mesh]:
    """Refinery/industrial storage tanks, silos, water towers from OSM."""
    out: list[Mesh] = []
    for tank in scenery.get("tanks", []):
        pts = [to_local(lo, la) for lo, la in tank["coords"]]
        cx = sum(p[0] for p in pts) / len(pts)
        cz = sum(p[2] for p in pts) / len(pts)
        if len(pts) >= 3:
            r = sum(math.hypot(p[0] - cx, p[2] - cz) for p in pts) / len(pts)
        else:
            r = 6.0
        if clearance is not None and not clearance.clear(cx, cz, r + 0.5):
            continue                            # obstruction audit: tank reaches the road
        kind = tank.get("kind", "storage_tank")
        h = tank.get("height_m") or 0.0
        y = ground_y(cx, cz)
        if kind in ("chimney", "flare"):
            out.append(cylinder(cx, y, cz, max(0.8, r * 0.15), h or 26.0, segs=10, cap=False))
        elif kind == "water_tower":
            out.append(cylinder(cx, y, cz, 1.2, 18.0, segs=8, cap=False))
            out.append(cylinder(cx, y + 18.0, cz, max(4.0, r), 7.0, segs=14, cap=True))
        else:
            r = max(3.0, min(r, 28.0))
            out.append(cylinder(cx, y, cz, r, h or (10.0 if r < 8 else 14.0),
                                segs=18 if r > 8 else 12, cap=True,
                                u_tiles=max(1.0, round(2 * math.pi * r / 8.0))))
    return out


def build_rail(scenery: dict, to_local, ground_y, lap: Lap) -> dict:
    """Railways: ballast ribbon + two steel rail strips per OSM way near the map."""
    beds: list[Mesh] = []
    rails: list[Mesh] = []
    for way in scenery.get("rail", []):
        pts = [to_local(lo, la) for lo, la in way["coords"]]
        if len(pts) < 2:
            continue
        bed_v: list[Vertex] = []
        bed_uv = []
        bed_t = []
        rail_v: list[Vertex] = []
        rail_uv = []
        rail_t = []
        arc = 0.0
        for k, (x, _, z) in enumerate(pts):
            y = ground_y(x, z) + 0.28
            a = pts[max(0, k - 1)]
            b = pts[min(len(pts) - 1, k + 1)]
            tx, tz = b[0] - a[0], b[2] - a[2]
            L = math.hypot(tx, tz) or 1e-6
            nx, nz = -tz / L, tx / L
            if k > 0:
                arc += math.hypot(x - pts[k - 1][0], z - pts[k - 1][2])
            bb = len(bed_v)
            bed_v += [(x + nx * 2.2, y, z + nz * 2.2), (x - nx * 2.2, y, z - nz * 2.2)]
            bed_uv += [(arc / 3, 0.0), (arc / 3, 1.0)]
            if k > 0:
                bed_t += [(bb - 2, bb + 1, bb - 1), (bb - 2, bb, bb + 1)]  # up-facing
            for gsign in (1.0, -1.0):
                rb = len(rail_v)
                gx, gz = x + nx * 0.72 * gsign, z + nz * 0.72 * gsign
                rail_v += [(gx + nx * 0.05, y + 0.12, gz + nz * 0.05),
                           (gx - nx * 0.05, y + 0.12, gz - nz * 0.05)]
                rail_uv += [(arc / 2, 0.0), (arc / 2, 1.0)]
                if k > 0:
                    rail_t += [(rb - 4, rb + 1, rb - 3), (rb - 4, rb, rb + 1)]  # up-facing
        beds.append({"vertices": bed_v, "uvs": bed_uv, "tris": bed_t})
        rails.append({"vertices": rail_v, "uvs": rail_uv, "tris": rail_t})
    return {"beds": beds, "rails": rails}


def build_crosswalks(lap: Lap, scenery: dict, to_local, *, lift: float = 0.014) -> list[Mesh]:
    """Continental crosswalk bars + stop bars at crossings/signals on the lap."""
    out: list[Mesh] = []
    done: list[tuple[float, float]] = []
    nodes = list(scenery.get("crossings", [])) + list(scenery.get("signals", []))
    for lon, lat in nodes:
        x, _, z = to_local(lon, lat)
        d, i = lap.nearest(x, z)
        if d > 16.0 or any(math.hypot(x - dx, z - dz) < 30 for dx, dz in done):
            continue
        done.append((x, z))
        p = lap.pts[i]
        a, b = lap.pts[max(0, i - 1)], lap.pts[min(len(lap.pts) - 1, i + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]
        L = math.hypot(tx, tz) or 1e-6
        tx, tz = tx / L, tz / L
        nx, nz = -tz, tx
        w = lap.widths[i] - 1.6
        y = p[1] + lift
        nbars = max(4, int(w / 1.0))
        for kb in range(nbars):
            u = (kb + 0.5) / nbars - 0.5
            cxb = p[0] + nx * u * w
            czb = p[2] + nz * u * w
            # corner order chosen so the face winds up (+Y) under the quad() convention
            out.append(quad((cxb - tx * 0.9 - nx * 0.3, y, czb - tz * 0.9 - nz * 0.3),
                            (cxb - tx * 0.9 + nx * 0.3, y, czb - tz * 0.9 + nz * 0.3),
                            (cxb + tx * 0.9 + nx * 0.3, y, czb + tz * 0.9 + nz * 0.3),
                            (cxb + tx * 0.9 - nx * 0.3, y, czb + tz * 0.9 - nz * 0.3)))
    return out


def build_billboards(lap: Lap, runs: list[dict], manifest: dict, seed: int,
                     clearance: "RoadClearance | None" = None, *, count: int = 4) -> dict:
    """Big roadside ad boards on the longest straights, angled toward oncoming traffic."""
    rects = manifest["atlas"]["ads"]
    rng = random.Random(seed * 7 + 9)
    # straights = gaps between corner runs
    gaps: list[tuple[float, float]] = []
    if runs:
        for a, b in zip(runs, runs[1:] + [runs[0]]):
            s0 = lap.arc[min(a["i1"], len(lap.arc) - 1)]
            s1 = lap.arc[b["i0"]]
            if s1 < s0:
                s1 += lap.total
            gaps.append((s1 - s0, s0))
    gaps.sort(reverse=True)
    steel: list[Mesh] = []
    faces: list[Mesh] = []
    for bi, (length, s0) in enumerate(gaps[:count]):
        s = s0 + length * 0.55
        p, (tx, tz), w = lap.sample(s)
        side = 1.0 if bi % 2 == 0 else -1.0
        nx, nz = -tz * side, tx * side
        bx, bz = p[0] + nx * (w / 2 + 7.0), p[2] + nz * (w / 2 + 7.0)
        if clearance is not None and not clearance.clear(bx, bz, 1.0):
            continue
        steel.append(box(bx, p[1], bz, 0.5, 0.5, 5.2, uv_scale=4.0, top=False))
        fx, fz = -tx, -tz  # face oncoming traffic straight-on, slight twist toward road
        ang = math.atan2(fx, fz) + side * 0.35
        fdir = (math.sin(ang), math.cos(ang))
        faces.append(_sign_face(bx, p[1] + 5.2 + 1.85, bz, 7.4, 3.7, fdir,
                                rects[f"ad{bi % 4}"]))
    return {"steel": steel, "faces": faces}


def build_start_gantry(dummies: dict, manifest: dict) -> dict:
    """Start/finish gantry spanning the road between the AC_TIME_0 timing dummies."""
    if "AC_TIME_0_L" not in dummies or "AC_TIME_0_R" not in dummies:
        return {"steel": [], "faces": []}
    lx, ly, lz = dummies["AC_TIME_0_L"]
    rx, ry, rz = dummies["AC_TIME_0_R"]
    cx, cz = (lx + rx) / 2, (lz + rz) / 2
    cy = min(ly, ry)
    dx, dz = rx - lx, rz - lz
    L = math.hypot(dx, dz) or 1e-6
    span = L + 3.0
    ry_ang = math.atan2(dx / L, dz / L)
    steel = [
        box(lx - dx / L * 1.5, cy, lz - dz / L * 1.5, 0.45, 0.45, 6.8, uv_scale=4.0, top=False),
        box(rx + dx / L * 1.5, cy, rz + dz / L * 1.5, 0.45, 0.45, 6.8, uv_scale=4.0, top=False),
        box(cx, cy + 6.8, cz, 0.5, span, 0.55, ry=ry_ang, uv_scale=4.0),
    ]
    fdir = (-dz / L, dx / L)  # perpendicular to the gate = along the road
    faces = [_sign_face(cx, cy + 6.0, cz, span - 1.0, 1.45, fdir,
                        manifest["atlas"]["ads"]["banner"]),
             _sign_face(cx, cy + 6.0, cz, span - 1.0, 1.45, (-fdir[0], -fdir[1]),
                        manifest["atlas"]["ads"]["banner"])]
    return {"steel": steel, "faces": faces}


def build_horizon(center: tuple[float, float], radius: float, *, height: float = 200.0,
                  base_y: float = -8.0, segs: int = 48) -> Mesh:
    """Inward-facing backdrop ring; U = azimuth/360 mapped to the panorama texture."""
    cx, cz = center
    verts: list[Vertex] = []
    uvs = []
    tris = []
    for i in range(segs + 1):
        a = 2 * math.pi * i / segs
        x = cx + radius * math.sin(a)          # azimuth from north (+Z), clockwise toward +X
        z = cz + radius * math.cos(a)
        verts += [(x, base_y, z), (x, base_y + height, z)]
        uvs += [(i / segs, 0.0), (i / segs, 1.0)]
    for i in range(segs):
        b = 2 * i
        tris += [(b, b + 3, b + 2), (b, b + 1, b + 3)]   # inward-facing (viewer is inside the ring)
    return {"vertices": verts, "uvs": uvs, "tris": tris}


# ------------------------------------------------------------------ vegetation

TREE_CELLS = {  # atlas cell -> (u0, v0, u1, v1) in OBJ-V (v=0 bottom); aspect = width/height
    "cottonwood": ((0.00, 0.5, 0.25, 1.0), 1.00),
    "ash":        ((0.25, 0.5, 0.50, 1.0), 0.92),
    "elm":        ((0.50, 0.5, 0.75, 1.0), 0.78),
    "juniper":    ((0.75, 0.5, 1.00, 1.0), 0.62),
    "bush":       ((0.00, 0.0, 0.25, 0.5), 1.45),
    "rabbitbrush": ((0.25, 0.0, 0.50, 0.5), 1.45),
    "dryshrub":   ((0.50, 0.0, 0.75, 0.5), 1.40),
    "reeds":      ((0.75, 0.0, 1.00, 0.5), 0.85),
}


def billboard(x: float, y: float, z: float, h: float, cell: str, rot: float) -> Mesh:
    """Two crossed cards, double-sided, mapped to an atlas cell."""
    (u0, v0, u1, v1), aspect = TREE_CELLS[cell]
    hw = h * aspect / 2
    verts: list[Vertex] = []
    uvs = []
    tris = []
    for k in range(2):
        a = rot + k * math.pi / 2
        dx, dz = math.cos(a) * hw, math.sin(a) * hw
        b = len(verts)
        verts += [(x - dx, y, z - dz), (x + dx, y, z + dz),
                  (x + dx, y + h, z + dz), (x - dx, y + h, z - dz)]
        uvs += [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        tris += [(b, b + 1, b + 2), (b, b + 2, b + 3),
                 (b, b + 2, b + 1), (b, b + 3, b + 2)]
    return {"vertices": verts, "uvs": uvs, "tris": tris}


def build_vegetation(lap: Lap, env_feats: list[dict], scenery: dict, to_local, ground_y,
                     seed: int, clearance: "RoadClearance | None" = None,
                     *, tree_cap: int = 2400, bush_cap: int = 900) -> dict:
    """Trees + understory: zone scatter, dense creek banks, OSM street trees. Avoids all roads."""
    rng = random.Random(seed * 7 + 3)
    trees: list[Mesh] = []
    bushes: list[Mesh] = []

    def road_clear(x: float, z: float, margin: float = 4.0) -> bool:
        if clearance is not None:
            return clearance.clear(x, z, margin)
        d, i = lap.nearest(x, z, reach=70.0)
        return d > (lap.widths[i] / 2 + margin if i >= 0 else margin)

    def plant_tree(x, z, kinds, hmin, hmax):
        if len(trees) >= tree_cap or not road_clear(x, z):
            return
        kind = rng.choices(list(kinds), weights=list(kinds.values()))[0]
        h = rng.uniform(hmin, hmax)
        trees.append(billboard(x, ground_y(x, z) - 0.3, z, h, kind, rng.uniform(0, math.pi)))

    def plant_bush(x, z, kinds, hmin=1.3, hmax=2.4):
        if len(bushes) >= bush_cap or not road_clear(x, z, 2.5):
            return
        kind = rng.choices(list(kinds), weights=list(kinds.values()))[0]
        bushes.append(billboard(x, ground_y(x, z) - 0.2, z, rng.uniform(hmin, hmax),
                                kind, rng.uniform(0, math.pi)))

    # --- OSM individual trees (street trees — exact positions)
    for lon, lat in scenery.get("trees", []):
        x, _, z = to_local(lon, lat)
        plant_tree(x, z, {"ash": 5, "elm": 4, "cottonwood": 2}, 8.0, 12.0)

    # --- creek banks: dense riparian cottonwoods + reeds along water lines
    for f in [f for f in env_feats if f["cls"] == "water" and f["kind"] == "line"]:
        pts = [to_local(lo, la) for lo, la in f["coords"]]
        arc = 0.0
        for k in range(1, len(pts)):
            x0, _, z0 = pts[k - 1]
            x1, _, z1 = pts[k]
            seg = math.hypot(x1 - x0, z1 - z0)
            steps = max(1, int(seg / 9.0))
            tx, tz = (x1 - x0) / (seg or 1e-6), (z1 - z0) / (seg or 1e-6)
            nx, nz = -tz, tx
            for st in range(steps):
                t = (st + rng.random() * 0.8) / steps
                bx, bz = x0 + (x1 - x0) * t, z0 + (z1 - z0) * t
                side = 1.0 if rng.random() < 0.5 else -1.0
                off = rng.uniform(5.0, 12.0) * side
                plant_tree(bx + nx * off, bz + nz * off,
                           {"cottonwood": 6, "ash": 2, "elm": 2}, 9.0, 15.0)
                if rng.random() < 0.55:
                    roff = rng.uniform(3.2, 4.6) * (1.0 if rng.random() < 0.5 else -1.0)
                    plant_bush(bx + nx * roff, bz + nz * roff, {"reeds": 8, "bush": 2}, 1.6, 2.4)

    # --- zone scatter
    for f in env_feats:
        if f["kind"] != "poly" or len(f["coords"]) < 3:
            continue
        cls = f["cls"]
        if cls == "green":
            step, kinds, hmin, hmax, bush_p = 27.0, {"cottonwood": 3, "ash": 4, "elm": 3, "juniper": 1}, 7.0, 12.0, 0.25
        elif cls == "wetland":
            step, kinds, hmin, hmax, bush_p = 19.0, {"cottonwood": 5, "ash": 2, "reeds": 0}, 8.0, 14.0, 0.5
        elif cls == "industrial":
            step, kinds, hmin, hmax, bush_p = 70.0, {"elm": 4, "dryshrub": 0, "ash": 2}, 6.0, 9.0, 0.6
        else:
            continue
        poly = [to_local(lo, la) for lo, la in f["coords"]]
        poly_xz = [(p[0], p[2]) for p in poly]
        xs = [p[0] for p in poly_xz]
        zs = [p[1] for p in poly_xz]
        gx = int((max(xs) - min(xs)) / step)
        gz = int((max(zs) - min(zs)) / step)
        for ix in range(gx + 1):
            for iz in range(gz + 1):
                x = min(xs) + ix * step + rng.uniform(-step * 0.4, step * 0.4) + (iz % 2) * step / 2
                z = min(zs) + iz * step + rng.uniform(-step * 0.4, step * 0.4)
                if not _pip(x, z, poly_xz):
                    continue
                plant_tree(x, z, kinds, hmin, hmax)
                if rng.random() < bush_p:
                    bx, bz = x + rng.uniform(-9, 9), z + rng.uniform(-9, 9)
                    if _pip(bx, bz, poly_xz):
                        plant_bush(bx, bz, {"bush": 4, "rabbitbrush": 4, "dryshrub": 3})

    # --- fence-line volunteers
    for fence in scenery.get("fences", [])[::2]:
        pts = [to_local(lo, la) for lo, la in fence["coords"]]
        for p in pts[:: max(1, len(pts) // 6)]:
            if rng.random() < 0.4:
                plant_bush(p[0] + rng.uniform(-1.5, 1.5), p[2] + rng.uniform(-1.5, 1.5),
                           {"dryshrub": 5, "rabbitbrush": 4, "bush": 2})
    return {"trees": trees, "bushes": bushes}


def _pip(x: float, z: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % n]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1 + 1e-12) + x1:
            inside = not inside
    return inside
