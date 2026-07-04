"""Export a tiny per-layout SPAWN kn5 for each layout that has a spawn anchor.

For a multi-track network map, each track is an AC layout over ONE shared geometry kn5. AC reads the
start/pit dummies (AC_START/AC_PIT/AC_TIME/AC_HOTLAP) from the loaded kn5s, so to give each layout its
OWN start point we keep the main kn5 free of spawns and ship a small per-layout kn5 that contains only
that layout's dummies. models_<layout>.ini loads BOTH (main geometry + this spawn kn5). This is the
standard AC "timing gates in a per-config kn5" pattern and respects layouts-share-one-kn5 (CLAUDE.md).

Dummies come from data/dummies_<layout>.json (build_network_mesh, per layouts[].spawn), placed on the
nearest road to each anchor. They are yawed here by true_north_rotation_deg to match the main model's
sun-fix yaw (scripts/ac/build_kn5.py).

    "$BLENDER" --background --python scripts/ac/build_spawn_kn5.py -- <track-dir>
"""

import json
import math
import sys
import tempfile
import zipfile
from pathlib import Path

import addon_utils
import bpy


def _track_dir(argv):
    if "--" not in argv:
        raise SystemExit("usage: blender --background --python build_spawn_kn5.py -- <track-dir>")
    rest = argv[argv.index("--") + 1:]
    if not rest:
        raise SystemExit("missing <track-dir> after '--'")
    return Path(rest[0]).resolve()


project = _track_dir(sys.argv)
repo = Path(__file__).resolve().parents[2]
cfg = json.loads((project / "track.config.json").read_text())
slug = cfg["slug"]
data = project / "data"
build = project / "build"
build.mkdir(parents=True, exist_ok=True)
yaw_deg = float(cfg.get("true_north_rotation_deg", 0.0))
yr = math.radians(yaw_deg)
yc, ys = math.cos(yr), math.sin(yr)

# install + enable the AC add-on once (zipped on the fly from the vendored copy)
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_src = repo / "vendor" / "io_import_accsv"
if not (addon_src / "__init__.py").exists():
    raise SystemExit(f"vendored AC add-on missing at {addon_src}")
_zip = Path(tempfile.gettempdir()) / "_ac_addon_vendored.zip"
with zipfile.ZipFile(_zip, "w", zipfile.ZIP_DEFLATED) as z:
    for f in addon_src.rglob("*"):
        if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
            z.write(f, Path("io_import_accsv") / f.relative_to(addon_src))
bpy.ops.preferences.addon_install(filepath=str(_zip), overwrite=True)
for mod in addon_utils.modules():
    if any(k in mod.__name__.lower() for k in ("assetto", "corsa", "accsv")):
        try:
            bpy.ops.preferences.addon_enable(module=mod.__name__)
        except Exception as e:
            print("enable err", e)


def _find_export_op():
    if hasattr(bpy.ops, "exporter") and hasattr(bpy.ops.exporter, "kn5"):
        return bpy.ops.exporter.kn5
    for modname in dir(bpy.ops):
        mod = getattr(bpy.ops, modname)
        for opname in dir(mod):
            if "kn5" in opname.lower() or "assetto" in opname.lower():
                return getattr(mod, opname)
    return None


op = _find_export_op()
# Clear any leftover persistence .ini from the main export — the add-on embeds every texture it lists,
# which would bloat a dummies-only spawn kn5 by ~25 MB of unused textures.
for old in build.glob("*.ini"):
    old.unlink()
FACING = ("AC_START", "AC_PIT", "AC_HOTLAP")
layouts = [lo for lo in cfg.get("layouts", []) if lo.get("spawn")]
print(f"[spawn_kn5] yaw={yaw_deg} layouts={[lo['id'] for lo in layouts]}")
for lo in layouts:
    lid = lo["id"]
    dpath = data / f"dummies_{lid}.json"
    if not dpath.exists():
        print(f"[spawn_kn5] no dummies_{lid}.json — skip")
        continue
    # clear the scene WITHOUT read_factory_settings (which resets prefs -> disables the add-on -> the
    # kn5 operator disappears). Just remove all objects between layouts.
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    dummies = json.loads(dpath.read_text())
    # dummies-only scene: the exporter writes each AC_* empty as a base node (node_writer._write_object
    # -> _write_base_node). A mesh here would hit _split_object_by_materials and fail without materials;
    # empties do not, so no root mesh is needed.
    for name, (x, y, z) in dummies.items():
        e = bpy.data.objects.new(name, None)
        e.empty_display_type = "ARROWS"
        e.empty_display_size = 3.0
        e.location = (x * yc + z * ys, x * ys - z * yc, y)   # same yaw as build_kn5's dummies
        if any(name.startswith(p) for p in FACING):
            e.rotation_euler = (0.0, 0.0, yr)
        bpy.context.scene.collection.objects.link(e)
    out = build / f"{slug}__{lid}.kn5"
    try:
        out.unlink()
    except OSError:
        pass
    for ob in bpy.data.objects:
        ob.select_set(True)
    if op is not None:
        try:
            op("EXEC_DEFAULT", filepath=str(out))
        except Exception as ex:
            import traceback
            print(f"[spawn_kn5] export EXCEPTION {lid}: {ex}")
            traceback.print_exc()
    exists = out.exists()
    print(f"[spawn_kn5] {lid}: kn5={exists} size={out.stat().st_size if exists else 0} dummies={len(dummies)}")
