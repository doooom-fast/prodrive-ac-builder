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
    "1ROAD":   ("asphalt_cracked_diffuse.jpg", "asphalt_cracked_normal.jpg", 0.80, (0.10, 0.10, 0.11, 1), 0.0, False),  # cracked/alligator asphalt (LA Canyons lac_tarmac_cracked)
    "1RUNOFF": ("asphalt_cracked_diffuse.jpg", "asphalt_cracked_normal.jpg", 0.85, (0.16, 0.15, 0.14, 1), 0.0, False),
    "CALIB":   (None, None, 0.4, (1.0, 0.05, 0.6, 1), 0.9, False),  # bright emissive magenta — temp orientation poles
    "1KERB":   ("kerb_diffuse.png",    None,                 0.55, (0.62, 0.10, 0.08, 1), 0.0, False),
    "MARKINGS": (None, None, 0.45, (0.88, 0.88, 0.85, 1), 0.0, False),  # white lane lines + crosswalk (shape = geometry)
    "ROADTEXT": ("roadtext_atlas.png", None, 0.5, (0.92, 0.92, 0.90, 1), 0.0, False),  # painted street-name decals (alpha cutout)
    "1GRASS":  ("ground_dry_diffuse.jpg", None,              0.95, (0.42, 0.38, 0.29, 1), 0.0, False),  # dry dirt/prairie (LA Canyons lac_dirt_ground)
    "BUSHES":  ("bushes_atlas.png", None, 0.9, (0.36, 0.37, 0.24, 1), 0.0, False),  # dry scrub billboards (LA Canyons bo_bushes_11)
    "HIGHWAY": ("asphalt_cracked_diffuse.jpg", "asphalt_cracked_normal.jpg", 0.80, (0.30, 0.30, 0.32, 1), 0.0, False),  # I-70 deck
    "HWYSTRUCT": ("building_diffuse.jpg", "building_normal.jpg", 0.85, (0.68, 0.68, 0.66, 1), 0.0, False),  # concrete parapets/piers
    "BUILDING": ("building_diffuse.jpg", "building_normal.jpg", 0.85, (0.55, 0.52, 0.48, 1), 0.0, False),
    "WAREHOUSE": ("roof_diffuse.jpg", "roof_normal.jpg", 0.70, (0.60, 0.62, 0.65, 1), 0.0, False),  # corrugated-metal warehouse walls (industrial)
    "BARRIER": ("building_diffuse.jpg", "building_normal.jpg", 0.85, (0.74, 0.74, 0.72, 1), 0.0, False),  # concrete jersey K-rail
    "ROOF":    ("roof_diffuse.jpg",    "roof_normal.jpg",    0.70, (0.40, 0.40, 0.42, 1), 0.10, False),
    "WATER":   (None, None, 0.04, (0.02, 0.10, 0.20, 1), 0.0, True),
    "TREES":   ("tree_diffuse.png", None, 0.90, (0.13, 0.30, 0.11, 1), 0.0, False),
    "LIGHTS":  (None, None, 0.40, (0.95, 0.82, 0.42, 1), 0.4, False),
    "SIGNS":   ("signs_atlas.png", None, 0.55, (0.12, 0.40, 0.18, 1), 0.0, False),  # green street-name panels
    "MOUNTAINS": (None, None, 0.95, (0.52, 0.57, 0.66, 1), 0.0, False),  # hazy blue Front Range backdrop (flat silhouette)
    "SIGNPOST": (None, None, 0.60, (0.45, 0.46, 0.48, 1), 0.0, False),              # grey metal posts
}

# materials drawn as alpha-cutout — wire the texture alpha + clip the transparent bg (trees as
# billboards; painted street names as flat road decals). The export addon also reads this set to set
# ALPHATEST=1 on these materials so the kn5 cuts out the transparent background in-engine.
BILLBOARD = {"TREES", "ROADTEXT", "BUSHES"}


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
        tex.image = bpy.data.images.load(str(dpath), check_existing=True)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if key in BILLBOARD:  # cutout billboard: wire alpha + clip the transparent background
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            for attr, val in (("blend_method", "CLIP"), ("shadow_method", "CLIP"),
                              ("surface_render_method", "DITHERED")):
                try:
                    setattr(mat, attr, val)
                except Exception:
                    pass
    else:
        bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.05 if water else rough
    bsdf.inputs["Metallic"].default_value = metal
    if water and "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = 0.4

    npath = tex_dir / norm if norm else None
    if npath and npath.exists():
        ntex = nt.nodes.new("ShaderNodeTexImage")
        nimg = bpy.data.images.load(str(npath), check_existing=True)
        nimg.colorspace_settings.name = "Non-Color"
        ntex.image = nimg
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat
