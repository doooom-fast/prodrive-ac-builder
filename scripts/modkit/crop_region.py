"""Crop an XZ region out of a merged map kn5 into a standalone, recentred multi-material OBJ prop.

SRP-style city kn5s merge every building's geometry by MATERIAL across a whole chunk (all windows in one
mesh, all concrete in another), so no single mesh is one building. The reusable kitbash unit is therefore
a SPATIAL TILE: keep every triangle (across all meshes) whose centroid falls in an XZ box (and a sane Y
band, to drop sky/underground junk), regroup by material, and drop the result to the origin (XZ-centred,
base at Y=0). That yields a "city block" prop — real buildings, windows, façades — ready to scatter.

    python -m scripts.modkit.crop_region <in.kn5> --center X Z --size M [--ymax M] --out <dir> --name blockA

Writes <dir>/<name>.obj + .mtl + the referenced textures as PNG (stdlib + Pillow, no /tmp).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.modkit.extract_kn5 import parse, _world_verts, save_textures, _textures_for


TRI_MAX_M = 60.0   # drop any triangle whose own bounding box exceeds this (sky/ground spanning quads)


def crop(kn5: Path, cx: float, cz: float, size: float, ymax: float, out_dir: Path, name: str) -> dict:
    p = parse(kn5)
    mats = p["materials"]
    half = size / 2.0
    x0, x1, z0, z1 = cx - half, cx + half, cz - half, cz + half

    # collect kept triangles per material (world space)
    kept: dict[int, list[tuple]] = {}     # matid -> list of (v0,v1,v2) each (x,y,z,u,v)
    ymin_seen = 1e18
    for m in p["meshes"]:
        wv = _world_verts(m)
        idx = m["idx"]
        for t in range(0, len(idx) - 2, 3):
            tri = (wv[idx[t]], wv[idx[t + 1]], wv[idx[t + 2]])
            gx = sum(v[0] for v in tri) / 3.0
            gz = sum(v[2] for v in tri) / 3.0
            if not (x0 <= gx <= x1 and z0 <= gz <= z1 and min(v[1] for v in tri) <= ymax):
                continue
            # reject giant map-spanning quads (sky/ground/water): a real building triangle is small,
            # so cap each triangle's own extent. This keeps the per-material building batches (whose
            # individual tris are small) while dropping the handful of huge background polys.
            ext = max(max(v[a] for v in tri) - min(v[a] for v in tri) for a in (0, 1, 2))
            if ext > TRI_MAX_M:
                continue
            kept.setdefault(m["matid"], []).append(tri)
            ymin_seen = min(ymin_seen, min(v[1] for v in tri))
    if not kept:
        raise SystemExit("no geometry in that region — adjust --center/--size")

    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"mtllib {name}.mtl"]
    voff = 0
    used = {}
    for matid, tris in kept.items():
        mat = mats[matid] if matid < len(mats) else {"name": f"mat{matid}"}
        used[mat["name"]] = mat
        lines.append(f"o block_{mat['name']}")
        lines.append(f"usemtl {mat['name']}")
        for tri in tris:
            for (x, y, z, _u, _v) in tri:
                lines.append(f"v {x - cx:.4f} {y - ymin_seen:.4f} {z - cz:.4f}")   # recenter XZ, base at 0
        for tri in tris:
            for (_x, _y, _z, u, v) in tri:
                lines.append(f"vt {u:.5f} {v:.5f}")
        for i in range(len(tris)):
            a = voff + i * 3 + 1
            lines.append(f"f {a}/{a} {a+1}/{a+1} {a+2}/{a+2}")
        voff += len(tris) * 3
    (out_dir / f"{name}.obj").write_text("\n".join(lines) + "\n", encoding="utf-8")

    mtl = []
    for mn, mat in used.items():
        mtl.append(f"newmtl {mn}")
        diff = next((t for s, t in mat.get("textures", []) if s.lower() in ("txdiffuse", "diffuse")), None)
        if diff:
            mtl.append(f"map_Kd {Path(diff).stem}.png")
        mtl.append("Kd 0.8 0.8 0.8\n")
    (out_dir / f"{name}.mtl").write_text("\n".join(mtl) + "\n", encoding="utf-8")

    sel_meshes = [m for m in p["meshes"] if m["matid"] in kept]
    texs = save_textures(p, _textures_for(sel_meshes, mats), out_dir)
    tri_total = sum(len(t) for t in kept.values())
    print(f"[crop] {name}: {tri_total} tris, {len(used)} materials, {len(texs)} textures -> {out_dir/name}.obj")
    return {"tris": tri_total, "materials": list(used), "textures": texs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kn5", type=Path)
    ap.add_argument("--center", nargs=2, type=float, required=True, metavar=("X", "Z"))
    ap.add_argument("--size", type=float, default=200.0)
    ap.add_argument("--ymax", type=float, default=140.0)
    ap.add_argument("--out", type=Path, default=Path("projects/san-diego-cruise/assets/blocks"))
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    crop(a.kn5, a.center[0], a.center[1], a.size, a.ymax, a.out, a.name)


if __name__ == "__main__":
    main()
