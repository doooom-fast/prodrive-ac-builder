"""Inspect a kn5: embedded textures, materials/shaders, node tree, vertex counts.

Static QA for the Mac build host (the kn5 can't be driven here) — verifies the export carried
what the pipeline intended: every texture embedded, every material on the right shader with real
property values, all mesh groups + AC_ dummies present, vertex counts under the 65k mesh limit.

Run:  python -m scripts.ac.kn5_inspect projects/<slug> [--json]
"""

from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.o = 0

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.o)[0]
        self.o += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.o)[0]
        self.o += 4
        return v

    def byte(self) -> int:
        v = self.d[self.o]
        self.o += 1
        return v

    def s(self) -> str:
        n = self.u32()
        v = self.d[self.o:self.o + n].decode("utf-8", "replace")
        self.o += n
        return v

    def skip(self, n: int) -> None:
        self.o += n


def inspect(kn5_path: Path) -> dict:
    r = Reader(kn5_path.read_bytes())
    assert r.d[:6] == b"sc6969", "bad header"
    r.skip(6)
    version = r.u32()

    textures = []
    for _ in range(r.i32()):
        r.u32()  # active
        name = r.s()
        size = r.u32()
        fmt = "png" if r.d[r.o + 1:r.o + 4] == b"PNG" else ("dds" if r.d[r.o:r.o + 3] == b"DDS" else "?")
        textures.append({"name": name, "kb": round(size / 1024), "fmt": fmt})
        r.skip(size)

    materials = []
    for _ in range(r.i32()):
        name = r.s()
        shader = r.s()
        blend = r.byte()
        alpha_tested = bool(r.byte())
        depth = r.i32()
        props = {}
        for _ in range(r.u32()):
            pname = r.s()
            a = r.f32()
            r.skip(8 + 12 + 16)
            props[pname] = round(a, 3)
        texmap = {}
        for _ in range(r.u32()):
            slot_name = r.s()
            r.u32()
            texmap[slot_name] = r.s()
        materials.append({"name": name, "shader": shader, "blend": blend,
                          "alphaTested": alpha_tested, "depth": depth,
                          "props": props, "textures": texmap})

    meshes = []
    nodes = 0

    def node():
        nonlocal nodes
        nodes += 1
        cls = r.u32()
        name = r.s()
        children = r.u32()
        r.byte()  # active
        if cls == 1:
            r.skip(64)
        elif cls == 2:
            cast = bool(r.byte())
            visible = bool(r.byte())
            transparent = bool(r.byte())
            nv = r.u32()
            r.skip(nv * 44)
            ni = r.u32()
            r.skip(ni * 2)
            mat = r.u32()
            r.skip(4 + 4 + 4)   # layer, lodIn, lodOut
            r.skip(16)          # bounding sphere
            renderable = bool(r.byte())
            meshes.append({"name": name, "verts": nv, "tris": ni // 3, "mat": mat,
                           "cast": cast, "transparent": transparent, "renderable": renderable})
        for _ in range(children):
            node()

    node()
    return {"version": version, "file_mb": round(len(r.d) / 1e6, 1),
            "textures": textures, "materials": materials, "meshes": meshes, "nodes": nodes}


def main() -> None:
    project = Path(sys.argv[1])
    slug = json.loads((project / "track.config.json").read_text())["slug"]
    info = inspect(project / "build" / f"{slug}.kn5")
    if "--json" in sys.argv:
        print(json.dumps(info, indent=1))
        return
    print(f"kn5 v{info['version']}  {info['file_mb']} MB  "
          f"{len(info['textures'])} textures  {len(info['materials'])} materials  "
          f"{len(info['meshes'])} meshes / {info['nodes']} nodes")
    print("\n-- textures --")
    for t in info["textures"]:
        print(f"  {t['name']:<28} {t['kb']:>6} KB  {t['fmt']}")
    print("\n-- materials (shader, alpha, key props) --")
    for m in info["materials"]:
        flags = ("AT" if m["alphaTested"] else "") + ("B" if m["blend"] == 1 else "")
        print(f"  {m['name']:<24} {m['shader']:<16} {flags:<3} "
              f"amb={m['props'].get('ksAmbient', '-')} dif={m['props'].get('ksDiffuse', '-')} "
              f"tex={','.join(m['textures'])}")
    print("\n-- meshes (grouped) --")
    groups = Counter()
    verts = Counter()
    over = []
    for mesh in info["meshes"]:
        base = mesh["name"].split("_")[0]
        groups[base] += 1
        verts[base] += mesh["verts"]
        if mesh["verts"] > 65536:
            over.append(mesh["name"])
    for base, n in sorted(groups.items()):
        print(f"  {base:<16} x{n:<3} {verts[base]:>8} verts")
    ac = [m["name"] for m in info["meshes"] if m["name"].startswith("AC_")]
    print(f"\nAC dummies: {len(ac)} ({', '.join(sorted(ac)[:6])}…)")
    print("over-limit meshes:", over or "none")


if __name__ == "__main__":
    main()
