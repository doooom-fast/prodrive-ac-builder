"""Material assignment for the AC Blender Tools addon.

Produces the material JSON / addon ``settings.json`` mapping mesh prefixes to AC shaders:
  1ROAD_* -> road shader, GRASS -> ksGrass, 1KERB_* -> kerb material.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def material_map(surfaces: dict[str, str]) -> dict[str, Any]:
    """Map surface roles (from config.surfaces) to AC shader assignments."""
    raise NotImplementedError("ksGrass for grass; road shader for 1ROAD_*; kerb material for 1KERB_*.")


def write_addon_settings(material_map: dict[str, Any], out_path: str | Path) -> Path:
    """Write the AC Blender Tools addon ``settings.json`` consumed during kn5 export."""
    raise NotImplementedError("Serialize material_map to the addon's settings.json schema.")
