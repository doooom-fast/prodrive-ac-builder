"""Merge FULL-DETAIL track meshes into the K10 data dir so build_kn5 imports them into ONE kn5.

Each merge_tracks[] entry names a track (Sand Creek, IMI) built at full quality by the loop/aerial
pipeline in its OWN frame. This translates that track's track.obj + environment.obj + dummies.json into
K10's shared origin frame, uniquifies every group name with a per-track suffix (keeping the 1ROAD_/
1KERB_/MARKINGS/... prefix so physics + materials still match), and drops each sub-track's own MOUNTAINS
backdrop (K10 has one). Result: the detailed tracks keep their kerbs/markings/textures/buildings/creek
bridges inside the unified drive-between map, instead of being reduced to bare network ribbons.

    python -m scripts.ac.merge_detailed projects/k10-colorado   (run AFTER build_network_mesh)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.config import load_config  # noqa: E402
from scripts.geometry.projection import _meters_per_degree  # noqa: E402

DROP_ENV = ("MOUNTAINS",)   # K10 emits its own Front Range backdrop; drop each sub-track's to avoid dupes


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


def main(k10_dir: str) -> None:
    k10 = Path(k10_dir)
    cfg = load_config(k10)
    og = cfg.raw["origin"]
    K_lon, K_lat, K_elev = float(og["lon"]), float(og["lat"]), float(og["elev_m"])
    m_lon, m_lat = _meters_per_degree(K_lat)
    sx = -1.0 if cfg.raw.get("mirror_x", True) else 1.0
    data = k10 / "data"
    for mt in cfg.raw.get("merge_tracks", []):
        slug = mt["slug"]; proj = Path(mt["project"])
        loc = json.loads((proj / "data" / "centerline.local.json").read_text())
        o = loc["origin"]
        # local(sub) -> local(K10): X = sx*(lon-lon0)*m_lon, so shifting lon0 sub->K adds sx*(sub-K)*m_lon
        dx = sx * (o["lon"] - K_lon) * m_lon
        dz = (o["lat"] - K_lat) * m_lat
        dy = o["elev_m"] - K_elev
        nv, ng = _transform_obj(proj / "data" / "track.obj", data / f"track_{slug}.obj", dx, dy, dz, slug)
        env = proj / "data" / "environment.obj"
        if env.exists():
            _transform_obj(env, data / f"env_{slug}.obj", dx, dy, dz, slug, drop=DROP_ENV)
        dpath = proj / "data" / "dummies.json"
        if dpath.exists():
            d = json.loads(dpath.read_text())
            out = {k: [round(v[0] + dx, 3), round(v[1] + dy, 3), round(v[2] + dz, 3)] for k, v in d.items()}
            (data / f"dummies_{slug}.json").write_text(json.dumps(out, indent=1))
        print(f"merged {slug}: {nv} verts, {ng} groups, offset ({dx:.0f}, {dy:.1f}, {dz:.0f}) m")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "projects/k10-colorado")
