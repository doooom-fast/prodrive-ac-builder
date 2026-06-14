"""Mac-native kn5 export — no Windows, no FBX round-trip.

Uses the pure-Python Hagnhofer kn5 exporter bundled in leBluem's ``io_import_accsv`` Blender addon.
That addon is GPL, so we don't vendor it: it's auto-cloned into ``vendor/io_import_accsv``
(gitignored) on first run, then three small fixes are patched in (idempotent string replaces):

  1. texture dir — upstream hardcodes a Windows ``'\\texture\\'`` path, so on macOS textures were
     silently skipped and the kn5 shipped untextured;
  2. normals — upstream writes Blender-frame normals raw (no Z-up→Y-up swap), which lit the track
     sideways in AC;
  3. tangents — same missing axis conversion (matters for normal-mapped shaders).

This script builds the Blender scene from ``track.obj`` + ``environment.obj``, emits the AC
dummies as tiny named nodes, stages every referenced texture into ``build/texture/``, generates
``settings.json`` (shader + texture slots + real ksAmbient/ksDiffuse/… values + alpha modes +
per-node flags, all from ``pbr.MATS``) and writes ``build/<slug>.kn5``.

Run inside Blender:
    blender --background --python scripts/ac/kn5_native.py -- <project-dir>

Validate the result in Assetto Corsa / Content Manager (it can't be driven on the Mac).
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

EXPORTER_REPO = "https://github.com/leBluem/io_import_accsv"

# (file, broken text, fixed text) — applied once; skipped when already patched
_PATCHES = [
    ("export_kn5.py",
     "basedir = os.path.dirname(filepath) + '\\\\texture\\\\'",
     "basedir = os.path.join(os.path.dirname(filepath), 'texture') + os.sep"),
    ("kn5/exporter_utils.py",
     "def convert_vector3_normal(in_vec):\n"
     "    ### return Vector((in_vec[0]*100, in_vec[2]*100, -in_vec[1]*100))\n"
     "    return Vector((in_vec[0], in_vec[1], in_vec[2]))",
     "def convert_vector3_normal(in_vec):\n"
     "    # axis-converted like positions (Blender Z-up -> AC Y-up) — patched by kn5_native.py\n"
     "    return Vector((in_vec[0], in_vec[2], -in_vec[1]))"),
    ("kn5/node_writer.py",
     "                        tangent = loop.tangent",
     "                        tangent = (loop.tangent[0], loop.tangent[2], -loop.tangent[1])"),
]


def _ensure_exporter(repo_root: Path) -> Path:
    vendor = repo_root / "vendor" / "io_import_accsv"
    if not (vendor / "export_kn5.py").exists():
        vendor.parent.mkdir(parents=True, exist_ok=True)
        print(f"[kn5_native] fetching GPL exporter -> {vendor}")
        subprocess.run(["git", "clone", "--depth", "1", EXPORTER_REPO, str(vendor)], check=True)
    for fname, broken, fixed in _PATCHES:
        p = vendor / fname
        src = p.read_text(encoding="utf-8")
        if fixed in src:
            continue
        if broken not in src:
            print(f"[kn5_native] WARNING: patch anchor not found in {fname} — upstream changed?")
            continue
        p.write_text(src.replace(broken, fixed), encoding="utf-8")
        print(f"[kn5_native] patched {fname}")
    return vendor


def _material_settings(pbr, obj_name: str, mat_name: str) -> tuple[dict, dict]:
    """(settings.json material entry, texture name set) for one object, from pbr.MATS."""
    row = pbr.lookup(obj_name) or {}
    shader = row.get("shader", "ksPerPixel")
    alpha = row.get("alpha")
    textures = {}
    if row.get("diff"):
        textures["txDiffuse"] = {"textureName": Path(row["diff"]).name}
    if row.get("norm") and shader.endswith("NM"):
        textures["txNormal"] = {"textureName": Path(row["norm"]).name}
    props = {}
    for key, val in (row.get("props") or {}).items():
        if isinstance(val, (tuple, list)):
            props[key] = {"valueC": list(val)}
        else:
            props[key] = {"valueA": float(val)}
    entry = {
        "shaderName": shader,
        "alphaBlendMode": {"test": "AlphaToCoverage", "blend": "AlphaBlend"}.get(alpha, "Opaque"),
        "alphaTested": alpha == "test",
        "depthMode": "DepthNormal",
        "properties": props,
        "textures": textures,
    }
    return entry, {Path(t["textureName"]).name for t in textures.values()}


def main() -> None:
    import bpy
    argv = sys.argv
    project_dir = Path(argv[argv.index("--") + 1])
    repo = project_dir.parents[1]
    vendor = _ensure_exporter(repo)
    sys.path.insert(0, str(vendor))
    sys.path.insert(0, str(vendor / "kn5"))   # the kn5 modules use sibling imports
    sys.path.insert(0, str(repo / "scripts" / "ac"))
    import pbr

    data = project_dir / "data"
    slug = json.loads((project_dir / "track.config.json").read_text())["slug"]
    out = project_dir / "build"
    out.mkdir(parents=True, exist_ok=True)
    kn5_path = out / f"{slug}.kn5"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    for obj_file in ("track.obj", "environment.obj"):
        p = data / obj_file
        if p.exists():
            bpy.ops.wm.obj_import(filepath=str(p), up_axis="Y", forward_axis="NEGATIVE_Z")

    # AC dummies as tiny named nodes (the exporter only writes meshes, not empties; AC reads the node
    # by name + transform, so a 5 cm tri works as a marker).
    dummies = json.loads((data / "dummies.json").read_text()) if (data / "dummies.json").exists() else {}
    for name, (x, y, z) in dummies.items():
        m = bpy.data.meshes.new(name)
        m.from_pydata([(0, 0, 0), (0.05, 0, 0), (0, 0.05, 0)], [], [(0, 1, 2)])
        ob = bpy.data.objects.new(name, m)
        ob.location = (x, y, z)
        bpy.context.scene.collection.objects.link(ob)

    # materials (pbr image nodes for preview/packing) + AC settings.json from the same table
    settings = {"materials": {}, "nodes": {}}
    needed_textures: set = set()
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        mat = pbr.setup_material(bpy, ob)
        entry, texnames = _material_settings(pbr, ob.name, mat.name)
        settings["materials"][mat.name] = entry
        needed_textures |= texnames
        row = pbr.lookup(ob.name) or {}
        node: dict = {}
        if row.get("shadows") is False:
            node["castShadows"] = False
        if row.get("alpha") == "blend":
            node["isTransparent"] = True
        # every mesh object needs an entry (even empty) — the exporter's NodeSettings pass
        # KeyErrors on names missing from settings["nodes"] once the key exists at all
        settings["nodes"][ob.name] = node
    for name in dummies:
        settings["nodes"][name] = {}
    (out / "settings.json").write_text(json.dumps(settings, indent=1))

    # stage textures where the (patched) exporter embeds from: build/texture/
    tex_src = pbr.texture_dir()
    legacy_src = tex_src.parent  # assets/textures (hand-placed extras)
    tex_dst = out / "texture"
    tex_dst.mkdir(parents=True, exist_ok=True)
    missing = []
    for name in sorted(needed_textures):
        src = tex_src / name if (tex_src / name).exists() else legacy_src / name
        if src.exists():
            shutil.copyfile(src, tex_dst / name)
        else:
            missing.append(name)
    if missing:
        print(f"[kn5_native] WARNING: textures not found (run texgen?): {', '.join(missing)}")

    import export_kn5
    for ob in bpy.data.objects:
        ob.select_set(ob.type == "MESH")
    try:
        kn5_path.unlink()
    except OSError:
        pass
    export_kn5.save(bpy.context, str(kn5_path), 1.0)

    ok = kn5_path.exists() and kn5_path.stat().st_size > 64
    if ok:
        with open(kn5_path, "rb") as f:
            header = f.read(6)
            import struct
            _ver = struct.unpack("<I", f.read(4))[0]
            ntex = struct.unpack("<I", f.read(4))[0]
        print(f"[kn5_native] {'OK' if header == b'sc6969' else 'BAD HEADER'} — "
              f"{kn5_path} ({kn5_path.stat().st_size} bytes, header {header!r}, {ntex} textures)")
    else:
        print("[kn5_native] FAILED — no kn5 written")


main()
