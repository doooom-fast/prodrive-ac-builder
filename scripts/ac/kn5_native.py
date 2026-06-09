"""Mac-native kn5 export — no Windows, no FBX round-trip.

Uses the pure-Python Hagnhofer kn5 exporter bundled in leBluem's ``io_import_accsv`` Blender addon.
That addon is GPL, so we don't vendor it: it's auto-cloned into ``vendor/io_import_accsv`` (gitignored)
on first run. This script builds the Blender scene from the project's ``track.obj`` + ``environment.obj``,
emits the AC dummies as tiny named nodes, generates the AC ``settings.json`` (shader + texture mappings
keyed off pbr.py), and writes ``build/<slug>.kn5``.

Run inside Blender:
    blender --background --python scripts/ac/kn5_native.py -- <project-dir>

Validate the result in Assetto Corsa / Content Manager (it can't be tested on the Mac). Known follow-ups:
AC_START/AC_PIT orientation (exported as positions only — facing may need a tweak in-game), and shader
choices are sensible defaults (tune per material in CM if desired).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

EXPORTER_REPO = "https://github.com/leBluem/io_import_accsv"


def _ensure_exporter(repo_root: Path) -> Path:
    vendor = repo_root / "vendor" / "io_import_accsv"
    if not (vendor / "export_kn5.py").exists():
        vendor.parent.mkdir(parents=True, exist_ok=True)
        print(f"[kn5_native] fetching GPL exporter -> {vendor}")
        subprocess.run(["git", "clone", "--depth", "1", EXPORTER_REPO, str(vendor)], check=True)
    return vendor


def _shader_and_textures(pbr, obj_name: str):
    """AC shader name + texture-slot mapping for an object, from pbr's prefix table."""
    key = next((k for k in pbr.TEXTURES if obj_name.upper().startswith(k)), None)
    if key is None:
        return "ksPerPixel", {}
    diff, norm = pbr.TEXTURES[key][0], pbr.TEXTURES[key][1]
    tx = {}
    if diff:
        tx["txDiffuse"] = {"textureName": diff}
    if norm:
        tx["txNormal"] = {"textureName": norm}
    if key == "TREES":
        return "ksTree", tx
    return ("ksPerPixelMultiMap" if norm else "ksPerPixel"), tx


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

    # materials (pbr image nodes -> textures embed) + AC settings.json (shaders + texture slot mappings)
    settings = {"materials": {}}
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        mat = pbr.setup_material(bpy, ob)
        shader, tx = _shader_and_textures(pbr, ob.name)
        is_tree = ob.name.upper().startswith("TREES")
        settings["materials"][mat.name] = {
            "shaderName": shader,
            "alphaBlendMode": "AlphaToCoverage" if is_tree else "Opaque",
            "alphaTested": is_tree,
            "depthMode": "DepthNormal",
            "properties": {},
            "textures": tx,
        }
    (out / "settings.json").write_text(json.dumps(settings, indent=1))

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
        print(f"[kn5_native] {'OK' if header == b'sc6969' else 'BAD HEADER'} — "
              f"{kn5_path} ({kn5_path.stat().st_size} bytes, header {header!r})")
    else:
        print("[kn5_native] FAILED — no kn5 written")


main()
