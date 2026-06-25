"""Extract named meshes (+ their textures) from an AC ``.kn5`` into OBJ/MTL/PNG.

This is the MESH side of the mod-mining pipeline (the texture side only ever pulled DDS blobs). It
decodes the kn5 node tree — the format is the exact inverse of the vendored exporter's node_writer.py:

    node  := class:u32  name:str  childCount:u32  active:bool  <body>  child*childCount
    class 1 (base)  body := matrix:16f
    class 2 (mesh)  body := castShadows,visible,transparent:3*bool  vCount:u32
                            vert*vCount{ pos:3f normal:3f uv:2f tangent:3f }   # 11 floats / 44 B
                            iCount:u32  index*iCount:u16  materialId:u32  layer:u32
                            lodIn:f lodOut:f  boundingSphere:4f  isRenderable:bool
    class 3 (skinned) — not yet (track scenery is static class-2; raises if hit)

Pure-Python + Pillow (for DDS→PNG), Mac-native, reproducible (no /tmp). The mesh world transform is
accumulated down the base-node chain so multi-part objects assemble; ``--recenter`` (default) drops the
result to origin (xz-centred, base at y=0) so it's a reusable prop.

    python -m scripts.modkit.extract_kn5 <file.kn5> --list
    python -m scripts.modkit.extract_kn5 <file.kn5> --match 'tree|cespuglio' --out assets/props/_raw
    python -m scripts.modkit.extract_kn5 <file.kn5> --extract NAME1 NAME2 --out <dir>

AC content is Y-up metres like our pipeline, so extracted geometry stands upright as-is.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.o = 0

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.o)[0]; self.o += 4; return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.o)[0]; self.o += 4; return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.d, self.o)[0]; self.o += 2; return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.o)[0]; self.o += 4; return v

    def boolean(self) -> bool:
        v = self.d[self.o]; self.o += 1; return v != 0

    def blob(self, n: int) -> bytes:
        v = self.d[self.o:self.o + n]; self.o += n; return v

    def string(self) -> str:
        n = self.u32(); v = self.d[self.o:self.o + n].decode("utf-8", "replace"); self.o += n; return v

    def matrix(self) -> list[float]:
        return [self.f32() for _ in range(16)]


_IDENT = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _matmul(a: list[float], b: list[float]) -> list[float]:
    """Row-major 4x4 multiply A*B (point convention p' = p*M, translation in floats 12..14)."""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def _xform(m: list[float], x: float, y: float, z: float) -> tuple[float, float, float]:
    return (x * m[0] + y * m[4] + z * m[8] + m[12],
            x * m[1] + y * m[5] + z * m[9] + m[13],
            x * m[2] + y * m[6] + z * m[10] + m[14])


def parse(path: Path) -> dict:
    """Parse a kn5 into {version, textures{name:blob}, materials[], meshes[]}."""
    d = Path(path).read_bytes()
    if d[:6] != b"sc6969":
        raise ValueError(f"not a kn5 (bad magic {d[:6]!r})")
    r = _Reader(d)
    r.o = 6
    version = r.i32()
    if version > 5:
        r.i32()  # extra header field present in v6+ (untested until a real v6 file)

    textures: dict[str, bytes] = {}
    for _ in range(r.i32()):
        r.i32()                       # active flag
        name = r.string()
        blob = r.blob(r.u32())
        textures[name] = blob

    materials = []
    for _ in range(r.u32()):
        name = r.string(); shader = r.string()
        r.blob(2)                     # alphaBlend + alphaTest
        r.i32()                       # depthMode
        for _ in range(r.u32()):      # shader properties: name + 40 bytes of float values
            r.string(); r.blob(40)
        slots = []
        for _ in range(r.u32()):      # texture slots
            sname = r.string(); r.i32(); tname = r.string()
            slots.append((sname, tname))
        materials.append({"name": name, "shader": shader, "textures": slots})

    meshes = []

    def read_node(parent: list[float]):
        ncls = r.u32(); name = r.string(); child_count = r.u32(); r.boolean()
        if ncls == 1:                                   # base / dummy: own transform, then children
            world = _matmul(r.matrix(), parent)
            for _ in range(child_count):
                read_node(world)
        elif ncls == 2:                                 # static mesh
            r.boolean(); r.boolean(); r.boolean()       # castShadows, visible, transparent
            vcount = r.u32()
            verts = []
            for _ in range(vcount):
                px, py, pz = r.f32(), r.f32(), r.f32()
                r.f32(); r.f32(); r.f32()               # normal (unused for OBJ shape)
                u, v = r.f32(), r.f32()
                r.f32(); r.f32(); r.f32()               # tangent
                verts.append((px, py, pz, u, v))
            idx = [r.u16() for _ in range(r.u32())]
            matid = r.u32(); r.u32(); r.f32(); r.f32()  # material, layer, lodIn, lodOut
            r.blob(16); r.boolean()                     # bounding sphere + isRenderable
            meshes.append({"name": name, "verts": verts, "idx": idx, "matid": matid, "xf": parent})
            for _ in range(child_count):
                read_node(parent)
        elif ncls == 3:
            raise NotImplementedError(f"SkinnedMesh (class 3) not supported yet: {name!r}")
        else:
            raise ValueError(f"unknown node class {ncls} at offset {r.o} ({name!r})")

    read_node(_IDENT)
    return {"version": version, "textures": textures, "materials": materials, "meshes": meshes}


def _world_verts(mesh: dict) -> list[tuple[float, float, float, float, float]]:
    m = mesh["xf"]
    return [(*_xform(m, x, y, z), u, v) for (x, y, z, u, v) in mesh["verts"]]


def write_obj(meshes: list[dict], materials: list[dict], out_obj: Path, *, recenter: bool = True) -> dict:
    """Write selected meshes (merged) to one OBJ + MTL. Returns stats. recenter → drop to origin."""
    allw = [_world_verts(m) for m in meshes]
    flat = [v for w in allw for v in w]
    if not flat:
        raise ValueError("no geometry in the selected meshes")
    cx = (min(v[0] for v in flat) + max(v[0] for v in flat)) / 2 if recenter else 0.0
    cz = (min(v[2] for v in flat) + max(v[2] for v in flat)) / 2 if recenter else 0.0
    by = min(v[1] for v in flat) if recenter else 0.0

    lines = [f"mtllib {out_obj.stem}.mtl"]
    voff = 0
    used_mats = {}
    for mesh, w in zip(meshes, allw):
        mat = materials[mesh["matid"]] if mesh["matid"] < len(materials) else {"name": "default"}
        used_mats[mat["name"]] = mat
        lines.append(f"o {mesh['name']}")
        lines.append(f"usemtl {mat['name']}")
        for x, y, z, _u, _v in w:
            lines.append(f"v {x - cx:.5f} {y - by:.5f} {z - cz:.5f}")
        for _x, _y, _z, u, v in w:
            lines.append(f"vt {u:.5f} {v:.5f}")
        for a, b, c in (mesh["idx"][i:i + 3] for i in range(0, len(mesh["idx"]) - 2, 3)):
            lines.append(f"f {a+1+voff}/{a+1+voff} {b+1+voff}/{b+1+voff} {c+1+voff}/{c+1+voff}")
        voff += len(w)
    out_obj.write_text("\n".join(lines) + "\n", encoding="utf-8")

    mtl = []
    for name, mat in used_mats.items():
        mtl.append(f"newmtl {name}")
        diff = next((t for s, t in mat.get("textures", []) if s.lower() in ("txdiffuse", "diffuse")), None)
        if diff:
            mtl.append(f"map_Kd {Path(diff).stem}.png")
        mtl.append("Kd 0.8 0.8 0.8\n")
    out_obj.with_suffix(".mtl").write_text("\n".join(mtl) + "\n", encoding="utf-8")
    return {"meshes": len(meshes), "vertices": voff, "triangles": voff and sum(len(m["idx"]) // 3 for m in meshes),
            "materials": list(used_mats)}


def save_textures(parsed: dict, names: set[str], out_dir: Path) -> list[str]:
    """Write the given texture blobs out as .dds and (if Pillow can) decode to .png alongside."""
    saved = []
    try:
        from PIL import Image
        import io
        have_pil = True
    except Exception:
        have_pil = False
    for tname, blob in parsed["textures"].items():
        if names and tname not in names:
            continue
        stem = Path(tname).stem
        (out_dir / f"{stem}.dds").write_bytes(blob)
        saved.append(f"{stem}.dds")
        if have_pil:
            try:
                Image.open(io.BytesIO(blob)).convert("RGBA").save(out_dir / f"{stem}.png")
                saved[-1] = f"{stem}.png"
            except Exception as e:
                print(f"  ! could not decode {tname}: {e}")
    return saved


def _textures_for(meshes: list[dict], materials: list[dict]) -> set[str]:
    out = set()
    for m in meshes:
        if m["matid"] < len(materials):
            out.update(t for _s, t in materials[m["matid"]].get("textures", []))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract meshes/textures from an AC kn5.")
    ap.add_argument("kn5", type=Path)
    ap.add_argument("--list", action="store_true", help="print the mesh inventory and exit")
    ap.add_argument("--match", help="regex over mesh names to extract")
    ap.add_argument("--extract", nargs="+", help="explicit mesh names to extract")
    ap.add_argument("--out", type=Path, default=Path("assets/props/_raw"))
    ap.add_argument("--name", help="output basename (default: derived)")
    ap.add_argument("--no-recenter", action="store_true")
    args = ap.parse_args()

    parsed = parse(args.kn5)
    mats = parsed["materials"]
    meshes = parsed["meshes"]
    print(f"kn5 v{parsed['version']}: {len(parsed['textures'])} textures, {len(mats)} materials, "
          f"{len(meshes)} meshes")

    if args.list or not (args.match or args.extract):
        for m in meshes:
            mat = mats[m["matid"]] if m["matid"] < len(mats) else {"name": "?", "shader": "?"}
            print(f"  {m['name']:<34} {len(m['verts']):>7} v  {len(m['idx'])//3:>7} tri  "
                  f"[{mat['shader']}] {mat['name']}")
        if not (args.match or args.extract):
            return

    if args.extract:
        want = set(args.extract)
        sel = [m for m in meshes if m["name"] in want]
    else:
        rx = re.compile(args.match, re.I)
        sel = [m for m in meshes if rx.search(m["name"])]
    if not sel:
        print("no meshes matched."); sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    base = args.name or re.sub(r"[^A-Za-z0-9_]+", "_", (args.match or sel[0]["name"]))
    stats = write_obj(sel, mats, args.out / f"{base}.obj", recenter=not args.no_recenter)
    texs = save_textures(parsed, _textures_for(sel, mats), args.out)
    print(f"  -> {args.out/base}.obj  ({stats['vertices']} v, {stats['triangles']} tri, "
          f"mats={stats['materials']})")
    print(f"  -> textures: {texs}")


if __name__ == "__main__":
    main()
