"""Headless Blender entry point — build the mesh and export the kn5.

Run from Blender (bpy is provided by the Blender runtime, not pip):

    blender --background --python scripts/ac/build_kn5.py -- <track-dir>

Reads <track-dir>/track.config.json + data/, builds the scene (1ROAD ribbon, GRASS heightfield,
dummies), assigns materials via the AC Blender Tools addon, and exports build/<slug>.kn5.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _track_dir_from_argv(argv: list[str]) -> Path:
    """Blender passes script args after a literal ``--``."""
    if "--" not in argv:
        raise SystemExit("usage: blender --background --python build_kn5.py -- <track-dir>")
    rest = argv[argv.index("--") + 1:]
    if not rest:
        raise SystemExit("missing <track-dir> after '--'")
    return Path(rest[0])


def build(track_dir: Path) -> Path:
    """Build the Blender scene from the project data and export the kn5. Returns the kn5 path."""
    import json

    import bpy  # only available inside Blender

    data = track_dir / "data"
    slug = json.loads((track_dir / "track.config.json").read_text())["slug"]
    out_kn5 = track_dir / "build" / f"{slug}.kn5"
    out_kn5.parent.mkdir(parents=True, exist_ok=True)
    (track_dir / "blender").mkdir(parents=True, exist_ok=True)

    # 1. empty scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 2. import the pre-built mesh (Phase 4 track.obj is Y-up; groups GRASS / 1ROAD_main)
    bpy.ops.wm.obj_import(filepath=str(data / "track.obj"), up_axis="Y", forward_axis="NEGATIVE_Z")

    # 3. AC dummy empties from dummies.json (ENU X-east / Y-up / Z-north metres)
    dummies = json.loads((data / "dummies.json").read_text()) if (data / "dummies.json").exists() else {}
    for name, (x, y, z) in dummies.items():
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = 3.0
        empty.location = (x, y, z)
        bpy.context.scene.collection.objects.link(empty)

    # 4. assign an AC shader per object by mesh-name prefix (materials.json from scripts.ac.materials)
    mat_file = data / "materials.json"
    mats = json.loads(mat_file.read_text())["materials"] if mat_file.exists() else {}
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        prefix = next((p for p in mats if ob.name.upper().startswith(p.upper())), None)
        if prefix:
            mat = bpy.data.materials.new(prefix)
            mat["shaderName"] = mats[prefix]["shader"]  # read by AC Blender Tools
            ob.data.materials.clear()
            ob.data.materials.append(mat)

    bpy.ops.wm.save_as_mainfile(filepath=str(track_dir / "blender" / f"{slug}.blend"))

    # 5. export kn5. Auto-detect whichever export operator the installed AC add-on registered
    #    (AC Tools, moppius/blender-assetto-corsa-tools, io_import_accsv, …) — no hardcoded name.
    found = []
    for modname in dir(bpy.ops):
        mod = getattr(bpy.ops, modname)
        for opname in dir(mod):
            if "kn5" in opname.lower() or "assetto" in opname.lower():
                found.append((f"{modname}.{opname}", getattr(mod, opname)))
    found.sort(key=lambda x: ("export" not in x[0].lower(), x[0]))  # prefer export ops
    if not found:
        ops = [f"{m}.{o}" for m in dir(bpy.ops) for o in dir(getattr(bpy.ops, m)) if "export" in o.lower()]
        raise SystemExit(
            "No kn5 export operator found — enable an AC kn5 exporter add-on (AC Tools / "
            f"moppius/blender-assetto-corsa-tools). Scene saved to blender/{slug}.blend.\n"
            f"Available export operators: {ops}")
    op_name, op = found[0]
    print(f"[build_kn5] export operator: {op_name}  (candidates: {[f for f, _ in found]})")
    try:
        op(filepath=str(out_kn5))
    except TypeError:
        op()  # some exporters read the path from a panel/scene setting instead
    return out_kn5


def main() -> None:
    track_dir = _track_dir_from_argv(sys.argv)
    out = build(track_dir)
    print(f"[build_kn5] exported {out}")


if __name__ == "__main__":
    main()
