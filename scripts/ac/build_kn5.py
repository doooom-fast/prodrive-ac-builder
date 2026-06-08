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

    # 2. import the pre-built meshes (Y-up): the track + the dressed environment if present
    for obj_file in ("track.obj", "environment.obj"):
        p = data / obj_file
        if p.exists():
            bpy.ops.wm.obj_import(filepath=str(p), up_axis="Y", forward_axis="NEGATIVE_Z")

    # 3. AC dummy empties from dummies.json (ENU X-east / Y-up / Z-north metres)
    dummies = json.loads((data / "dummies.json").read_text()) if (data / "dummies.json").exists() else {}
    for name, (x, y, z) in dummies.items():
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = 3.0
        empty.location = (x, y, z)
        bpy.context.scene.collection.objects.link(empty)

    # 4. textured PBR material per object (pbr.py: tiling diffuse + normal on the generated UVs) +
    #    stamp the AC shader name from materials.json — the FBX carries the textures (path_mode=COPY)
    #    AND the kn5 gets the right shader.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pbr
    mat_file = data / "materials.json"
    mats = json.loads(mat_file.read_text())["materials"] if mat_file.exists() else {}
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        mat = pbr.setup_material(bpy, ob)
        prefix = next((p for p in mats if ob.name.upper().startswith(p.upper())), None)
        if prefix:
            mat["shaderName"] = mats[prefix]["shader"]  # read by AC Blender Tools

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
    if found:
        op_name, op = found[0]
        print(f"[build_kn5] kn5 export operator: {op_name}")
        try:
            op(filepath=str(out_kn5))
        except TypeError:
            op()  # some exporters read the path from a panel/scene setting instead
        return out_kn5

    # No direct kn5 exporter on this Blender (AC Tools exports FBX; direct-kn5 add-ons need Blender 3.x).
    # Fall back to an AC-standard FBX — convert to kn5 with Content Manager (import) or ksEditor.
    out_fbx = track_dir / "build" / f"{slug}.fbx"
    bpy.ops.export_scene.fbx(filepath=str(out_fbx), axis_forward="-Z", axis_up="Y",
                             apply_unit_scale=True, use_mesh_modifiers=True, path_mode="COPY")
    print(f"[build_kn5] no direct kn5 exporter found — wrote AC-standard FBX: {out_fbx}")
    print("           convert to .kn5 via Content Manager (track import) or ksEditor.")
    return out_fbx


def main() -> None:
    track_dir = _track_dir_from_argv(sys.argv)
    out = build(track_dir)
    print(f"[build_kn5] exported {out}")


if __name__ == "__main__":
    main()
