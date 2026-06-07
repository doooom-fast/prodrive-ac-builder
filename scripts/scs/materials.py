"""Phase S4 — map SCS materials (.mat → .tobj → .dds) to Assetto Corsa materials.

SCS ``.mat`` files name a shader (e.g. ``eut2.dif.spec``) and reference textures via ``.tobj``
descriptors that point at ``.dds`` files. AC reads DDS directly, so textures are reused as-is; the
work is mapping SCS shaders to AC ``ks*`` shaders and emitting the material description that
``scripts/ac/materials.py`` turns into the AC Blender Tools ``settings.json``.

This module owns the SCS-specific knowledge (shader map, .mat/.tobj parsing). The downstream AC
material writer stays the single place that knows AC's JSON schema.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# SCS shader family (matched as a prefix) → AC shader. Lossy by design; refine per-track.
SCS_TO_AC_SHADER: dict[str, str] = {
    "eut2.dif.spec.weight.mult2": "ksPerPixelMultiMap",
    "eut2.dif.spec": "ksPerPixel",
    "eut2.dif": "ksPerPixel",
    "eut2.road": "ksMultilayer",  # road blends → multilayer; refine to a road shader if used
    "eut2.grass": "ksGrass",
    "eut2.vegetation": "ksTree",
    "eut2.building": "ksPerPixel",
    "eut2.glass": "ksPerPixel_AT",  # alpha
}
_DEFAULT_AC_SHADER = "ksPerPixel"

_TOKEN_RE = re.compile(r'(\w[\w.]*)\s*:\s*"?([^"\n]+?)"?\s*$', re.MULTILINE)


def map_shader(scs_shader: str) -> str:
    """Map an SCS shader name to an AC shader by longest matching prefix."""
    for prefix in sorted(SCS_TO_AC_SHADER, key=len, reverse=True):
        if scs_shader.startswith(prefix):
            return SCS_TO_AC_SHADER[prefix]
    return _DEFAULT_AC_SHADER


def resolve_tobj(tobj_path: Path) -> str | None:
    """Read a (plaintext) ``.tobj`` and return the ``.dds`` path it points at, if parseable."""
    if not tobj_path.exists():
        return None
    for line in tobj_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("map") and line.endswith(".dds"):
            return line.split()[-1]
        if line.endswith(".dds"):
            return line
    return None  # binary .tobj — resolve with TruckLib.Models upstream


def build_materials(mat_paths: list[Path], asset_tree: Path, dest: Path) -> Path:
    """Parse ``.mat`` files → an intermediate ``materials.json`` for ``scripts/ac/materials.py``."""
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / "materials.json"
    materials = []
    for mat in mat_paths:
        attrs = dict(_TOKEN_RE.findall(mat.read_text(encoding="utf-8", errors="replace")))
        scs_shader = attrs.get("effect", attrs.get("shader", ""))
        tex_ref = attrs.get("texture") or attrs.get("texture_name")
        dds = resolve_tobj(asset_tree / tex_ref) if tex_ref else None
        materials.append(
            {
                "name": mat.stem,
                "ac_shader": map_shader(scs_shader),
                "scs_shader": scs_shader,
                "textures": {"txDiffuse": dds} if dds else {},
            }
        )
    out_path.write_text(json.dumps({"materials": materials}, indent=2) + "\n", encoding="utf-8")
    return out_path
