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
import shutil
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
    _patch_exporter(vendor)
    return vendor


def _patch_exporter(vendor: Path) -> None:
    """Idempotently fix the vendored exporter so textures embed off-Windows.

    Upstream hardcodes ``basedir = os.path.dirname(filepath) + '\\texture\\'`` (Windows separators),
    so on macOS the on-disk texture lookup never resolves and the kn5 ships with ZERO embedded
    textures — drivable but the ground renders flat/black. Rewrite it to a real ``texture/`` path with
    ``os.sep``. The vendor dir is gitignored / re-cloned, so we patch at run time (no-op once applied)."""
    ek = vendor / "export_kn5.py"
    src = ek.read_text(encoding="utf-8")
    broken = "basedir = os.path.dirname(filepath) + '\\\\texture\\\\'"
    fixed = "basedir = os.path.join(os.path.dirname(filepath), 'texture') + os.sep"
    if broken in src:
        ek.write_text(src.replace(broken, fixed), encoding="utf-8")
        print("[kn5_native] patched export_kn5.py texture path (Windows -> portable)")
    elif fixed not in src:
        print("[kn5_native] WARNING: texture-path anchor not found in export_kn5.py — upstream changed?")


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

    # AC dummies (AC_START/AC_PIT/AC_TIME/AC_HOTLAP) as tiny named nodes: the exporter only writes
    # meshes, not empties, and AC reads the node position from its geometry, so a 5 cm tri works.
    #
    # The position MUST live in the vertices, not in ob.location: the exporter bakes geometry with
    # `obj.matrix_world @ co`, but in `--background` the depsgraph isn't evaluated after we set
    # ob.location, so matrix_world stays identity and every marker collapsed to the world origin
    # (car spawned at the track centroid, metres underground -> fell through, no ground visible).
    # Bake the world position into the tri directly, like the road ribbon does.
    #
    # dummies.json is AC Y-up (x, y=up, z). The exporter applies convert_vector3 (x,y,z)->(x,z,-y)
    # to every vertex, so pre-rotate into Blender's frame with the inverse (x,-z,y) and leave the
    # object at the origin — the road reaches AC unchanged the same way (Y-up OBJ import + that one
    # convert == identity), so this lands the marker exactly on the road.
    dummies = json.loads((data / "dummies.json").read_text()) if (data / "dummies.json").exists() else {}
    for name, (x, y, z) in dummies.items():
        bx, by, bz = x, -z, y  # inverse of the exporter's convert_vector3, so it lands at AC (x,y,z)
        m = bpy.data.meshes.new(name)
        m.from_pydata([(bx, by, bz), (bx + 0.05, by, bz), (bx, by + 0.05, bz)], [], [(0, 1, 2)])
        ob = bpy.data.objects.new(name, m)
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

    # Stage every referenced texture where the (patched) exporter embeds from: build/texture/.
    # The exporter reads image files off disk by the textureName in settings.json (not from Blender's
    # loaded image nodes), so the files must exist there or the kn5 ships untextured.
    tex_src = pbr.texture_dir()
    tex_dst = out / "texture"
    tex_dst.mkdir(parents=True, exist_ok=True)
    needed = {t["textureName"] for m in settings["materials"].values() for t in m["textures"].values()}
    missing = [n for n in sorted(needed) if not (tex_src / n).exists()]
    for name in sorted(needed):
        if (tex_src / name).exists():
            shutil.copyfile(tex_src / name, tex_dst / name)
    print(f"[kn5_native] staged {len(needed) - len(missing)}/{len(needed)} textures -> {tex_dst}")
    if missing:
        print(f"[kn5_native] WARNING: textures not found in {tex_src}: {', '.join(missing)}")

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
