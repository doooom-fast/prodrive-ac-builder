"""Shared PBR material setup for the Blender render/export scripts.

Maps an imported object's name prefix to a texture set under ``assets/textures/`` and builds a
Principled material with a tiling diffuse + normal map driven by the mesh's UVs (generated in the
geometry pass). Falls back to a flat colour when a texture is missing, so it degrades gracefully.

Not a Blender entry point — import it (``from scripts.ac import pbr``) and call ``setup_material``.
"""

from __future__ import annotations

from pathlib import Path

# name-prefix -> (diffuse, normal, roughness, fallback_rgba, metallic, water)
TEXTURES = {
    "1ROAD":   ("asphalt_diffuse.jpg", "asphalt_normal.jpg", 0.72, (0.08, 0.08, 0.09, 1), 0.0, False),
    "1KERB":   ("kerb_diffuse.png",    None,                 0.55, (0.62, 0.10, 0.08, 1), 0.0, False),
    "GRASS":   ("grass_diffuse.jpg",   "grass_normal.jpg",   0.95, (0.15, 0.33, 0.11, 1), 0.0, False),
    "HIGHWAY": ("asphalt_diffuse.jpg", "asphalt_normal.jpg", 0.80, (0.34, 0.34, 0.36, 1), 0.0, False),
    "WATER":   (None, None, 0.04, (0.02, 0.10, 0.20, 1), 0.0, True),
    "TREES":   (None, None, 0.90, (0.09, 0.25, 0.08, 1), 0.0, False),
    "LIGHTS":  (None, None, 0.40, (0.95, 0.82, 0.42, 1), 0.4, False),
}


def texture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "textures"


def setup_material(bpy, obj, tex_dir: Path | None = None):
    """Assign a Principled material (diffuse + normal from ``tex_dir``) to ``obj`` by name prefix.
    Returns the material so callers can stamp AC metadata (e.g. ``mat['shaderName']``) on it."""
    tex_dir = Path(tex_dir) if tex_dir else texture_dir()
    name = obj.name.upper()
    key = next((k for k in TEXTURES if name.startswith(k)), None)
    diff, norm, rough, color, metal, water = TEXTURES.get(
        key, (None, None, 0.8, (0.5, 0.5, 0.5, 1), 0.0, False))

    mat = bpy.data.materials.new(obj.name + "_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    dpath = tex_dir / diff if diff else None
    if dpath and dpath.exists():
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(dpath))
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.05 if water else rough
    bsdf.inputs["Metallic"].default_value = metal
    if water and "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = 0.4

    npath = tex_dir / norm if norm else None
    if npath and npath.exists():
        ntex = nt.nodes.new("ShaderNodeTexImage")
        nimg = bpy.data.images.load(str(npath))
        nimg.colorspace_settings.name = "Non-Color"
        ntex.image = nimg
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat
