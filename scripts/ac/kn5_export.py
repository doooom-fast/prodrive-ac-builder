"""Pure-Python OBJ → kn5 export — no Blender, no bpy.

This is the Blender-free replacement for ``kn5_native.py``: it reads the geometry the geometry pass
already wrote (``data/track.obj`` + ``data/environment.obj``, both AC Y-up metres) plus the AC dummy
positions (``data/dummies.json``), assigns materials by mesh-name prefix from :mod:`scripts.ac.pbr`,
embeds the referenced textures, and serialises a valid ``build/<slug>.kn5`` directly.

Why it can drop Blender: the geometry is already built without bpy (shapely/numpy/trimesh), and the
kn5 *writer* was only ever pure-Python wrapped in Blender. The byte layout here is the exact inverse
of :mod:`scripts.modkit.extract_kn5`'s reader (and matches the vendored Hagnhofer/leBluem writer), so
a written file round-trips back through that reader — which is how the tests prove format correctness
without AC.

Coordinate convention: the Blender path imported the Y-up OBJ (Y→Z-up) and then applied the exporter's
``convert_vector3`` (Z→Y-up) — the two cancel, so the *net* OBJ→kn5 transform is identity. We therefore
write OBJ coordinates straight through with no conversion (and dummies.json, already AC Y-up, likewise).

Run (plain Python, no Blender):
    python -m scripts.ac.kn5_export projects/sand-creek-raceway

Validation: format correctness is unit-tested via a write→extract_kn5.parse round-trip. The in-AC
*visual* checks that genuinely need the game (UV V-orientation, shader-property lighting, dummy facing)
are the same Mac-side follow-ups kn5_native called out — see scripts/preview/README.md.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scripts.ac import pbr

KN5_MAGIC = b"sc6969"
KN5_VERSION = 5
VERTEX_LIMIT = 2**16 - 1  # u16 index space; a single mesh node can't exceed this many vertices

BLEND_MODE = {"Opaque": 0, "AlphaBlend": 1, "AlphaToCoverage": 2}
DEPTH_MODE = {"DepthNormal": 0, "DepthNoWrite": 1, "DepthOff": 2}
# leBluem's default shader property set; zeros unless settings override (parity with the Blender path).
DEFAULT_SHADER_PROPS = ("ksAmbient", "ksDiffuse", "ksSpecular", "ksSpecularEXP", "ksEmissive", "ksAlphaRef")


# --- OBJ parsing ---------------------------------------------------------------

@dataclass
class ObjObject:
    """One ``o``/``g`` group from an OBJ: triangles indexing the shared v/vt/vn pools."""

    name: str
    # each triangle is 3 corners; a corner is (v_idx, vt_idx|None, vn_idx|None), all 0-based
    tris: list[tuple[tuple[int, int | None, int | None], ...]] = field(default_factory=list)


@dataclass
class Obj:
    positions: list[tuple[float, float, float]]
    uvs: list[tuple[float, float]]
    normals: list[tuple[float, float, float]]
    objects: list[ObjObject]


def _parse_corner(tok: str) -> tuple[int, int | None, int | None]:
    """Parse a ``v/vt/vn`` face token (any field optional) into 0-based indices."""
    parts = (tok.split("/") + ["", ""])[:3]

    def idx(s: str) -> int | None:
        return int(s) - 1 if s else None

    return idx(parts[0]), idx(parts[1]), idx(parts[2])


def parse_obj(text: str, default_name: str = "object") -> Obj:
    """Minimal OBJ reader: v/vt/vn pools + ``o``/``g`` groups, faces fan-triangulated."""
    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []
    objects: list[ObjObject] = []
    cur: ObjObject | None = None

    def ensure_object() -> ObjObject:
        nonlocal cur
        if cur is None:
            cur = ObjObject(default_name)
            objects.append(cur)
        return cur

    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        tag, _, rest = line.partition(" ")
        rest = rest.strip()
        if tag == "v":
            x, y, z = (float(v) for v in rest.split()[:3])
            positions.append((x, y, z))
        elif tag == "vt":
            u, v, *_ = (float(t) for t in rest.split()) or (0.0, 0.0)
            uvs.append((u, v))
        elif tag == "vn":
            x, y, z = (float(n) for n in rest.split()[:3])
            normals.append((x, y, z))
        elif tag in ("o", "g"):
            cur = ObjObject(rest or default_name)
            objects.append(cur)
        elif tag == "f":
            corners = [_parse_corner(t) for t in rest.split()]
            obj = ensure_object()
            for i in range(1, len(corners) - 1):  # fan-triangulate
                obj.tris.append((corners[0], corners[i], corners[i + 1]))

    return Obj(positions, uvs, normals, [o for o in objects if o.tris])


# --- vertex assembly + tangents ------------------------------------------------

@dataclass
class Vertex:
    pos: tuple[float, float, float]
    normal: tuple[float, float, float]
    uv: tuple[float, float]
    tangent: tuple[float, float, float] = (1.0, 0.0, 0.0)


@dataclass
class Mesh:
    name: str
    material_id: int
    vertices: list[Vertex]
    indices: list[int]


def _face_normal(a, b, c) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    m = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return (nx / m, ny / m, nz / m)


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    m = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
    return (v[0] / m, v[1] / m, v[2] / m) if m else (1.0, 0.0, 0.0)


def build_mesh(obj: ObjObject, src: Obj, material_id: int, *, flip_uv_v: bool = True) -> list[Mesh]:
    """Assemble dedup'd vertex/index buffers for one OBJ object, splitting at the u16 vertex limit.

    Tangents are accumulated per Lengyel's method from positions + UVs (needed for normal mapping).
    ``flip_uv_v`` writes ``(u, -v)`` to mirror the Blender exporter's explicit UV-V negation."""
    index: dict[tuple, int] = {}
    verts: list[Vertex] = []
    tan_accum: list[tuple[float, float, float]] = []
    indices: list[int] = []

    def corner_vertex(c) -> int:
        vi, vti, vni = c
        pos = src.positions[vi]
        uv = src.uvs[vti] if (vti is not None and vti < len(src.uvs)) else (0.0, 0.0)
        if flip_uv_v:
            uv = (uv[0], -uv[1])
        normal = src.normals[vni] if (vni is not None and vni < len(src.normals)) else None
        key = (vi, vti, vni)
        if key in index:
            return index[key]
        new = len(verts)
        index[key] = new
        verts.append(Vertex(pos, normal or (0.0, 1.0, 0.0), uv))
        tan_accum.append((0.0, 0.0, 0.0))
        return new

    for tri in obj.tris:
        ia, ib, ic = (corner_vertex(c) for c in tri)
        indices.extend((ia, ib, ic))
        # face normal fallback for corners with no vn in the OBJ
        for c, vidx in zip(tri, (ia, ib, ic)):
            if c[2] is None:
                fn = _face_normal(verts[ia].pos, verts[ib].pos, verts[ic].pos)
                verts[vidx].normal = fn
        # tangent contribution (Lengyel) accumulated onto the three corners
        _accumulate_tangent(verts, tan_accum, ia, ib, ic)

    for i, v in enumerate(verts):
        t = tan_accum[i]
        v.normal = _normalize(v.normal)
        v.tangent = _normalize(t) if (t[0] or t[1] or t[2]) else _orthogonal(v.normal)

    mesh = Mesh(obj.name, material_id, verts, indices)
    return _split_for_vertex_limit(mesh)


def _accumulate_tangent(verts, tan_accum, ia, ib, ic) -> None:
    a, b, c = verts[ia], verts[ib], verts[ic]
    e1 = (b.pos[0] - a.pos[0], b.pos[1] - a.pos[1], b.pos[2] - a.pos[2])
    e2 = (c.pos[0] - a.pos[0], c.pos[1] - a.pos[1], c.pos[2] - a.pos[2])
    du1, dv1 = b.uv[0] - a.uv[0], b.uv[1] - a.uv[1]
    du2, dv2 = c.uv[0] - a.uv[0], c.uv[1] - a.uv[1]
    denom = du1 * dv2 - du2 * dv1
    if abs(denom) < 1e-12:
        return
    f = 1.0 / denom
    t = (f * (dv2 * e1[0] - dv1 * e2[0]),
         f * (dv2 * e1[1] - dv1 * e2[1]),
         f * (dv2 * e1[2] - dv1 * e2[2]))
    for i in (ia, ib, ic):
        ta = tan_accum[i]
        tan_accum[i] = (ta[0] + t[0], ta[1] + t[1], ta[2] + t[2])


def _orthogonal(n: tuple[float, float, float]) -> tuple[float, float, float]:
    """Any unit vector perpendicular to n (tangent fallback for UV-less meshes)."""
    ref = (0.0, 0.0, 1.0) if abs(n[1]) < 0.99 else (1.0, 0.0, 0.0)
    t = (n[1] * ref[2] - n[2] * ref[1], n[2] * ref[0] - n[0] * ref[2], n[0] * ref[1] - n[1] * ref[0])
    return _normalize(t)


def _split_for_vertex_limit(mesh: Mesh) -> list[Mesh]:
    """Split a mesh whose vertex count exceeds the u16 limit into sub-meshes (re-indexed)."""
    if len(mesh.vertices) <= VERTEX_LIMIT:
        return [mesh]
    out: list[Mesh] = []
    i = 0
    part = 0
    while i < len(mesh.indices):
        remap: dict[int, int] = {}
        sub_verts: list[Vertex] = []
        sub_idx: list[int] = []
        while i < len(mesh.indices) and len(remap) <= VERTEX_LIMIT - 3:
            for vidx in mesh.indices[i:i + 3]:
                if vidx not in remap:
                    remap[vidx] = len(sub_verts)
                    sub_verts.append(mesh.vertices[vidx])
                sub_idx.append(remap[vidx])
            i += 3
        out.append(Mesh(f"{mesh.name}__{part}", mesh.material_id, sub_verts, sub_idx))
        part += 1
    return out


# --- materials -----------------------------------------------------------------

@dataclass
class Material:
    name: str
    shader: str
    alpha_blend: int
    alpha_tested: bool
    depth_mode: int
    texture_mapping: dict[str, str]  # slot -> texture (basename)


def _shader_and_textures(prefix_key: str | None, diff: str | None, norm: str | None):
    """AC shader + texture-slot mapping for a mesh, mirroring kn5_native._shader_and_textures."""
    tx: dict[str, str] = {}
    if diff:
        tx["txDiffuse"] = diff
    if norm:
        tx["txNormal"] = norm
    if prefix_key == "TREES":
        return "ksTree", tx
    return ("ksPerPixelMultiMap" if norm else "ksPerPixel"), tx


def material_for(obj_name: str, overrides: dict[str, dict]) -> tuple[Material, dict[str, str]]:
    """Build the Material for a mesh by name prefix, plus the {basename: source_path} textures it needs.

    Pure equivalent of pbr.setup_material's *naming*: material name is ``<obj>_mat``; the texture set
    and alpha behaviour come from pbr.TEXTURES / pbr.BILLBOARD, with captured overrides swapped in."""
    name = obj_name.upper()
    key = next((k for k in pbr.TEXTURES if name.startswith(k)), None)
    diff_file, norm_file = (pbr.TEXTURES[key][0], pbr.TEXTURES[key][1]) if key else (None, None)
    ov = overrides.get(key or "", {})

    sources: dict[str, str] = {}
    diff = norm = None
    if ov.get("diffuse"):
        diff = Path(ov["diffuse"]).name
        sources[diff] = ov["diffuse"]
    elif diff_file:
        diff = diff_file
        sources[diff] = str(pbr.texture_dir() / diff_file)
    if ov.get("normal"):
        norm = Path(ov["normal"]).name
        sources[norm] = ov["normal"]
    elif norm_file:
        norm = norm_file
        sources[norm] = str(pbr.texture_dir() / norm_file)

    shader, mapping = _shader_and_textures(key, diff, norm)
    is_billboard = key in pbr.BILLBOARD
    mat = Material(
        name=f"{obj_name}_mat",
        shader=shader,
        alpha_blend=BLEND_MODE["AlphaToCoverage"] if is_billboard else BLEND_MODE["Opaque"],
        alpha_tested=is_billboard,
        depth_mode=DEPTH_MODE["DepthNormal"],
        texture_mapping=mapping,
    )
    return mat, sources


# --- binary writer -------------------------------------------------------------

class _Writer:
    """The byte primitives of the kn5 format (little-endian), matching the vendored KN5Writer."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v)

    def i32(self, v: int) -> None:
        self.buf += struct.pack("<i", v)

    def u16(self, v: int) -> None:
        self.buf += struct.pack("<H", v)

    def f32(self, v: float) -> None:
        self.buf += struct.pack("<f", v)

    def boolean(self, v: bool) -> None:
        self.buf += b"\x01" if v else b"\x00"

    def string(self, s: str) -> None:
        b = s.encode("utf-8")
        self.u32(len(b))
        self.buf += b

    def blob(self, b: bytes) -> None:
        self.u32(len(b))
        self.buf += b

    def vec3(self, v) -> None:
        self.buf += struct.pack("<3f", *v)


def _write_textures(w: _Writer, textures: dict[str, bytes]) -> None:
    w.i32(len(textures))
    for name, data in textures.items():
        w.i32(1)  # active
        w.string(name)
        w.blob(data)


def _write_materials(w: _Writer, materials: list[Material]) -> None:
    w.i32(len(materials))
    for m in materials:
        w.string(m.name)
        w.string(m.shader)
        w.buf += struct.pack("<B", m.alpha_blend)
        w.boolean(m.alpha_tested)
        w.i32(m.depth_mode)
        w.u32(len(DEFAULT_SHADER_PROPS))
        for prop in DEFAULT_SHADER_PROPS:
            w.string(prop)
            w.f32(0.0)                       # valueA
            w.buf += struct.pack("<2f", 0.0, 0.0)   # valueB
            w.buf += struct.pack("<3f", 0.0, 0.0, 0.0)  # valueC
            w.buf += struct.pack("<4f", 0.0, 0.0, 0.0, 0.0)  # valueD
        w.u32(len(m.texture_mapping))
        for slot, (mapping_name, tex_name) in enumerate(m.texture_mapping.items()):
            w.string(mapping_name)
            w.u32(slot)
            w.string(tex_name)


def _bounding_sphere(verts: list[Vertex]) -> tuple[tuple[float, float, float], float]:
    xs = [v.pos[0] for v in verts] or [0.0]
    ys = [v.pos[1] for v in verts] or [0.0]
    zs = [v.pos[2] for v in verts] or [0.0]
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    center = tuple((lo[i] + hi[i]) / 2 for i in range(3))
    radius = max((hi[i] - lo[i]) / 2 for i in range(3)) * 2
    return center, radius


def _write_mesh_node(w: _Writer, mesh: Mesh) -> None:
    w.u32(2)  # class Mesh
    w.string(mesh.name)
    w.u32(0)  # child count
    w.boolean(True)   # active
    w.boolean(True)   # castShadows
    w.boolean(True)   # visible
    w.boolean(False)  # transparent
    w.u32(len(mesh.vertices))
    for v in mesh.vertices:
        w.buf += struct.pack("<3f3f2f3f", *v.pos, *v.normal, *v.uv, *v.tangent)
    w.u32(len(mesh.indices))
    w.buf += struct.pack(f"<{len(mesh.indices)}H", *mesh.indices)
    w.u32(mesh.material_id)
    w.u32(0)    # layer
    w.f32(0.0)  # lodIn
    w.f32(0.0)  # lodOut
    center, radius = _bounding_sphere(mesh.vertices)
    w.vec3(center)
    w.f32(radius)
    w.boolean(True)  # isRenderable


def _write_base_node(w: _Writer, name: str, child_count: int) -> None:
    w.u32(1)  # class Node
    w.string(name)
    w.u32(child_count)
    w.boolean(True)
    w.buf += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)  # identity


# --- top-level export ----------------------------------------------------------

def _dummy_meshes(dummies: dict, material_id: int) -> list[Mesh]:
    """A tiny 5 cm tri at each AC dummy position — AC reads the marker's location from geometry.

    No coordinate conversion: dummies.json is AC Y-up and we write straight through (the Blender path
    pre-rotated only to cancel the exporter's convert_vector3, which we don't apply)."""
    out = []
    for name, (x, y, z) in dummies.items():
        verts = [
            Vertex((x, y, z), (0.0, 1.0, 0.0), (0.0, 0.0)),
            Vertex((x + 0.05, y, z), (0.0, 1.0, 0.0), (0.0, 0.0)),
            Vertex((x, y, z + 0.05), (0.0, 1.0, 0.0), (0.0, 0.0)),
        ]
        out.append(Mesh(name, material_id, verts, [0, 1, 2]))
    return out


def build_kn5_bytes(project_dir: Path, *, flip_uv_v: bool = True) -> tuple[bytes, dict]:
    """Assemble the full kn5 byte payload for a project. Returns (bytes, stats)."""
    data = project_dir / "data"
    overrides = pbr.load_overrides(project_dir)

    materials: list[Material] = []
    mat_id: dict[str, int] = {}
    textures: dict[str, bytes] = {}
    meshes: list[Mesh] = []

    def register_material(obj_name: str) -> int:
        mat, sources = material_for(obj_name, overrides)
        if mat.name not in mat_id:
            mat_id[mat.name] = len(materials)
            materials.append(mat)
            for basename, srcpath in sources.items():
                p = Path(srcpath)
                if basename not in textures and p.is_file():
                    textures[basename] = p.read_bytes()
        return mat_id[mat.name]

    for obj_file in ("track.obj", "environment.obj"):
        p = data / obj_file
        if not p.exists():
            continue
        parsed = parse_obj(p.read_text(encoding="utf-8"), default_name=p.stem)
        for obj in parsed.objects:
            mid = register_material(obj.name)
            meshes.extend(build_mesh(obj, parsed, mid, flip_uv_v=flip_uv_v))

    # AC dummy markers share one textureless material
    dummies_path = data / "dummies.json"
    if dummies_path.exists():
        dummies = json.loads(dummies_path.read_text())
        if dummies:
            dummy_mat = Material("ac_dummy_mat", "ksPerPixel", BLEND_MODE["Opaque"], False,
                                 DEPTH_MODE["DepthNormal"], {})
            mat_id[dummy_mat.name] = len(materials)
            materials.append(dummy_mat)
            meshes.extend(_dummy_meshes(dummies, mat_id[dummy_mat.name]))

    slug = json.loads((project_dir / "track.config.json").read_text())["slug"]
    w = _Writer()
    w.buf += KN5_MAGIC
    w.u32(KN5_VERSION)
    _write_textures(w, textures)
    _write_materials(w, materials)
    _write_base_node(w, slug, len(meshes))
    for mesh in meshes:
        _write_mesh_node(w, mesh)

    stats = {
        "meshes": len(meshes),
        "materials": len(materials),
        "textures": len(textures),
        "vertices": sum(len(m.vertices) for m in meshes),
        "triangles": sum(len(m.indices) // 3 for m in meshes),
    }
    return bytes(w.buf), stats


def export(project_dir: Path, *, flip_uv_v: bool = True) -> Path:
    """Build the kn5 and write it to ``build/<slug>.kn5``. Returns the path."""
    project_dir = Path(project_dir).resolve()
    payload, stats = build_kn5_bytes(project_dir, flip_uv_v=flip_uv_v)
    slug = json.loads((project_dir / "track.config.json").read_text())["slug"]
    out = project_dir / "build" / f"{slug}.kn5"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    print(f"[kn5_export] wrote {out} ({len(payload)} bytes) — "
          f"{stats['meshes']} meshes, {stats['materials']} materials, {stats['textures']} textures, "
          f"{stats['vertices']} verts, {stats['triangles']} tris")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="prodrive-kn5-export",
        description="Export a project's OBJ geometry to an AC kn5 — no Blender required.")
    ap.add_argument("project", help="project dir (e.g. projects/sand-creek-raceway)")
    ap.add_argument("--no-flip-uv", action="store_true",
                    help="write UV V unchanged (default flips to (u,-v) to match the Blender path)")
    args = ap.parse_args(argv)
    project = Path(args.project)
    if not (project / "track.config.json").exists():
        print(f"error: {project} has no track.config.json", file=sys.stderr)
        return 1
    export(project, flip_uv_v=not args.no_flip_uv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
