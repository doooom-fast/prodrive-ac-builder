"""Material database — one table drives both Blender preview materials and the kn5 export.

Maps a mesh-name prefix to its texture set (under ``assets/textures/generated/``, produced by
``texgen.py``), its AC shader + shader properties, and its alpha mode. ``setup_material`` builds
the Blender Principled material (preview/flythrough renders); ``kn5_native.py`` reads the same
rows to write the exporter's ``settings.json`` and stage textures into ``build/texture/``.

ORDER MATTERS for prefix matching (first ``startswith`` hit wins) — keep longer/more-specific
prefixes above their shorter cousins (GUARDPOST before GUARD, MARKYELLOW before MARKINGS).
"""

from __future__ import annotations

from pathlib import Path

# prefix -> row; every texture lives in assets/textures/generated/ (texgen.py output)
#   diff/norm: file names (or None)
#   rough/metal/color: Blender preview hints
#   shader: AC shader; props: AC shader properties; alpha: None | "test" | "blend"
#   emissive: AC ksEmissive RGB (also hinted in Blender)
#   shadows: cast shadows (kn5 node flag)
MATS: dict[str, dict] = {
    "1ROAD":     dict(diff="road_diffuse.png", norm="road_normal.png", rough=0.74,
                      color=(0.13, 0.13, 0.14, 1), shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.16, ksSpecularEXP=28)),
    "HIGHWAY":   dict(diff="road_diffuse.png", norm="road_normal.png", rough=0.78,
                      color=(0.30, 0.30, 0.33, 1), shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.10, ksSpecularEXP=20)),
    "WEAR":      dict(diff="road_wear.png", rough=0.60, color=(0.05, 0.05, 0.06, 1),
                      shader="ksPerPixel", alpha="blend", shadows=False,
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.22, ksSpecularEXP=40)),
    "1KERB":     dict(diff="kerb_diffuse.png", norm="kerb_normal.png", rough=0.55,
                      color=(0.62, 0.10, 0.08, 1), shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.50, ksSpecular=0.25, ksSpecularEXP=32)),
    "MARKYELLOW": dict(diff="paint_yellow.png", rough=0.5, color=(0.85, 0.65, 0.10, 1),
                       shader="ksPerPixel", shadows=False,
                       props=dict(ksAmbient=0.5, ksDiffuse=0.5, ksSpecular=0.3, ksSpecularEXP=36)),
    "MARKINGS":  dict(diff="paint_white.png", rough=0.5, color=(0.88, 0.88, 0.85, 1),
                      shader="ksPerPixel", shadows=False,
                      props=dict(ksAmbient=0.5, ksDiffuse=0.5, ksSpecular=0.3, ksSpecularEXP=36)),
    "CROSSWALK": dict(diff="paint_white.png", rough=0.5, color=(0.88, 0.88, 0.85, 1),
                      shader="ksPerPixel", shadows=False,
                      props=dict(ksAmbient=0.5, ksDiffuse=0.5, ksSpecular=0.3, ksSpecularEXP=36)),
    "1GRASS":    dict(diff="grass_diffuse.png", norm="grass_normal.png", rough=0.95,
                      color=(0.15, 0.33, 0.11, 1), shader="ksGrass",
                      props=dict(ksAmbient=0.5, ksDiffuse=0.45, ksSpecular=0.0, ksSpecularEXP=1)),
    "GRASS":     dict(diff="grass_diffuse.png", norm="grass_normal.png", rough=0.95,
                      color=(0.15, 0.33, 0.11, 1), shader="ksGrass",
                      props=dict(ksAmbient=0.5, ksDiffuse=0.45, ksSpecular=0.0, ksSpecularEXP=1)),
    "RAILBED":   dict(diff="gravel_diffuse.png", rough=0.95, color=(0.36, 0.33, 0.30, 1),
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.5, ksDiffuse=0.45, ksSpecular=0.02, ksSpecularEXP=8)),
    "RAILS":     dict(diff="steel_dark.png", rough=0.35, color=(0.25, 0.26, 0.28, 1), metal=0.6,
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.4, ksDiffuse=0.4, ksSpecular=0.6, ksSpecularEXP=48)),
    "ROOFS":     dict(diff="roof_flat.png", norm="roof_flat_n.png", rough=0.85,
                      color=(0.40, 0.40, 0.42, 1), shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.48, ksDiffuse=0.46, ksSpecular=0.05, ksSpecularEXP=12)),
    "HWCONC":    dict(diff="concrete_diffuse.png", norm="concrete_normal.png", rough=0.80,
                      color=(0.58, 0.58, 0.56, 1), shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.48, ksDiffuse=0.48, ksSpecular=0.08, ksSpecularEXP=16)),
    "PIERS":     dict(diff="concrete_diffuse.png", norm="concrete_normal.png", rough=0.80,
                      color=(0.56, 0.56, 0.54, 1), shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.48, ksDiffuse=0.48, ksSpecular=0.08, ksSpecularEXP=16)),
    "1WALL":     dict(diff="concrete_diffuse.png", norm="concrete_normal.png", rough=0.78,
                      color=(0.62, 0.62, 0.60, 1), shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.48, ksDiffuse=0.48, ksSpecular=0.10, ksSpecularEXP=18)),
    "TANKS":     dict(diff="tank_metal.png", norm="tank_metal_n.png", rough=0.55,
                      color=(0.74, 0.73, 0.69, 1), metal=0.25, shader="ksPerPixelNM",
                      props=dict(ksAmbient=0.46, ksDiffuse=0.48, ksSpecular=0.28, ksSpecularEXP=30)),
    "TREES":     dict(diff="tree_atlas.png", rough=0.90, color=(0.13, 0.30, 0.11, 1),
                      shader="ksTree", alpha="test", shadows=True,
                      props=dict(ksAmbient=0.55, ksDiffuse=0.45, ksSpecular=0.0, ksSpecularEXP=1,
                                 ksAlphaRef=0.45)),
    "BUSH":      dict(diff="tree_atlas.png", rough=0.90, color=(0.25, 0.32, 0.14, 1),
                      shader="ksTree", alpha="test", shadows=False,
                      props=dict(ksAmbient=0.55, ksDiffuse=0.45, ksSpecular=0.0, ksSpecularEXP=1,
                                 ksAlphaRef=0.45)),
    "FENCE":     dict(diff="fence_chain.png", rough=0.55, color=(0.55, 0.56, 0.58, 1), metal=0.4,
                      shader="ksPerPixelAT", alpha="test", shadows=False,
                      props=dict(ksAmbient=0.5, ksDiffuse=0.45, ksSpecular=0.4, ksSpecularEXP=32,
                                 ksAlphaRef=0.4)),
    "SIGNFACE":  dict(diff="signs_atlas.png", rough=0.40, color=(0.8, 0.8, 0.78, 1),
                      shader="ksPerPixelAT", alpha="test", shadows=False,
                      props=dict(ksAmbient=0.55, ksDiffuse=0.5, ksSpecular=0.3, ksSpecularEXP=36,
                                 ksAlphaRef=0.5)),
    "ADFACE":    dict(diff="adboards.png", rough=0.55, color=(0.2, 0.2, 0.25, 1),
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.55, ksDiffuse=0.5, ksSpecular=0.15, ksSpecularEXP=24)),
    "HORIZON":   dict(diff="horizon.png", rough=1.0, color=(0.55, 0.60, 0.70, 1),
                      shader="ksPerPixelAT", alpha="test", shadows=False,
                      props=dict(ksAmbient=0.9, ksDiffuse=0.10, ksSpecular=0.0, ksSpecularEXP=1,
                                 ksAlphaRef=0.3)),
    "GANTRYSTEEL": dict(diff="pole_steel.png", rough=0.45, color=(0.55, 0.57, 0.60, 1), metal=0.5,
                        shader="ksPerPixel",
                        props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.45, ksSpecularEXP=40)),
    "SIGNPOST":  dict(diff="pole_steel.png", rough=0.45, color=(0.55, 0.57, 0.60, 1), metal=0.5,
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.45, ksSpecularEXP=40)),
    "POLES":     dict(diff="pole_steel.png", rough=0.45, color=(0.55, 0.57, 0.60, 1), metal=0.5,
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.45, ksSpecularEXP=40)),
    "PYLON":     dict(diff="pole_steel.png", rough=0.5, color=(0.5, 0.52, 0.55, 1), metal=0.5,
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.4, ksSpecularEXP=32)),
    "WOODPOLE":  dict(diff="pole_wood.png", rough=0.85, color=(0.38, 0.29, 0.21, 1),
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.48, ksDiffuse=0.48, ksSpecular=0.05, ksSpecularEXP=12)),
    "WIRES":     dict(diff="steel_dark.png", rough=0.5, color=(0.12, 0.12, 0.13, 1),
                      shader="ksPerPixel", shadows=False,
                      props=dict(ksAmbient=0.4, ksDiffuse=0.4, ksSpecular=0.2, ksSpecularEXP=20)),
    "TRAFSIG":   dict(diff="steel_dark.png", rough=0.6, color=(0.15, 0.16, 0.17, 1),
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.25, ksSpecularEXP=28)),
    "GUARDPOST": dict(diff="pole_steel.png", rough=0.5, color=(0.5, 0.52, 0.55, 1), metal=0.4,
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.4, ksSpecularEXP=36)),
    "GUARD":     dict(diff="guardrail.png", rough=0.40, color=(0.60, 0.62, 0.65, 1), metal=0.6,
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.55, ksSpecularEXP=44)),
    "TIRES":     dict(diff="tirewall.png", rough=0.92, color=(0.08, 0.08, 0.09, 1),
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.45, ksDiffuse=0.45, ksSpecular=0.08, ksSpecularEXP=10)),
    "LIGHTS":    dict(diff="lamp_warm.png", rough=0.4, color=(0.95, 0.82, 0.42, 1),
                      shader="ksPerPixel", emissive=(1.4, 1.15, 0.65),
                      props=dict(ksAmbient=0.5, ksDiffuse=0.4, ksSpecular=0.3, ksSpecularEXP=24,
                                 ksEmissive=(1.4, 1.15, 0.65))),
    "WATER":     dict(diff="water_calm.png", rough=0.05, color=(0.02, 0.10, 0.20, 1), water=True,
                      shader="ksPerPixel",
                      props=dict(ksAmbient=0.5, ksDiffuse=0.35, ksSpecular=0.9, ksSpecularEXP=120)),
}

# building facade variant families (texgen's facade factory): BUILDIN#/BUILDCM#/BUILDOF#/BUILDRS#.
# Registered up to 8 per family (single digit keeps prefix matching unambiguous); the build only
# references the indices texgen actually wrote (manifest.json "facades" counts).
_FACADE_FAMILIES = {
    "IN": ("fac_ind_{i}", dict(rough=0.78, color=(0.56, 0.54, 0.50, 1), spec=0.12, exp=24)),
    "CM": ("fac_com_{i}", dict(rough=0.80, color=(0.52, 0.40, 0.33, 1), spec=0.10, exp=20)),
    "OF": ("fac_off_{i}", dict(rough=0.45, color=(0.48, 0.51, 0.54, 1), spec=0.32, exp=40)),
    "RS": ("fac_res_{i}", dict(rough=0.82, color=(0.66, 0.63, 0.56, 1), spec=0.08, exp=16)),
}
for _fam, (_stem, _hint) in _FACADE_FAMILIES.items():
    for _i in range(8):
        MATS[f"BUILD{_fam}{_i}"] = dict(
            diff=_stem.format(i=_i) + ".png", norm=_stem.format(i=_i) + "_n.png",
            rough=_hint["rough"], color=_hint["color"], shader="ksPerPixelNM",
            props=dict(ksAmbient=0.48, ksDiffuse=0.48, ksSpecular=_hint["spec"],
                       ksSpecularEXP=_hint["exp"]))

# materials drawn as alpha-cutout in the Blender preview — wire texture alpha + clip
BILLBOARD = {k for k, v in MATS.items() if v.get("alpha") == "test"}

# legacy view used by older callers: prefix -> (diffuse, normal, rough, fallback, metal, water)
TEXTURES = {k: (v.get("diff"), v.get("norm"), v.get("rough", 0.8), v.get("color", (0.5, 0.5, 0.5, 1)),
                v.get("metal", 0.0), bool(v.get("water"))) for k, v in MATS.items()}


def texture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "textures" / "generated"


def lookup(name: str) -> dict | None:
    up = name.upper()
    for k, row in MATS.items():
        if up.startswith(k):
            return row
    return None


def setup_material(bpy, obj, tex_dir: Path | None = None):
    """Assign a Principled material (diffuse + normal from ``tex_dir``) to ``obj`` by name prefix.
    Returns the material so callers can stamp AC metadata (e.g. ``mat['shaderName']``) on it."""
    tex_dir = Path(tex_dir) if tex_dir else texture_dir()
    row = lookup(obj.name) or dict(rough=0.8, color=(0.5, 0.5, 0.5, 1))
    diff, norm = row.get("diff"), row.get("norm")
    rough, color, metal = row.get("rough", 0.8), row.get("color", (0.5, 0.5, 0.5, 1)), row.get("metal", 0.0)

    mat = bpy.data.materials.new(obj.name + "_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    dpath = tex_dir / diff if diff else None
    if dpath and dpath.exists():
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(dpath), check_existing=True)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if row.get("alpha") == "test":  # cutout: wire alpha + clip the transparent background
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            for attr, val in (("blend_method", "CLIP"), ("shadow_method", "CLIP"),
                              ("surface_render_method", "DITHERED")):
                try:
                    setattr(mat, attr, val)
                except Exception:
                    pass
        elif row.get("alpha") == "blend":
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            for attr, val in (("blend_method", "BLEND"), ("surface_render_method", "BLENDED")):
                try:
                    setattr(mat, attr, val)
                except Exception:
                    pass
    else:
        bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.05 if row.get("water") else rough
    bsdf.inputs["Metallic"].default_value = metal
    if row.get("emissive") and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = (*[min(1.0, c) for c in row["emissive"]], 1.0)
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 2.0
    if row.get("water") and "Transmission Weight" in bsdf.inputs:
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
