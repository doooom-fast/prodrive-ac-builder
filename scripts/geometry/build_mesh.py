"""Phase 4: build the track mesh (1ROAD ribbon + GRASS terrain + AC dummies) and write OBJ/MTL.

Consumes the projected local-metre data from Phases 1-3 and emits, in data/:
  track.obj + track.mtl (named groups 1ROAD / GRASS, for Blender → kn5 in Phase 5),
  dummies.json (AC_* placements), and track_render.svg (a 3/4 view, elevation exaggerated, to eyeball).
Pure stdlib.

Run:  python -m scripts.geometry.build_mesh projects/sand-creek-raceway
"""

from __future__ import annotations

import ast
import json
import math
import struct
import sys
from pathlib import Path

from scripts.geometry import dummies as dummies_mod
from scripts.geometry import kerbs, ribbon
from scripts.geometry.projection import _meters_per_degree

Vertex = tuple[float, float, float]
ROAD_LIFT_M = 0.1  # small crown above the graded terrain (a real road sits ~0.1 m proud, not floating)


def read_npy(path: Path) -> list[list[float]]:
    """Minimal float64 2D .npy reader (matches the writer in elevation/heightfield.py)."""
    with open(path, "rb") as f:
        assert f.read(6) == b"\x93NUMPY"
        f.read(2)
        hlen = struct.unpack("<H", f.read(2))[0]
        header = ast.literal_eval(f.read(hlen).decode())
        ny, nx = header["shape"]
        data = struct.unpack(f"<{ny * nx}d", f.read(8 * ny * nx))
    return [list(data[j * nx:(j + 1) * nx]) for j in range(ny)]


def project_grid(grid: list[list[float]], meta: dict, origin: tuple[float, float], elev0: float,
                 *, mirror_x: bool = False) -> list[list[Vertex]]:
    """Project the lat/lon terrain grid into the same local ENU frame as the centerline (mirroring the
    east axis too when ``mirror_x`` so the grass stays under the mirrored road)."""
    s, w, n, e = meta["bbox_swne"]
    nx, ny, sp = meta["nx"], meta["ny"], meta["spacing_m"]
    midlat = (s + n) / 2
    gy = sp / 111_000.0
    gx = sp / (111_000.0 * math.cos(math.radians(midlat)))
    lon0, lat0 = origin
    m_lon, m_lat = _meters_per_degree(lat0)
    sx = -1.0 if mirror_x else 1.0
    out = []
    for j in range(ny):
        lat = n - j * gy
        row = [(sx * ((w + i * gx) - lon0) * m_lon, grid[j][i] - elev0, (lat - lat0) * m_lat) for i in range(nx)]
        out.append(row)
    return out


def write_obj(path: Path, mtl_name: str, groups: list[tuple[str, str, dict]]) -> tuple[int, int]:
    """Write an OBJ with named objects/materials. groups: (object_name, material, mesh). Emits per-
    vertex UVs (``vt`` + ``f v/vt``) for any mesh carrying a parallel ``uvs`` list; v and vt use
    independent global offsets so textured and untextured groups can share one file."""
    lines = [f"mtllib {mtl_name}"]
    voff = vtoff = 0
    nv = nf = 0
    for name, mat, mesh in groups:
        lines.append(f"o {name}")
        lines.append(f"usemtl {mat}")
        for x, y, z in mesh["vertices"]:
            lines.append(f"v {x:.3f} {y:.3f} {z:.3f}")
        uvs = mesh.get("uvs")
        if uvs:
            for u, v in uvs:
                lines.append(f"vt {u:.4f} {v:.4f}")
        for a, b, c in mesh["tris"]:
            if uvs:
                lines.append(f"f {a+1+voff}/{a+1+vtoff} {b+1+voff}/{b+1+vtoff} {c+1+voff}/{c+1+vtoff}")
            else:
                lines.append(f"f {a + 1 + voff} {b + 1 + voff} {c + 1 + voff}")
        voff += len(mesh["vertices"])
        if uvs:
            vtoff += len(uvs)
        nv += len(mesh["vertices"])
        nf += len(mesh["tris"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return nv, nf


def write_mtl(path: Path) -> None:
    path.write_text(
        "newmtl road\nKd 0.20 0.20 0.23\nKa 0.05 0.05 0.05\n\n"
        "newmtl grass\nKd 0.26 0.44 0.20\nKa 0.05 0.08 0.04\n\n"
        "newmtl kerb\nKd 0.80 0.20 0.18\nKa 0.10 0.03 0.03\n",
        encoding="utf-8",
    )


def orient_up(mesh: dict) -> dict:
    """Flip any triangle whose geometric normal faces down so every face points +Y (up).

    AC track collision is **one-sided**: a ground/drivable surface whose faces point down lets the
    car drop straight through from above (and renders backface-culled). The ribbon/terrain/kerb
    generators wind their quads downward, so re-orient them up before export. Mutates and returns
    the mesh. Only safe for near-horizontal surfaces — don't apply to vertical geometry (barriers)."""
    V = mesh["vertices"]
    out = []
    for a, b, c in mesh["tris"]:
        ax, _, az = V[a]
        bx, _, bz = V[b]
        cx, _, cz = V[c]
        ny = (bz - az) * (cx - ax) - (bx - ax) * (cz - az)  # y-component of (b-a)×(c-a)
        out.append((a, c, b) if ny < 0.0 else (a, b, c))
    mesh["tris"] = out
    return mesh


def smooth_centerline(pts: list[Vertex], *, lam: float = 0.45, iterations: int = 4) -> list[Vertex]:
    """Light GLOBAL Laplacian smoothing to kill the GPS-level wobble (3-15° per-vertex jogs in the
    OSM/KML centerline) that makes the road EDGES ripple on curves. Each vertex is pulled only a
    fraction toward its neighbours' midpoint, so straights stay straight and the route is preserved —
    it just removes the high-frequency noise. Closed-loop aware; vertex count preserved."""
    closed = math.hypot(pts[0][0] - pts[-1][0], pts[0][2] - pts[-1][2]) < 1e-6
    P = [list(p) for p in (pts[:-1] if closed else pts)]
    m = len(P)
    for _ in range(iterations):
        new = [p[:] for p in P]
        for i in range(m):
            a, b = P[(i - 1) % m], P[(i + 1) % m]
            for c in (0, 1, 2):
                new[i][c] = P[i][c] + lam * ((a[c] + b[c]) / 2.0 - P[i][c])
        P = new
    out = [tuple(p) for p in P]
    if closed:
        out.append(out[0])
    return out


def round_sharp_corners(pts: list[Vertex], *, angle_thr: float = 28.0,
                        iterations: int = 7, window: int = 3) -> list[Vertex]:
    """Round only the SHARP kinks (a hard ~90° street corner has no zero-radius point — real ones have
    a curb radius). Localized corner-cutting near kinks > ``angle_thr``; straights and gentle bends are
    untouched, so the route shape is preserved. Fixes the ribbon self-pinching + the stub kerbs at
    corners. Closed-loop aware; vertex count (and the parallel widths) is preserved."""
    closed = math.hypot(pts[0][0] - pts[-1][0], pts[0][2] - pts[-1][2]) < 1e-6
    P = [list(p) for p in (pts[:-1] if closed else pts)]
    m = len(P)

    def kink(Q: list, i: int) -> float:
        a, b, c = Q[(i - 1) % m], Q[i], Q[(i + 1) % m]
        v1 = (b[0] - a[0], b[2] - a[2])
        v2 = (c[0] - b[0], c[2] - b[2])
        l1 = math.hypot(*v1) or 1e-9
        l2 = math.hypot(*v2) or 1e-9
        d = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        return math.degrees(math.acos(d))

    for _ in range(iterations):
        mark = [False] * m
        for i in range(m):
            if kink(P, i) > angle_thr:
                for w in range(-window, window + 1):
                    mark[(i + w) % m] = True
        new = [p[:] for p in P]
        for i in range(m):
            if mark[i]:
                a, b = P[(i - 1) % m], P[(i + 1) % m]
                for c in (0, 1, 2):
                    new[i][c] = 0.5 * P[i][c] + 0.25 * (a[c] + b[c])
        P = new
    out = [tuple(p) for p in P]
    if closed:
        out.append(out[0])
    return out


def build(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    local = json.loads((data / "centerline.local.json").read_text(encoding="utf-8"))
    centerline = round_sharp_corners(smooth_centerline([tuple(p) for p in local["points_xyz_m"]]))
    widths = local["widths_m"]
    origin = (local["origin"]["lon"], local["origin"]["lat"])
    elev0 = local["origin"]["elev_m"]

    # MIRROR_X: AC's kn5 convert renders the track reflected east<->west (a real right-hander reads as a
    # left, north preserved). Cancel it by mirroring the SOURCE X (east) here — so the road, the dummies
    # (placed below) and the facing (build_kn5) are all COMPUTED in the mirrored frame, never reflected
    # as matrices (that's what broke the spawn before). orient_up re-faces the drivable surfaces.
    mirror_x = bool(json.loads((project_dir / "track.config.json").read_text()).get("mirror_x", False))
    if mirror_x:
        centerline = [(-x, y, z) for (x, y, z) in centerline]

    grid = read_npy(data / "heightfield.npy")
    meta = json.loads((data / "heightfield.meta.json").read_text(encoding="utf-8"))
    grid, meta = ribbon.upsample_grid(grid, meta, 3)  # 40 m → ~13 m so grading hugs the road cleanly
    grid_xyz = project_grid(grid, meta, origin, elev0, mirror_x=mirror_x)
    ribbon.conform_terrain_to_road(grid_xyz, centerline, widths)  # grade terrain to the road (no dipping)

    # tile_m=15 matches the Poly Haven aerial_asphalt_01 (~30 m) real-world scale — kills the 4 m
    # tiling repeat that read as obvious stripes with the old close-up asphalt.
    road = ribbon.road_ribbon(centerline, widths, tile_m=15.0)
    road["vertices"] = [(x, y + ROAD_LIFT_M, z) for x, y, z in road["vertices"]]
    grass = ribbon.grass_terrain(grid_xyz)
    # Paved asphalt SHOULDER that ramps the lane edge down to the terrain (kills the floating-ribbon
    # hard edge AND gives a tarmac border instead of grass right at the edge). Lift baked in so its
    # inner lip meets the road edge exactly.
    shoulder = ribbon.road_shoulder(centerline, widths, lift=ROAD_LIFT_M)
    # Wide tarmac RUNOFF apron on the outside of corners (replaces grass run-off / the old walls).
    runoff = kerbs.corner_runoff(centerline, widths)
    runoff["vertices"] = [(x, y + 0.05, z) for x, y, z in runoff["vertices"]]  # clear the grass, below road
    kerb = kerbs.corner_kerbs(centerline, widths)
    kerb["vertices"] = [(x, y + ROAD_LIFT_M, z) for x, y, z in kerb["vertices"]]  # kerb lip at road-edge height
    marks = ribbon.road_markings(centerline, widths)
    marks["vertices"] = [(x, y + ROAD_LIFT_M + 0.012, z) for x, y, z in marks["vertices"]]  # just above road

    # AC track collision is one-sided — every ground/drivable surface must face up or the car
    # falls straight through. The ribbon/terrain/shoulder/runoff/kerb/markings generators wind their
    # quads downward, so re-orient them up. (No barriers — corners run off onto open tarmac.)
    for surface in (road, grass, shoulder, runoff, kerb, marks):
        orient_up(surface)

    dummies = dummies_mod.place_dummies(centerline, widths, n_sectors=3)

    # --- ORIENTATION CALIBRATION markers (TEMPORARY): pole CLUSTERS around the start so ONE in-game
    #     photo pins down exactly how AC transforms our axes. Counts encode the intended direction:
    #     1 pole = FORWARD (into the lap), 3 = RIGHT (the way the real Turn 1 goes), 2 = LEFT,
    #     5 = BACK (toward the chicane). 20 m tall, 60 m out from the start. Remove once oriented.
    x0, y0, z0 = centerline[0]
    tx, tz = centerline[1][0] - x0, centerline[1][2] - z0
    tl = math.hypot(tx, tz) or 1.0
    tx, tz = tx / tl, tz / tl                                    # forward unit vector
    dirs = [((tx, tz), 1), ((tz, -tx), 3), ((-tz, tx), 2), ((-tx, -tz), 5)]  # fwd, right, left, back
    cv, ct = [], []
    for (dx, dz), count in dirs:
        for k in range(count):
            off = 60.0 + k * 7.0
            cx, cz = x0 + dx * off, z0 + dz * off
            b = len(cv)
            W, H = 1.2, 20.0
            cv += [(cx - W, y0, cz), (cx + W, y0, cz), (cx + W, y0 + H, cz), (cx - W, y0 + H, cz),
                   (cx, y0, cz - W), (cx, y0, cz + W), (cx, y0 + H, cz + W), (cx, y0 + H, cz - W)]
            for o in (0, 4):
                ct += [(b + o, b + o + 1, b + o + 2), (b + o, b + o + 2, b + o + 3),
                       (b + o, b + o + 2, b + o + 1), (b + o, b + o + 3, b + o + 2)]
    calib = {"vertices": cv, "tris": ct}

    # 1GRASS (not GRASS): the leading digit makes the terrain a PHYSICAL surface keyed to
    # surfaces.ini GRASS, so you don't fall through the world off the racing line either.
    nv, nf = write_obj(data / "track.obj", "track.mtl",
                       [("1GRASS", "grass", grass), ("1ROAD_shoulder", "road", shoulder),
                        ("1RUNOFF_corners", "road", runoff), ("1ROAD_main", "road", road),
                        ("1KERB_corners", "kerb", kerb), ("MARKINGS", "kerb", marks),
                        ("CALIB", "kerb", calib)])
    write_mtl(data / "track.mtl")
    (data / "dummies.json").write_text(json.dumps(dummies, indent=1), encoding="utf-8")

    # road surface area (sum of triangle areas in the horizontal plane)
    rv = road["vertices"]
    area = 0.0
    for a, b, c in road["tris"]:
        (ax, _, az), (bx, _, bz), (cx, _, cz) = rv[a], rv[b], rv[c]
        area += abs((bx - ax) * (cz - az) - (cx - ax) * (bz - az)) / 2
    render_iso([("grass", (0.30, 0.47, 0.22), grass), ("shoulder", (0.40, 0.40, 0.43), shoulder),
                ("runoff", (0.46, 0.46, 0.49), runoff), ("road", (0.82, 0.83, 0.86), road),
                ("kerb", (0.88, 0.24, 0.20), kerb), ("marks", (0.95, 0.95, 0.92), marks)],
               dummies, data / "track_render.svg")

    return {"vertices": nv, "triangles": nf, "road_verts": len(rv), "kerb_verts": len(kerb["vertices"]),
            "shoulder_verts": len(shoulder["vertices"]), "runoff_verts": len(runoff["vertices"]),
            "grass_grid": f"{meta['nx']}x{meta['ny']}", "road_area_m2": round(area), "dummies": len(dummies)}


# --- pure-python 3/4-view renderer (orthographic, flat-shaded, painter's algorithm) ----

def render_iso(layers: list[tuple[str, tuple, dict]], dummies: dict, path: Path, *,
               az: float = -0.72, pitch: float = 0.60, yexag: float = 6.0, size: int = 1200,
               light: tuple = (-0.45, 0.82, -0.35)) -> None:
    ca, sa, cp, sp = math.cos(az), math.sin(az), math.cos(pitch), math.sin(pitch)
    ll = math.sqrt(sum(c * c for c in light))
    lx, ly, lz = (c / ll for c in light)

    def tf(v: Vertex) -> tuple[float, float, float]:
        x, y, z = v[0], v[1] * yexag, v[2]
        x1, z1 = x * ca + z * sa, -x * sa + z * ca
        return x1, y * cp - z1 * sp, y * sp + z1 * cp  # screenX, screenY(up), depth

    layer_faces = []  # per layer, in draw order: list of (depth, (p0,p1,p2), rgb)
    for _, base, mesh in layers:
        V = mesh["vertices"]
        fl = []
        for a, b, c in mesh["tris"]:
            v0, v1, v2 = V[a], V[b], V[c]
            ux, uy, uz = v1[0] - v0[0], (v1[1] - v0[1]) * yexag, v1[2] - v0[2]
            wx, wy, wz = v2[0] - v0[0], (v2[1] - v0[1]) * yexag, v2[2] - v0[2]
            nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            inten = 0.30 + 0.70 * max(0.0, abs((nx * lx + ny * ly + nz * lz) / nl))
            t0, t1, t2 = tf(v0), tf(v1), tf(v2)
            rgb = tuple(min(255, int(ch * inten * 255)) for ch in base)
            fl.append(((t0[2] + t1[2] + t2[2]) / 3, (t0, t1, t2), rgb))
        fl.sort(key=lambda f: f[0])  # far → near within the layer
        layer_faces.append(fl)

    allx = [p[0] for fl in layer_faces for _, tri, _ in fl for p in tri]
    ally = [p[1] for fl in layer_faces for _, tri, _ in fl for p in tri]
    minx, maxx, miny, maxy = min(allx), max(allx), min(ally), max(ally)
    pad = 24
    scale = (size - 2 * pad) / max(maxx - minx, maxy - miny)
    W, H = (maxx - minx) * scale + 2 * pad, (maxy - miny) * scale + 2 * pad

    def sc(p) -> tuple[float, float]:
        return round(pad + (p[0] - minx) * scale, 1), round(H - pad - (p[1] - miny) * scale, 1)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}"><rect width="100%" height="100%" fill="#0c1116"/>']
    for fl in layer_faces:  # grass first, then road painted on top so the ribbon always reads
        for _, tri, rgb in fl:
            pts = " ".join(f"{x},{y}" for x, y in map(sc, tri))
            out.append(f'<polygon points="{pts}" fill="rgb{rgb}"/>')
    # start/finish gate (AC_TIME_0_L → _R) drawn on top
    if "AC_TIME_0_L" in dummies and "AC_TIME_0_R" in dummies:
        x1, y1 = sc(tf(tuple(dummies["AC_TIME_0_L"])))
        x2, y2 = sc(tf(tuple(dummies["AC_TIME_0_R"])))
        out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#ff3b30" stroke-width="6"/>')
    out.append(f'<text x="{pad}" y="24" fill="#cdd6e0" font-size="14" font-family="monospace">'
               f'Sand Creek Raceway — 1ROAD + GRASS (elevation ×{yexag:g})</text>')
    out.append("</svg>")
    path.write_text("".join(out), encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.geometry.build_mesh <project-dir>")
    stats = build(sys.argv[1])
    print("wrote data/track.obj (+track.mtl), dummies.json, track_render.svg")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
