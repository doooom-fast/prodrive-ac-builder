"""Parse hand-drawn KML — used ONLY for segments where the route leaves the OSM network."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_kml(path: str | Path) -> list[dict[str, Any]]:
    """Parse KML LineStrings into named segments: [{"name": str, "coords": [(lon, lat), ...]}]."""
    raise NotImplementedError("Parse <Placemark>/<LineString>/<coordinates>; keep placemark name.")
