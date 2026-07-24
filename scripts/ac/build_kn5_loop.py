"""Loop front-end: prep a Blender-FIRST project's loop.blend for AC and save blender/<slug>.blend.

This is the San Diego (k10-san-diego) build philosophy, ported as an alternate front-end: the
project's ``loop.blend`` is the source of truth (Kevin shapes it in Blender), and this pass CONSUMES
it — renames the working meshes to AC surface conventions, gives them tiling UVs + PBR materials,
welds/holes-fills the grass, drops the AC_START/PIT/TIME/HOTLAP dummies computed from the real
centreline, packs textures, and saves ``blender/<slug>.blend``. ``export_kn5_addon`` then binds
shaders + exports the real kn5 (see scripts/build_loop.sh for the full pipeline).

THIS IS A DIFFERENT PROGRAM from scripts/ac/build_kn5.py (the OBJ-import pipeline). The two must
never be merged: this one edits an existing hand-authored scene; that one assembles a scene from
generated, audited OBJs. (docs: k10-colorado ENGINE-MIGRATION.md — "build_kn5.py is two programs".)

    blender --background --python scripts/ac/build_kn5_loop.py -- <project-dir>

The project dir is EXTERNAL to this repo (a consumer repo like k10-san-diego passes its own
project path); everything engine-side resolves against this file's location, never the project's.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# engine repo root — for `from scripts.ac import pbr` / `from scripts.geometry import dummies`
# regardless of where Blender was launched from or where the project dir lives.
_REPO = Path(__file__).resolve().parents[2]

# working mesh name (in loop.blend) -> AC-convention name. `1` prefix = physical surface keyed to
# surfaces.ini (ROAD/KERB/GRASS); 1WALL = physical collision barrier (guardrail).
AC_NAME = {
    "ROAD": "1ROAD_road",
    "KERB": "1KERB_kerb",
    # The street curb+sidewalk ships as the working mesh "CURB". Remap it to a 1KERB_ physical
    # surface so (a) it's collidable — the car can't fall through the road-edge/grass gap it
    # bridges — and (b) it gets the face-up flip below. Without this it stayed "CURB":
    # non-physical AND textureless=black.
    "CURB": "1KERB_sidewalk",
    "TERRAIN": "1GRASS",
    "GUARDRAIL": "1WALL_guard",
}
UV_TILE = 4.0  # metres per texture tile (top-down planar projection)

# AC/ksEditor hard per-mesh vertex cap (16-bit indices). Meshes are split under SPLIT_CAP; anything
# STILL over VERT_CAP after split+weld is FATAL — AC silently drops over-cap meshes, and a dropped
# PHYSICAL mesh means the car falls through (the invisible-forest / fall-through bug class).
VERT_CAP = 65535
SPLIT_CAP = 60000

# freeway groups whose winding must not matter: after the loop's local->Blender reflection their
# faces would point inward, so double-side them (append reversed faces) — a barrier/structure must
# render AND collide from both sides. Drivable surfaces are handled by the face-up flip pass.
DOUBLE_SIDE = ("1WALL", "HWYSTRUCT")

# --- terrain contact conform (the CO road-grounding pattern, loop-path edition) -------------------
# The hand-authored TERRAIN follows the DEM; the hand-shaped ROAD does not follow it back — on the
# western hills the deck ended up 1.8–6.7 m over the grass DIRECTLY beneath it (203+ red samples on
# the kn5 ground gate). Construction pins the world to the road: under the pavement footprint the
# terrain is PINNED to deck−GROUND_CLEAR (up or down), a FEATHER band blends back to natural ground,
# and the corridor is SUBDIVIDED first so coarse terrain triangles can hug the deck instead of
# chording (the adaptive-fine-grid move). Declared bridge spans (the real I-8 crossings) are spared:
# there the pin may only push DOWN — a bridge keeps its trench.
GROUND_CLEAR = 0.02        # m below the deck (the ground gate's ceiling is 0.05)
BAND_M = 3.0               # full-contact shelf past the pavement edge (CO grade_embankment's band)
FEATHER_M = 6.0            # smoothstep blend band beyond the shelf
CORRIDOR_EDGE_M = 4.5      # subdivide terrain edges near the road down to about this length
LAYER_WIN = 30.0           # deck sampling window (no stacked loop legs, but stay safe)
BRIDGE_MATCH_M = 14.0      # centerline pt within this of an OSM bridge way = on the span
BRIDGE_PAD_M = 8.0         # widen each detected span a touch onto the abutments


def _mpd(lat0):
    phi = math.radians(lat0)
    return (111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi) + 0.118 * math.cos(5 * phi),
            111132.954 - 559.822 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi))


def detect_bridge_spans(pts_xyz, origin_lonlat, bridge_ways, *, mirror_x=False,
                        match_m=BRIDGE_MATCH_M, pad_m=BRIDGE_PAD_M):
    """Station ranges [(a_m, b_m), ...] where the loop rides an OSM-declared bridge (its own deck —
    motorway/motorway_link ways are excluded so a freeway bridge crossing OVER the loop can't mark a
    phantom span on the road below). Pure function (no bpy) so it is unit-testable.

    pts_xyz: local (E, up, N) centerline; bridge_ways: [{'hw': ..., 'geom': [[lon, lat], ...]}, ...]."""
    lon0, lat0 = origin_lonlat
    m_lon, m_lat = _mpd(lat0)
    sx = -1.0 if mirror_x else 1.0
    segs = []
    for w in bridge_ways or []:
        if (w.get("hw") or "") in ("motorway", "motorway_link"):
            continue                      # the freeway's own bridges, not the loop's deck
        g = [(sx * (lon - lon0) * m_lon, (lat - lat0) * m_lat) for lon, lat in w.get("geom", [])]
        segs += [(g[i][0], g[i][1], g[i + 1][0], g[i + 1][1]) for i in range(len(g) - 1)]
    if not segs:
        return []

    def near_bridge(x, z):
        for ax, az, bx, bz in segs:
            dx, dz = bx - ax, bz - az
            L2 = dx * dx + dz * dz
            t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / L2))
            px, pz = ax + t * dx, az + t * dz
            if (x - px) ** 2 + (z - pz) ** 2 <= match_m * match_m:
                return True
        return False

    spans = []
    st = 0.0
    open_a = None
    prev = pts_xyz[0]
    for i, p in enumerate(pts_xyz):
        if i:
            st += math.hypot(p[0] - prev[0], p[2] - prev[2])
            prev = p
        if near_bridge(p[0], p[2]):
            if open_a is None:
                open_a = st
            open_b = st
        elif open_a is not None:
            spans.append((max(0.0, open_a - pad_m), open_b + pad_m))
            open_a = None
    if open_a is not None:
        spans.append((max(0.0, open_a - pad_m), open_b + pad_m))
    return spans


def declare_bridge_spans(proj: Path) -> list[tuple[float, float]]:
    """Detect the loop's real bridge spans and DECLARE them the way every other project does — write
    data/bridge.spans.auto.json + data/finished_centerline.json so the kn5 ground gate applies its
    standard declared-span exemption (a deck over the I-8 trench is SUPPOSED to ride high over the
    grass; that is not a float). finished_centerline is written in the KN5 frame (x, y, -z of the
    local frame): the Blender-first path has no OBJ stage, so the shipped-binary frame IS the
    reference frame the gate samples in. Returns the spans (local stations, metres)."""
    local = json.loads((proj / "data" / "centerline.local.json").read_text())
    pts = [tuple(p) for p in local["points_xyz_m"]]
    widths = local.get("widths_m") or [7.0] * len(pts)
    cfg = json.loads((proj / "track.config.json").read_text())
    bridges_p = proj / "data" / "bridges.cache.json"
    ways = json.loads(bridges_p.read_text()) if bridges_p.exists() else []
    o = local.get("origin") or {}
    spans = []
    if ways and "lon" in o:
        spans = detect_bridge_spans(pts, (o["lon"], o["lat"]), ways,
                                    mirror_x=bool(cfg.get("mirror_x", False)))
    (proj / "data" / "bridge.spans.auto.json").write_text(
        json.dumps([[round(a, 1), round(b, 1)] for a, b in spans]), encoding="utf-8")
    (proj / "data" / "finished_centerline.json").write_text(json.dumps({
        "points_xyz_m": [[round(x, 3), round(y, 3), round(-z, 3)] for x, y, z in pts],
        "widths_m": widths}), encoding="utf-8")
    print(f"[build_kn5_loop] declared {len(spans)} bridge span(s): "
          f"{[(round(a), round(b)) for a, b in spans]}")
    return spans


def _project_dir(argv):
    if "--" not in argv:
        raise SystemExit("usage: blender --background --python build_kn5_loop.py -- <project-dir>")
    rest = argv[argv.index("--") + 1:]
    if not rest:
        raise SystemExit("missing <project-dir>")
    return Path(rest[0]).resolve()


def assert_under_cap(name: str, nverts: int) -> None:
    """Loop-path over-cap guard (the OBJ program's guard lives in build_kn5.py step 2b; this path
    needs its own). FATAL, not a warning: AC silently drops over-cap meshes from render AND
    collision, so a warned-and-shipped over-cap 1ROAD/1GRASS is a guaranteed fall-through."""
    if nverts > VERT_CAP:
        raise SystemExit(f"[build_kn5_loop] FATAL: '{name}' has {nverts} positions (> {VERT_CAP}) "
                         f"even after the split pass — AC silently drops over-cap meshes. "
                         f"Raise the split factor or slim the source mesh. Refusing to export.")


def _split_large(ob, cap=SPLIT_CAP):
    """Split a mesh over AC's 65,535-vertex cap into UNIQUELY-named spatial tiles (base_0, base_1,
    ...). The exporter otherwise auto-splits into DUPLICATE-named meshes, and AC drops dup-named
    PHYSICAL meshes from collision -> the car falls through (a 46 km freeway terrain is ~268k
    verts). Partitions faces into bands along the longest axis; pbr/surfaces still key off the
    shared name prefix (1GRASS_0 -> GRASS)."""
    import bpy

    me = ob.data
    if len(me.vertices) <= cap:
        return
    K = len(me.vertices) // cap + 1
    co = [(v.co.x, v.co.y, v.co.z) for v in me.vertices]
    ax = 0 if (max(c[0] for c in co) - min(c[0] for c in co)) >= \
             (max(c[1] for c in co) - min(c[1] for c in co)) else 1
    lo = min(c[ax] for c in co); span = (max(c[ax] for c in co) - lo) or 1.0
    bands = [[] for _ in range(K)]
    for p in me.polygons:
        bands[min(K - 1, int((p.center[ax] - lo) / span * K))].append(p)
    base = ob.name
    mat = me.materials[0] if me.materials else None
    # carry authored per-vertex UVs across the split (palm cards etc. are single UV per vertex) —
    # without this the tiles have NO UVs and an alpha-cutout texture samples (0,0) and vanishes.
    vert_uv = None
    if me.uv_layers.active:
        uvl = me.uv_layers.active
        vert_uv = [(0.0, 0.0)] * len(me.vertices)
        for loop in me.loops:
            vert_uv[loop.vertex_index] = tuple(uvl.data[loop.index].uv)
    for k, polys in enumerate(bands):
        if not polys:
            continue
        used, nv, nf, orig = {}, [], [], []
        for poly in polys:
            idx = []
            for vi in poly.vertices:
                if vi not in used:
                    used[vi] = len(nv); nv.append(co[vi]); orig.append(vi)
                idx.append(used[vi])
            nf.append(idx)
        nm = bpy.data.meshes.new(f"{base}_{k}")
        nm.from_pydata(nv, [], nf); nm.update()
        if vert_uv is not None:
            nuv = nm.uv_layers.new(name="UVMap")
            for loop in nm.loops:
                nuv.data[loop.index].uv = vert_uv[orig[loop.vertex_index]]
        if mat:
            nm.materials.append(mat)
        bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"{base}_{k}", nm))
    print(f"[build_kn5_loop] split {base} ({len(me.vertices)} verts) -> {K} tiles under {cap}")
    bpy.data.objects.remove(ob, do_unlink=True)


def planar_uv(me):
    """Top-down planar UVs (u=x/tile, v=y/tile) — tiles asphalt/grass/kerb consistently at world
    scale."""
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (co.x / UV_TILE, co.y / UV_TILE)


def _add_obj_meshes(obj_path):
    """Import a merged OBJ (e.g. a freeway network already translated to the loop frame) using the
    SAME local->Blender remap as the loop authoring — (x,y,z)->(x,z,y) with reversed winding — so
    it lands in the loop's frame and the existing rename/flip/material pass handles it. Keeps AC
    group names + authored UVs."""
    import bpy

    verts = []; uvs = []; groups = []; cur = None
    for ln in obj_path.read_text().splitlines():
        s = ln.split()
        if not s:
            continue
        if s[0] == "v":
            verts.append((float(s[1]), float(s[2]), float(s[3])))
        elif s[0] == "vt":
            uvs.append((float(s[1]), float(s[2])))
        elif s[0] == "o":
            cur = (ln[2:].strip(), []); groups.append(cur)
        elif s[0] == "f" and cur is not None:
            face = []
            for tok in s[1:]:
                p = tok.split("/")
                face.append((int(p[0]) - 1, int(p[1]) - 1 if len(p) > 1 and p[1] else None))
            cur[1].append(face)
    n = 0
    for name, faces in groups:
        if not faces:
            continue
        has_uv = all(t is not None for fc in faces for _, t in fc)
        idx = {}; bverts = []; buvs = []; bfaces = []
        for fc in faces:
            bf = []
            for vi, ti in fc:
                if vi not in idx:
                    idx[vi] = len(bverts)
                    x, y, z = verts[vi]; bverts.append((x, z, y))     # local (E,up,N) -> Blender (E,N,up)
                    buvs.append(uvs[ti] if (has_uv and ti is not None) else (0.0, 0.0))
                bf.append(idx[vi])
            bfaces.append(tuple(reversed(bf)))                        # reverse winding (cancels the reflection)
        if name.upper().startswith(DOUBLE_SIDE):
            bfaces += [tuple(reversed(f)) for f in bfaces]            # render + collide from both sides
        me = bpy.data.meshes.new(name); me.from_pydata(bverts, [], bfaces); me.validate(); me.update()
        if has_uv:
            uvl = me.uv_layers.new(name="UVMap")
            for loop in me.loops:
                uvl.data[loop.index].uv = buvs[loop.vertex_index]
        bpy.context.scene.collection.objects.link(bpy.data.objects.new(name, me))
        n += 1
    print(f"[build_kn5_loop] merged {n} groups ({len(verts)} verts) from {obj_path.name}")
    return n


def _conform_and_reseat(proj: Path, spans):
    """Terrain contact conform for the Blender-first loop + prop re-seat, run INSIDE the open scene
    (after the AC renames, before the split pass). Three moves, all engine-owned so every future
    rebuild stays fixed (no hand surgery baked into loop.blend):

      1. SUBDIVIDE the terrain corridor: coarse DEM triangles cannot hug a hand-shaped deck — edges
         near the road are split to ~CORRIDOR_EDGE_M so the pin has vertices to work with
         (the adaptive-fine-grid move).
      2. PIN under the footprint: every 1GRASS vert under 1ROAD pavement is SET to deck−GROUND_CLEAR
         (up or down — contact, not a clamp), with a smoothstep FEATHER band blending back to natural
         ground past the edge. Under a DECLARED bridge span the pin may only push DOWN: the I-8
         trench stays a trench and the deck keeps riding it.
      3. RE-SEAT props on the moved ground: trees are seated absolutely (their floats predate this
         pass); palms/scrub/buildings/lights ride the terrain DELTA so today's good seats stay good.
    """
    import bpy
    from mathutils import kdtree
    from mathutils.bvhtree import BVHTree

    def _world_tris(name_pred):
        tris = []
        for ob in bpy.data.objects:
            if ob.type != "MESH" or not name_pred(ob.name.upper()):
                continue
            mw = ob.matrix_world
            me = ob.data
            vs = [mw @ v.co for v in me.vertices]
            for p in me.polygons:
                idx = list(p.vertices)
                for k in range(1, len(idx) - 1):
                    tris.append(((vs[idx[0]].x, vs[idx[0]].y, vs[idx[0]].z),
                                 (vs[idx[k]].x, vs[idx[k]].y, vs[idx[k]].z),
                                 (vs[idx[k + 1]].x, vs[idx[k + 1]].y, vs[idx[k + 1]].z)))
        return tris

    def _bvh(tris):
        return BVHTree.FromPolygons([v for t in tris for v in t],
                                    [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]) if tris else None

    def _surf_z(bvh, x, y, zref=None, win=LAYER_WIN):
        """Highest surface z at (x, y) via a downward ray from far above (Blender z = up)."""
        if bvh is None:
            return None
        hit = bvh.ray_cast((x, y, 4000.0), (0.0, 0.0, -1.0))
        if hit[0] is None:
            return None
        z = hit[0].z
        if zref is not None and abs(z - zref) > win:
            return None
        return z

    # 0. BURY-CULL: drivable faces (road/kerb) sandwiched >=0.3 m UNDER other pavement are junction
    #    apron slop that slid beneath the main deck when the junctions were shaped — dead geometry
    #    no wheel can reach. Left in, they poison every "lowest drivable sheet" lens: the poke gate
    #    reads contact-pinned grass as floating grass ABOVE the buried sliver, and clamping the
    #    grass down to the sliver instead re-opens metre-deep holes under the driven road. Cull the
    #    fully-buried faces (all verts covered) before anything measures against them.
    import bmesh
    _pre_bvh = _bvh(_world_tris(lambda n: n.startswith(("1ROAD", "1KERB")) and not n.endswith("_FW")))
    n_cull = 0
    if _pre_bvh is not None:
        for ob in [o for o in bpy.data.objects if o.type == "MESH"
                   and o.name.upper().startswith(("1ROAD", "1KERB"))
                   and not o.name.upper().endswith("_FW")]:
            me = ob.data
            bm = bmesh.new(); bm.from_mesh(me)
            drop = []
            for f in bm.faces:
                buried = True
                for v in f.verts:
                    hit = _pre_bvh.ray_cast((v.co.x, v.co.y, v.co.z + 0.3), (0.0, 0.0, 1.0), 20.0)
                    if hit[0] is None:
                        buried = False
                        break
                if buried:
                    drop.append(f)
            if drop:
                n_cull += len(drop)
                bmesh.ops.delete(bm, geom=drop, context="FACES")
                bm.to_mesh(me); me.update()
            bm.free()
    if n_cull:
        print(f"[build_kn5_loop] bury-cull: {n_cull} drivable faces removed from under other pavement")

    road_tris = _world_tris(lambda n: n.startswith("1ROAD"))
    road_bvh = _bvh(road_tris)
    if road_bvh is None:
        print("[build_kn5_loop] conform skipped: no 1ROAD mesh")
        return
    # drivable = road + kerb/sidewalk: the anti-poke pass below must use the same surface set the
    # verify poke lens measures against (grass over a LOW sidewalk apron is a poke too).
    driv_bvh = _bvh(_world_tris(lambda n: n.startswith(("1ROAD", "1KERB"))))

    # HORIZONTAL road-vert KD-tree for the feather + subdivision predicate. Distance must be 2D: on
    # a bench cut the ground beside the road is legitimately metres LOW, so a 3D nearest-distance
    # reads 6+ m and never feathers exactly the band the contact pin exists for (the CO lesson —
    # "real ground under the outer half of a bench-cut road is legitimately metres low").
    _rverts = sorted({(round(v[0], 4), round(v[1], 4), round(v[2], 4)) for t in road_tris for v in t})
    road_kd = kdtree.KDTree(len(_rverts))
    for _i, (_x, _y, _z) in enumerate(_rverts):
        road_kd.insert((_x, _y, 0.0), _i)
    road_kd.balance()

    def _near2d(x, y):
        co, idx, d = road_kd.find((x, y, 0.0))
        return (d, _rverts[idx][2]) if co is not None else (None, None)

    def _lowest_surf(bvh, x, y, zref, win=20.0):
        """LOWEST drivable surface at (x, y) within ±win of zref — multi-hit downward ray walk
        (the verify poke lens takes the lowest sheet; on a crowned/sloped section the highest one
        is the wrong reference)."""
        z0 = zref + win
        best = None
        for _ in range(6):
            hit = bvh.ray_cast((x, y, z0), (0.0, 0.0, -1.0), z0 - (zref - win))
            if hit[0] is None:
                break
            best = hit[0].z
            z0 = hit[0].z - 0.02
        return best

    # span mask: centerline stations inside a declared span -> XY discs (deck may only push DOWN)
    span_pts = []
    try:
        local = json.loads((proj / "data" / "centerline.local.json").read_text())
        pts = local["points_xyz_m"]
        wid = local.get("widths_m") or [7.0] * len(pts)
        st = 0.0
        for i, p in enumerate(pts):
            if i:
                st += math.hypot(p[0] - pts[i - 1][0], p[2] - pts[i - 1][2])
            if any(a <= st <= b for a, b in spans):
                span_pts.append((p[0], p[2], wid[i] / 2.0 + 12.0))   # Blender XY = (E, N)
    except Exception as e:  # noqa: BLE001
        print(f"[build_kn5_loop] span mask skipped: {e}")

    def on_span(x, y):
        return any((x - sx) ** 2 + (y - sy) ** 2 <= r * r for sx, sy, r in span_pts)

    terrain = [ob for ob in bpy.data.objects
               if ob.type == "MESH" and ob.name.upper().startswith("1GRASS")]
    old_grass_bvh = _bvh(_world_tris(lambda n: n.startswith("1GRASS")))   # pre-pin ground, for deltas

    import bmesh
    n_pin = n_feather = n_sub = 0
    for ob in terrain:
        me = ob.data
        bm = bmesh.new(); bm.from_mesh(me)
        # 1. corridor subdivision (repeat: each round halves qualifying edges)
        for _round in range(4):
            todo = []
            for e in bm.edges:
                if e.calc_length() <= CORRIDOR_EDGE_M:
                    continue
                mx = (e.verts[0].co + e.verts[1].co) / 2
                d2d, _rz = _near2d(mx.x, mx.y)
                if d2d is not None and d2d <= FEATHER_M + 10.0:
                    todo.append(e)
            if not todo:
                break
            bmesh.ops.subdivide_edges(bm, edges=todo, cuts=1)
            n_sub += len(todo)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        # 2. pin + feather (all distances HORIZONTAL — bench-cut ground is legitimately metres low)
        for v in bm.verts:
            x, y, z = v.co.x, v.co.y, v.co.z
            d2d, rz = _near2d(x, y)
            if d2d is None or d2d > FEATHER_M + 10.0:
                continue
            deck = _surf_z(road_bvh, x, y, zref=z)
            if deck is not None:                       # under the pavement footprint
                tgt = deck - GROUND_CLEAR
                if on_span(x, y):
                    if z > tgt:
                        v.co.z = tgt; n_pin += 1       # bridge span: contact may only push DOWN
                else:
                    v.co.z = tgt; n_pin += 1
            else:                                      # contact band + feather past the edge
                # full-contact BAND (CO's "gentle shelf"): every triangle covering pavement has all
                # verts within ~2.6 m of the edge, so holding the first 3 m at contact height makes
                # the surface under the deck edge gate-proof; then smoothstep back to natural.
                if d2d <= BAND_M:
                    w = 1.0
                elif d2d < BAND_M + FEATHER_M:
                    w = 1.0 - (d2d - BAND_M) / FEATHER_M
                    w = w * w * (3 - 2 * w)
                else:
                    continue
                # target = deck at the CLOSEST FOOTPRINT POINT (BVH), not the nearest road VERT's
                # height — on a 7% grade the vert-snap target was ±0.3 off between stations and
                # printed that error into the contact band (the 0.05–0.35 residual tail).
                near3 = road_bvh.find_nearest((x, y, z))
                tgt = (near3[0].z if near3[0] is not None else rz) - GROUND_CLEAR
                nz = tgt * w + z * (1.0 - w)
                if on_span(x, y) and nz > z:
                    continue
                v.co.z = nz; n_feather += 1
        # 2c. ANTI-POKE vs the LOWEST drivable sheet (road + kerb): the pin/feather reference the
        # nearest/highest deck — on crowned or sloping sections, and over the sidewalk's outer
        # apron, that left grass 0.15–1.2 m over the LOWER surface the verify lens measures
        # against (217 pokes). One-sided: only pushes DOWN, so spans/trenches are untouched.
        # (Blanket clamp is safe now that the bury-cull removed the sandwiched apron slivers.)
        n_anti = 0
        for v in bm.verts:
            low = _lowest_surf(driv_bvh, v.co.x, v.co.y, v.co.z)
            if low is not None and v.co.z > low - GROUND_CLEAR:
                v.co.z = low - GROUND_CLEAR; n_anti += 1
        if n_anti:
            print(f"[build_kn5_loop] anti-poke: {n_anti} verts clamped under the lowest drivable sheet")
        bm.to_mesh(me); bm.free(); me.update()
    print(f"[build_kn5_loop] terrain conform: {n_sub} corridor edges split, "
          f"{n_pin} verts pinned to deck-{GROUND_CLEAR}, {n_feather} feathered")

    # 3. prop re-seat on the moved ground
    ground_bvh = _bvh(_world_tris(lambda n: n.startswith(("1GRASS", "1ROAD", "1KERB"))))

    def _islands(ob):
        """Connected vert islands of a mesh object (index lists), via union-find over edges."""
        me = ob.data
        parent = list(range(len(me.vertices)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]; a = parent[a]
            return a
        for e in me.edges:
            a, b = find(e.vertices[0]), find(e.vertices[1])
            if a != b:
                parent[a] = b
        groups: dict[int, list[int]] = {}
        for i in range(len(me.vertices)):
            groups.setdefault(find(i), []).append(i)
        return list(groups.values())

    def _shift(ob, isl, dz):
        me = ob.data
        for i in isl:
            me.vertices[i].co.z += dz

    trunk_dz = []                                    # (x, y, dz) for canopy matching
    n_trees = n_rel = 0
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.name.upper().startswith("TREETRUNK"):
            continue
        me = ob.data
        for isl in _islands(ob):
            fi = min(isl, key=lambda i: me.vertices[i].co.z)
            f = ob.matrix_world @ me.vertices[fi].co
            g = _surf_z(ground_bvh, f.x, f.y, zref=None)
            if g is None:
                continue
            dz = g - f.z
            cx = sum(me.vertices[i].co.x for i in isl) / len(isl)
            cy = sum(me.vertices[i].co.y for i in isl) / len(isl)
            if abs(dz) > 0.03:
                _shift(ob, isl, dz); n_trees += 1
            trunk_dz.append((cx, cy, dz if abs(dz) > 0.03 else 0.0))
        me.update()
    for ob in bpy.data.objects:                      # canopies follow their trunk
        if ob.type != "MESH" or not ob.name.upper().startswith("TREECANOPY"):
            continue
        me = ob.data
        for isl in _islands(ob):
            cx = sum(me.vertices[i].co.x for i in isl) / len(isl)
            cy = sum(me.vertices[i].co.y for i in isl) / len(isl)
            best = None
            for tx, ty, dz in trunk_dz:
                d2 = (cx - tx) ** 2 + (cy - ty) ** 2
                if best is None or d2 < best[0]:
                    best = (d2, dz)
            if best is not None and best[0] < 16.0 and abs(best[1]) > 0.0:
                _shift(ob, isl, best[1])
        me.update()
    # palms / scrub / buildings / lights ride the terrain delta (their seats were already green)
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.name.upper().startswith(
                ("PALMTRUNK", "PALMFROND", "SCRUB", "BUILDING", "HOUSE", "LIGHTS")):
            continue
        me = ob.data
        for isl in _islands(ob):
            fi = min(isl, key=lambda i: me.vertices[i].co.z)
            f = ob.matrix_world @ me.vertices[fi].co
            zo = _surf_z(old_grass_bvh, f.x, f.y, zref=f.z, win=40.0)
            zn = _surf_z(ground_bvh, f.x, f.y, zref=f.z, win=40.0)
            if zo is None or zn is None:
                continue
            dz = zn - zo
            if abs(dz) > 0.02:
                _shift(ob, isl, dz); n_rel += 1
        me.update()
    print(f"[build_kn5_loop] re-seat: {n_trees} trees seated on the conformed ground, "
          f"{n_rel} props rode the terrain delta")


def main():
    import bpy

    proj = _project_dir(sys.argv)
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    cfg = json.loads((proj / "track.config.json").read_text())
    slug = cfg["slug"]
    (proj / "blender").mkdir(exist_ok=True)
    (proj / "build").mkdir(exist_ok=True)

    # 1. open the working scene
    bpy.ops.wm.open_mainfile(filepath=str(proj / "loop.blend"))

    # 1b. merge pre-built network OBJs (translated to the loop frame, e.g. by a merge_freeway step)
    #     into ONE kn5. Skipped when the project has none.
    for mobj in sorted(list((proj / "data").glob("track_*.obj")) + list((proj / "data").glob("env_*.obj"))):
        _add_obj_meshes(mobj)

    # 2. drop non-exported helpers (markers/cameras), rename meshes to AC convention
    for ob in list(bpy.data.objects):
        if ob.type != "MESH":
            bpy.data.objects.remove(ob, do_unlink=True); continue
        ob.name = AC_NAME.get(ob.name, ob.name)

    # 2b. terrain contact conform: declare the real bridge spans, pin the terrain to the deck under
    #     the footprint (subdividing the corridor first), spare the declared spans, and re-seat the
    #     props on the moved ground. Engine-owned so every future rebuild stays fixed.
    spans = declare_bridge_spans(proj)
    _conform_and_reseat(proj, spans)

    # split any mesh over the AC per-mesh vertex cap into uniquely-named tiles (big tracks: freeway terrain)
    for ob in list(o for o in bpy.data.objects if o.type == "MESH"):
        _split_large(ob)

    import bmesh
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        me = ob.data
        # props / billboards carry authored UVs — don't flatten (freeway BUSHES/CHAINLINK too)
        if not ob.name.upper().startswith(("PALM", "TREE", "SCRUB", "BUSHES", "CHAINLINK", "ROADTEXT")):
            planar_uv(me)
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
        if ob.name.upper().startswith("1GRASS"):
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.05)   # terrain must be watertight
            try:
                bmesh.ops.holes_fill(bm, edges=bm.edges, sides=16)
            except Exception as e:
                print(f"[build_kn5_loop] holes_fill skipped: {e}")
        # DRIVABLE surfaces must face UP or AC has no top collision and the car falls through. The
        # local->Blender axis remap (x,y,z)->(x,z,y) is a reflection that flipped every face down.
        # Fix DETERMINISTICALLY: reverse only the faces whose normal points down (normal.z<0). This
        # is NOT recalc_face_normals (which guesses "outward" from shape and picks DOWN on big
        # terrain); for a near-horizontal drivable surface "up" is unambiguous, so this can't guess
        # wrong or split the mesh. ...plus flat painted markings (MARKINGS/YLINE) — decals that
        # must face up to be seen from the car.
        if ob.name.upper().startswith(("1ROAD", "1GRASS", "1KERB", "MARKINGS", "YLINE")):
            bm.normal_update()
            down = [f for f in bm.faces if f.normal.z < 0]
            if down:
                bmesh.ops.reverse_faces(bm, faces=down)
            print(f"[build_kn5_loop] {ob.name}: flipped {len(down)}/{len(bm.faces)} faces up")
        bm.to_mesh(me); bm.free(); me.update()
        if len(me.loops) > VERT_CAP:         # smooth-shade big meshes so render-verts fit the 16-bit cap
            for poly in me.polygons:
                poly.use_smooth = True
            me.update()
        # loop-path over-cap guard: FATAL (the OBJ program guards in build_kn5.py; this path is its
        # own program and needs its own gate — a WARNING here shipped over-cap meshes before).
        assert_under_cap(ob.name, len(me.vertices))

    # 3. AC dummies from the real centreline (local frame x=E,y=up,z=N -> Blender x=E,y=N,z=up = (x,z,y))
    from scripts.geometry import dummies as dmod
    local = json.loads((proj / "data" / "centerline.local.json").read_text())
    cl = [tuple(p) for p in local["points_xyz_m"]]
    widths = local["widths_m"]
    n_pits = 8
    placed = dmod.place_dummies(cl, widths, n_sectors=3, n_pits=n_pits)
    # start facing = travel direction pts[0]->pts[1], as a yaw about Blender Z(up)
    tx, ty = cl[1][0] - cl[0][0], cl[1][2] - cl[0][2]          # Blender (E, N)
    start_yaw = math.atan2(tx, ty)
    FACING = ("AC_START", "AC_PIT", "AC_HOTLAP")
    dummies_out = {}
    for name, (x, y, z) in placed.items():
        e = bpy.data.objects.new(name, None)
        e.empty_display_type = "ARROWS"; e.empty_display_size = 4.0
        e.location = (x, z, y)                                  # local (E,up,N) -> Blender (E,N,up)
        if any(name.startswith(p) for p in FACING):
            e.rotation_euler = (0.0, 0.0, start_yaw)
        bpy.context.scene.collection.objects.link(e)
        dummies_out[name] = [round(x, 3), round(y, 3), round(z, 3)]
    (proj / "data" / "dummies.json").write_text(json.dumps(dummies_out, indent=1))

    # 4. PBR materials (prefix -> texture set); export_kn5_addon re-derives shader from the same
    #    prefix. Reconciled to the ENGINE pbr: config/capture texture_overrides apply here AND at
    #    export (load_overrides), so a loop project can e.g. swap 1GRASS dry dirt for green turf
    #    via track.config.json without renaming meshes.
    from scripts.ac import pbr
    overrides = pbr.load_overrides(proj)
    if overrides:
        print(f"[build_kn5_loop] texture overrides: {sorted(overrides)}")
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        pbr.setup_material(bpy, ob, overrides=overrides)

    # 5. pack textures + save the AC-ready .blend for the export pass
    try:
        bpy.ops.file.pack_all()
    except Exception as e:
        print(f"[build_kn5_loop] pack_all warning: {e}")
    out = proj / "blender" / f"{slug}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    meshes = [o.name for o in bpy.data.objects if o.type == "MESH"]
    print(f"[build_kn5_loop] prepped {meshes}  + {len(dummies_out)} dummies -> {out}")


if __name__ == "__main__":
    main()
