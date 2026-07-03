"""Merge FULL-DETAIL track meshes into the K10 data dir so build_kn5 imports them into ONE kn5.

Each merge_tracks[] entry names a track (Sand Creek, IMI) built at full quality by the loop/aerial
pipeline in its OWN frame. This translates that track's track.obj + environment.obj + dummies.json into
K10's shared origin frame, uniquifies every group name with a per-track suffix (keeping the 1ROAD_/
1KERB_/MARKINGS/... prefix so physics + materials still match), and drops each sub-track's own MOUNTAINS
backdrop (K10 has one). Result: the detailed tracks keep their kerbs/markings/textures/buildings/creek
bridges inside the unified drive-between map, instead of being reduced to bare network ribbons.

Build order (K10, v0.8): network_elev -> build_network_mesh -> merge_detailed -> build_network_env. The
connectors ride the REAL (despiked, grade-capped) ground from network_elev; merge runs AFTER build_network_mesh
and WELDS each track's entrance (its road vertex nearest a connector) onto that connector's Y, so the connector
meets the track deck at grade (0 m) with no launch ramp. The rest of the track keeps its own internal relief.

    python -m scripts.ac.merge_detailed projects/k10-colorado   (run AFTER build_network_mesh)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.config import load_config  # noqa: E402
from scripts.geometry.projection import _meters_per_degree  # noqa: E402

# K10 emits its own Front Range backdrop; drop each sub-track's. Also strip power poles / overhead wires /
# streetlights from every merged track — across a fictional multi-track map they read as "telephone poles
# everywhere" (user). Prefix-matched case-insensitively, so POLE_<slug>/WIRE_<slug>/LIGHTS_<slug> all go.
DROP_ENV = ("MOUNTAINS", "POLE", "WIRE", "LIGHTS")


def _road_verts_local(obj: Path, stride: int = 1):
    """Local 1ROAD (x,y,z) vertices of a sub-track's own track.obj (for entrance-weld matching)."""
    V: list = []; keep: set = set(); road = False
    for ln in obj.read_text().splitlines():
        if ln.startswith("v "):
            _, a, b, c = ln.split()[:4]; V.append((float(a), float(b), float(c)))
        elif ln.startswith("o "):
            road = ln[2:].strip().upper().startswith("1ROAD")
        elif ln.startswith("f ") and road:
            for tok in ln.split()[1:]:
                keep.add(int(tok.split("/")[0]) - 1)
    pts = [V[i] for i in sorted(keep)]
    return pts[::stride] if stride > 1 else pts


def _connector_verts(k10_data: Path, stride: int = 1):
    """Network CONNECTOR road vertices (1ROAD_part) in the K10 frame, from the already-built network
    track.obj. These ride the synthetic field; welding each track's nearest entrance vertex to the nearest
    connector vertex's Y makes the connector meet the track deck AT GRADE (no residual step)."""
    p = k10_data / "track.obj"
    if not p.exists():
        return []
    V: list = []; keep: set = set(); road = False
    for ln in p.read_text().splitlines():
        if ln.startswith("v "):
            _, a, b, c = ln.split()[:4]; V.append((float(a), float(b), float(c)))
        elif ln.startswith("o "):
            road = ln[2:].strip().upper().startswith("1ROAD_PART")
        elif ln.startswith("f ") and road:
            for tok in ln.split()[1:]:
                keep.add(int(tok.split("/")[0]) - 1)
    pts = [V[i] for i in sorted(keep)]
    return pts[::stride] if stride > 1 else pts


def _road_ref(obj: Path):
    """Local 1ROAD centroid (cx,cz), mean deck Y, and footprint radius from a sub-track's own track.obj.
    Used to seat the track ON the network ground (kill float) and to size its grass/scatter clear-disc."""
    V: list = []; keep: set = set(); road = False
    for ln in obj.read_text().splitlines():
        if ln.startswith("v "):
            _, a, b, c = ln.split()[:4]; V.append((float(a), float(b), float(c)))
        elif ln.startswith("o "):
            road = ln[2:].strip().upper().startswith("1ROAD")
        elif ln.startswith("f ") and road:
            for tok in ln.split()[1:]:
                keep.add(int(tok.split("/")[0]) - 1)
    if not keep:
        return None
    xs = [V[i][0] for i in keep]; ys = [V[i][1] for i in keep]; zs = [V[i][2] for i in keep]
    cx = sum(xs) / len(xs); cz = sum(zs) / len(zs)
    r = max(math.hypot(x - cx, z - cz) for x, z in zip(xs, zs))
    return cx, cz, sum(ys) / len(ys), r


def _terrain_sampler(k10: Path, lon0: float, lat0: float, elev0: float, m_lon: float, m_lat: float, sx: float):
    """Reconstruct build_network_mesh's terr_y(x,z): network ground height in the K10 local frame.
    Returns None if the heightfield hasn't been built yet (fall back to real-elevation placement)."""
    hf = k10 / "data" / "heightfield.npy"; mf = k10 / "data" / "heightfield.meta.json"
    if not (hf.exists() and mf.exists()):
        return None
    from scripts.geometry.build_mesh import read_npy
    grid = read_npy(hf); meta = json.loads(mf.read_text())
    s, w, n, e = meta["bbox_swne"]; nx, ny, sp = meta["nx"], meta["ny"], meta["spacing_m"]
    gy = sp / 111_000.0; gx = sp / (111_000.0 * math.cos(math.radians((s + n) / 2)))

    def terr_y(x, z):
        lon = lon0 + sx * x / m_lon; lat = lat0 + z / m_lat
        j = min(ny - 1, max(0, int(round((n - lat) / gy))))
        i = min(nx - 1, max(0, int(round((lon - w) / gx))))
        return grid[j][i] - elev0
    return terr_y


def _transform_obj(inp: Path, outp: Path, dx: float, dy: float, dz: float, suffix: str, drop=()):
    """Translate every vertex by (dx,dy,dz), suffix each group name, drop groups by prefix, re-index."""
    verts: list = []; vts: list = []; groups: list = []; cur = None
    for ln in inp.read_text().splitlines():
        s = ln.split()
        if not s:
            continue
        if s[0] == "v":
            verts.append((float(s[1]) + dx, float(s[2]) + dy, float(s[3]) + dz))
        elif s[0] == "vt":
            vts.append((float(s[1]), float(s[2])))
        elif s[0] == "o":
            cur = (ln[2:].strip(), []); groups.append(cur)
        elif s[0] == "f" and cur is not None:
            face = []
            for tok in s[1:]:
                p = tok.split("/")
                vi = int(p[0]) - 1
                ti = int(p[1]) - 1 if len(p) > 1 and p[1] else None
                face.append((vi, ti))
            cur[1].append(face)
    kept = [(n, fs) for n, fs in groups if not any(n.upper().startswith(d) for d in drop)]
    uv: dict = {}; ut: dict = {}; ov: list = []; ot: list = []

    def mv(i):
        if i not in uv:
            uv[i] = len(ov); ov.append(verts[i])
        return uv[i]

    def mt(i):
        if i is None:
            return None
        if i not in ut:
            ut[i] = len(ot); ot.append(vts[i])
        return ut[i]

    body = []
    for n, fs in kept:
        body.append(f"o {n}_{suffix}")
        for face in fs:
            toks = []
            for vi, ti in face:
                a = mv(vi); b = mt(ti)
                toks.append(f"{a + 1}/{b + 1}" if b is not None else f"{a + 1}")
            body.append("f " + " ".join(toks))
    with outp.open("w") as f:
        for x, y, z in ov:
            f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
        for u, v in ot:
            f.write(f"vt {u:.5f} {v:.5f}\n")
        f.write("\n".join(body) + "\n")
    return len(ov), len(kept)


def track_footprints(k10_dir: str | Path) -> dict:
    """{slug: {cx, cz, radius_m}} for each merged track in the K10 local frame — HORIZONTAL only, so it
    needs no heightfield and can be computed BEFORE the network mesh (which clears its grass/scatter from
    under each disc). Same maths as main(); kept side-effect-free so build_network_mesh/env can import it."""
    k10 = Path(k10_dir); cfg = load_config(k10); og = cfg.raw["origin"]
    K_lon, K_lat = float(og["lon"]), float(og["lat"])
    m_lon, m_lat = _meters_per_degree(K_lat)
    sx = -1.0 if cfg.raw.get("mirror_x", True) else 1.0
    out: dict = {}
    for mt in cfg.raw.get("merge_tracks", []):
        proj = Path(mt["project"])
        try:
            o = json.loads((proj / "data" / "centerline.local.json").read_text())["origin"]
            ref = _road_ref(proj / "data" / "track.obj")
        except FileNotFoundError:
            continue
        if ref is None:
            continue
        cxl, czl, _my, r = ref
        dx = sx * (o["lon"] - K_lon) * m_lon; dz = (o["lat"] - K_lat) * m_lat
        out[mt["slug"]] = {"cx": dx + cxl, "cz": dz + czl, "radius_m": r + 25.0}
    return out


def main(k10_dir: str) -> None:
    k10 = Path(k10_dir)
    cfg = load_config(k10)
    og = cfg.raw["origin"]
    K_lon, K_lat, K_elev = float(og["lon"]), float(og["lat"]), float(og["elev_m"])
    m_lon, m_lat = _meters_per_degree(K_lat)
    sx = -1.0 if cfg.raw.get("mirror_x", True) else 1.0
    data = k10 / "data"
    from scripts.elevation import synthetic_field  # noqa: E402
    # SYNTHETIC gentle field (fictional inter-track world): seat each track's mean deck at its chosen gentle
    # base height so it sits on the SAME field the connectors + ground ride -> connectors meet it at grade,
    # no 60 m cliff, no 190 m fake spread. Falls back to the old grass-terrain seat for non-synthetic projects.
    bases = synthetic_field.resolve_track_bases(k10) if synthetic_field.enabled(cfg) else None
    terr_y = None if bases else _terrain_sampler(k10, K_lon, K_lat, K_elev, m_lon, m_lat, sx)
    conn = _connector_verts(data, stride=1) if bases is not None else []   # network connector road verts (K10 frame)
    _CELL = 6.0; conn_hash: dict = {}
    for _cx, _cy, _cz in conn:                                             # spatial hash for exact nearest-connector
        conn_hash.setdefault((int(_cx // _CELL), int(_cz // _CELL)), []).append((_cx, _cy, _cz))

    def _nearest_conn(wx, wz):
        ci, cj = int(wx // _CELL), int(wz // _CELL); best = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for cvx, cvy, cvz in conn_hash.get((ci + di, cj + dj), ()):
                    d2 = (wx - cvx) ** 2 + (wz - cvz) ** 2
                    if best is None or d2 < best[0]:
                        best = (d2, cvy)
        return best
    pads: dict = {}
    for mt in cfg.raw.get("merge_tracks", []):
        slug = mt["slug"]; proj = Path(mt["project"])
        loc = json.loads((proj / "data" / "centerline.local.json").read_text())
        o = loc["origin"]
        # local(sub) -> local(K10): X = sx*(lon-lon0)*m_lon, so shifting lon0 sub->K adds sx*(sub-K)*m_lon
        dx = sx * (o["lon"] - K_lon) * m_lon
        dz = (o["lat"] - K_lat) * m_lat
        # SEAT ON NETWORK GROUND (kill float): place the track so its mean road deck sits on the network
        # heightfield at its footprint centre. The high-res per-track 3DEP build and the coarse network DEM
        # can disagree by tens of metres (Sand Creek floated +60 m); reconcile here so connectors — which
        # follow the network ground — meet each track at grade. Falls back to real elevation pre-heightfield.
        ref = _road_ref(proj / "data" / "track.obj")
        if bases is not None and slug in bases and ref is not None:
            cxl, czl, myl, r = ref
            pads[slug] = {"cx": round(dx + cxl, 2), "cz": round(dz + czl, 2), "radius_m": round(r + 25.0, 1)}
            # Seat on the REAL ground. Default: mean deck on the field. But shift (rigid) so the track's
            # ENTRANCE — its road vertex nearest a connector — lands on that connector's Y, so the connector
            # (which rides the real field at gentle grade) meets the track deck AT GRADE with no launch ramp
            # and no junction step. The rest of the track keeps its own internal relief around that seat.
            dy = bases[slug] - myl
            if conn:
                best = None                                       # exact global-nearest (track vert, connector Y)
                for lx, ly, lz in _road_verts_local(proj / "data" / "track.obj", stride=1):
                    nc = _nearest_conn(dx + lx, dz + lz)
                    if nc is not None and (best is None or nc[0] < best[0]):
                        best = (nc[0], nc[1], ly)
                if best is not None and best[0] <= 40.0 * 40.0:   # a connector reaches within 40 m -> weld to it
                    dy = best[1] - best[2]
        elif terr_y is not None and ref is not None:
            cxl, czl, myl, r = ref
            pad_y = terr_y(dx + cxl, dz + czl)
            dy = pad_y - myl
            pads[slug] = {"cx": round(dx + cxl, 2), "cz": round(dz + czl, 2), "radius_m": round(r + 25.0, 1)}
        else:
            dy = o["elev_m"] - K_elev
        nv, ng = _transform_obj(proj / "data" / "track.obj", data / f"track_{slug}.obj", dx, dy, dz, slug)
        env = proj / "data" / "environment.obj"
        if env.exists():
            _transform_obj(env, data / f"env_{slug}.obj", dx, dy, dz, slug, drop=DROP_ENV)
        layout = mt.get("layout", slug)   # which AC layout's spawn this track provides (None -> no spawn)
        dpath = proj / "data" / "dummies.json"
        if dpath.exists() and layout:
            d = json.loads(dpath.read_text())
            out = {k: [round(v[0] + dx, 3), round(v[1] + dy, 3), round(v[2] + dz, 3)] for k, v in d.items()}
            (data / f"dummies_{layout}.json").write_text(json.dumps(out, indent=1))
        print(f"merged {slug}: {nv} verts, {ng} groups, offset ({dx:.0f}, {dy:.1f}, {dz:.0f}) m")
    # footprints for build_network_mesh/env to clear network grass+scatter from UNDER each track disc
    (data / "track_pads.json").write_text(json.dumps(pads, indent=1))
    print(f"wrote {len(pads)} track pad footprint(s) -> data/track_pads.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "projects/k10-colorado")
