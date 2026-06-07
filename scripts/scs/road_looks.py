"""Phase S2 helper — parse ``def/world/road_look.sii`` into cross-sections for the ribbon sweep.

Each road in the map references a ``road_look`` template by name; the template defines the lane
layout (count, width, shoulder). We turn that into a ``CrossSection`` the existing ribbon sweeper
(``scripts/geometry/ribbon.py``) can extrude along the resampled centerline — the same way the GPS
pipeline turns ``default_width_m`` into a ribbon, but with the game's real cross-section.

``.sii`` is usually plaintext but can be encrypted/3nK-encoded; this parser handles plaintext and
flags the encrypted case (decrypt with TruckLib.Sii or SII_Decrypt upstream).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_UNIT_RE = re.compile(r"road_look\s*:\s*([^\s{]+)\s*\{(.*?)\}", re.DOTALL)
_ATTR_RE = re.compile(r"^\s*([\w.\[\]]+)\s*:\s*(.+?)\s*$", re.MULTILINE)


@dataclass
class CrossSection:
    """A drivable cross-section in meters, centered on the centerline."""

    name: str
    lanes_left: int = 1
    lanes_right: int = 1
    lane_width_m: float = 4.5
    shoulder_m: float = 0.0

    @property
    def total_width_m(self) -> float:
        return (self.lanes_left + self.lanes_right) * self.lane_width_m + 2 * self.shoulder_m


def parse_road_looks(asset_tree: Path) -> dict[str, CrossSection]:
    """Parse every ``road_look`` unit under ``def/world/`` into ``{name: CrossSection}``."""
    out: dict[str, CrossSection] = {}
    for sii in (asset_tree / "def" / "world").glob("road_look*.sii"):
        text = sii.read_text(encoding="utf-8", errors="replace")
        if text[:6] in ("ScsC", "\x00\x00\x00\x00") or "\x00" in text[:64]:
            raise ValueError(f"{sii} looks encrypted — decrypt upstream (TruckLib.Sii / SII_Decrypt)")
        for name, body in _UNIT_RE.findall(text):
            attrs = dict(_ATTR_RE.findall(body))
            out[name.strip('"')] = CrossSection(
                name=name.strip('"'),
                lanes_left=_int(attrs.get("lanes_left"), 1),
                lanes_right=_int(attrs.get("lanes_right"), 1),
                lane_width_m=_float(attrs.get("lane_width") or attrs.get("road_size_left"), 4.5),
                shoulder_m=_float(attrs.get("shoulder_size_right"), 0.0),
            )
    return out


def _int(value: str | None, default: int) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
