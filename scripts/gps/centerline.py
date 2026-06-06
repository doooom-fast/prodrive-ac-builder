"""Build the centerline: order, dedupe, resample (~2–5 m), tag width, close the loop, name connectors.

Output: ``data/centerline.geojson`` — ordered lat/lon with per-vertex width + segment tags.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RESAMPLE_SPACING_M = 3.0  # target even spacing along the route (spec: ~2–5 m)


def order_and_dedupe(ways: list[dict[str, Any]], kml_segments: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Merge OSM ways + KML segments into one ordered, deduped lon/lat polyline."""
    raise NotImplementedError("Chain ways end-to-end, drop duplicate/overlapping nodes.")


def resample(points: list[tuple[float, float]], spacing_m: float = RESAMPLE_SPACING_M) -> list[tuple[float, float]]:
    """Resample the polyline to even ``spacing_m`` spacing (geodesic distance)."""
    raise NotImplementedError("Arc-length parametrize and resample at fixed spacing.")


def tag_widths(points: list[tuple[float, float]], default_width_m: float, overrides: list[dict[str, Any]]) -> list[float]:
    """Per-vertex width = default, with section overrides applied."""
    raise NotImplementedError("Apply width_overrides by segment range; else default_width_m.")


def build_centerline(project_dir: str | Path) -> Path:
    """Full step: config -> Overpass/KML -> order/resample/tag/stitch -> write centerline.geojson."""
    raise NotImplementedError(
        "Orchestrate overpass.fetch_ways + kml.parse_kml + order/resample/tag_widths; "
        "close loop if config.loop; emit connectors as named sub-paths; write GeoJSON."
    )
