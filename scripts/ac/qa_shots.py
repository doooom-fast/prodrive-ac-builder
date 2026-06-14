"""Render car-height QA stills of the dressed track at interesting spots (Blender/Eevee).

Picks viewpoints that exercise the scenery: the start/finish gantry, the sharpest corner
(kerbs + jersey walls + chevrons), a creek crossing (water + riparian trees + guardrail), and a
long straight (buildings, signs, streetlights, horizon). Writes build/qa_NN_<name>.png.

Run:  blender --background --python scripts/ac/qa_shots.py -- <project-dir>
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pbr  # noqa: E402


def main():
    import bpy
    import mathutils
    a = sys.argv
    pd = Path(a[a.index("--") + 1])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    for obj_file in ("track.obj", "environment.obj"):
        p = pd / "data" / obj_file
        if p.exists():
            bpy.ops.wm.obj_import(filepath=str(p), up_axis="Y", forward_axis="NEGATIVE_Z")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for o in meshes:
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in meshes:
        pbr.setup_material(bpy, o)

    pts = json.loads((pd / "data" / "centerline.local.json").read_text())["points_xyz_m"]
    n = len(pts)

    # curvature to find the sharpest corner
    def rate(i):
        a_, b_, c_ = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        v1 = (b_[0] - a_[0], b_[2] - a_[2])
        v2 = (c_[0] - b_[0], c_[2] - b_[2])
        l1 = math.hypot(*v1) or 1e-6
        l2 = math.hypot(*v2) or 1e-6
        return abs(v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)

    # top-3 distinct sharpest corners (where the barriers cluster)
    ranked = sorted(range(1, n - 1), key=rate, reverse=True)
    corners: list = []
    for i in ranked:
        if all(min(abs(i - c), n - abs(i - c)) > 150 for c in corners):
            corners.append(i)
        if len(corners) == 3:
            break
    shots = [("start", -20, 10)]                # approaching the start/finish gantry
    shots += [(f"corner{k}", c - 25, c + 6) for k, c in enumerate(corners)]
    shots += [("midlap", n // 3, n // 3 + 30),
              ("backstretch", 2 * n // 3, 2 * n // 3 + 30)]

    # creek crossing: where a water line crosses the loop (guardrails + riparian trees)
    env_path = pd / "data" / "environment.geojson"
    if env_path.exists():
        import importlib
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        scenery = importlib.import_module("scripts.environment.scenery")
        projection = importlib.import_module("scripts.geometry.projection")
        local = json.loads((pd / "data" / "centerline.local.json").read_text())
        origin = (local["origin"]["lon"], local["origin"]["lat"])
        m_lon, m_lat = projection._meters_per_degree(origin[1])
        env = json.loads(env_path.read_text())["features"]
        loop_xz = [(p[0], p[2]) for p in pts]
        for f in env:
            if f["cls"] != "water" or f["kind"] != "line":
                continue
            w_xz = [((lo - origin[0]) * m_lon, (la - origin[1]) * m_lat) for lo, la in f["coords"]]
            hit_i = None
            for k in range(len(w_xz) - 1):
                for i in range(0, n - 6, 6):
                    if scenery._seg_hit(loop_xz[i], loop_xz[i + 6], w_xz[k], w_xz[k + 1]):
                        hit_i = i
                        break
                if hit_i is not None:
                    break
            if hit_i is not None:
                shots.append(("creek", hit_i - 22, hit_i + 8))
                break

    def to_bl(p):
        return mathutils.Vector((p[0], -p[2], p[1]))

    def look(cam, eye, target):
        fwd = (target - eye).normalized()
        up = mathutils.Vector((0, 0, 1))
        right = fwd.cross(up).normalized()
        tup = right.cross(fwd).normalized()
        cam.matrix_world = mathutils.Matrix((
            (right.x, tup.x, -fwd.x, eye.x),
            (right.y, tup.y, -fwd.y, eye.y),
            (right.z, tup.z, -fwd.z, eye.z),
            (0, 0, 0, 1)))

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 24
    cam_data.clip_end = 8000
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun_data.energy = 2.4
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), math.radians(15), math.radians(140))

    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    bpy.context.scene.world = world
    sky = world.node_tree.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "NISHITA"
        sky.sun_elevation = math.radians(40)
        sky.sun_rotation = math.radians(140)
    except Exception:
        pass
    bg = world.node_tree.nodes.get("Background")
    world.node_tree.links.new(sky.outputs[0], bg.inputs[0])
    bg.inputs[1].default_value = 0.5

    sc = bpy.context.scene
    engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.exposure = -0.5
    sc.render.resolution_x = 1280
    sc.render.resolution_y = 720

    for name, i0, i1 in shots:
        i0 %= n
        i1 %= n
        eye = to_bl(pts[i0]) + mathutils.Vector((0, 0, 2.2))
        target = to_bl(pts[i1]) + mathutils.Vector((0, 0, 1.2))
        look(cam, eye, target)
        out = pd / "build" / f"qa_{name}.png"
        sc.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("QA_SHOT", out)


main()
