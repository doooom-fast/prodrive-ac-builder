"""Render an OBJ prop to a transparent billboard PNG (front orthographic view) via headless Blender.

Turns a heavy real mesh (e.g. a mined 13k-tri California palm) into a flat cutout card that can be
scattered thousands of times cheaply. Wires each material's image alpha for clean frond cutouts,
frames the mesh with an ortho camera, transparent film, EEVEE.

    blender --background --python scripts/modkit/render_billboard.py -- <in.obj> <out.png> [px]
"""

import sys
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
in_obj, out_png = Path(argv[0]), Path(argv[1])
PX = int(argv[2]) if len(argv) > 2 else 768

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=str(in_obj), up_axis="Y", forward_axis="NEGATIVE_Z")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]

# wire image alpha -> Principled alpha (CLIP) so frond gaps cut out
for ob in meshes:
    for slot in ob.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        img = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
        if bsdf and img and "Alpha" in (o.name for o in img.outputs):
            try:
                nt.links.new(img.outputs["Alpha"], bsdf.inputs["Alpha"])
                mat.blend_method = "CLIP"
                mat.alpha_threshold = 0.5
            except Exception:
                pass

# bounding box over all meshes (world space)
import mathutils  # noqa: E402
mn = mathutils.Vector((1e9, 1e9, 1e9)); mx = mathutils.Vector((-1e9, -1e9, -1e9))
for ob in meshes:
    for c in ob.bound_box:
        w = ob.matrix_world @ mathutils.Vector(c)
        mn = mathutils.Vector((min(mn[i], w[i]) for i in range(3)))
        mx = mathutils.Vector((max(mx[i], w[i]) for i in range(3)))
center = (mn + mx) / 2
# OBJ is imported Y-up -> Blender Z-up, so the prop STANDS along Blender Z (height=Z, width=X).
# Frame it from the -Y side looking horizontally (+Y) so we get a proper side elevation, not a top-down.
import math  # noqa: E402
width = (mx - mn).x
height = (mx - mn).z
size = max(width, height) * 1.06

cam_data = bpy.data.cameras.new("cam"); cam_data.type = "ORTHO"; cam_data.ortho_scale = size
cam = bpy.data.objects.new("cam", cam_data); bpy.context.scene.collection.objects.link(cam)
cam.location = (center.x, mn.y - size * 2, center.z)       # stand back on -Y, centered on X/Z
cam.rotation_euler = (math.pi / 2, 0, 0)                   # look horizontally toward +Y
bpy.context.scene.camera = cam

sun_d = bpy.data.lights.new("sun", "SUN"); sun_d.energy = 3.5
sun = bpy.data.objects.new("sun", sun_d); bpy.context.scene.collection.objects.link(sun)
sun.rotation_euler = (1.0, 0.1, 0.4)

sc = bpy.context.scene
try:
    sc.render.engine = "BLENDER_EEVEE_NEXT"   # Blender 4.2 EEVEE
except Exception:
    sc.render.engine = "BLENDER_EEVEE"
sc.render.film_transparent = True
sc.render.resolution_x = sc.render.resolution_y = PX
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
sc.render.filepath = str(out_png)
bpy.ops.render.render(write_still=True)
print(f"[render_billboard] wrote {out_png} ({PX}px) from {in_obj.name}")
