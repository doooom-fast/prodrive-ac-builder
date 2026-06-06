"""Overpass API queries: fetch road ways for the route by bounding box + road names.

The map screenshot is only a selection aid — this is where real geometry enters the pipeline.
"""

from __future__ import annotations

from typing import Any

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def build_query(bbox: tuple[float, float, float, float], road_names: list[str]) -> str:
    """Build an Overpass QL query for the given bbox (south, west, north, east) and road names."""
    raise NotImplementedError("Build the Overpass QL: way[highway][name~...](bbox); out geom;")


def fetch_ways(bbox: tuple[float, float, float, float], road_names: list[str]) -> list[dict[str, Any]]:
    """Run the Overpass query and return ways as ordered lat/lon node lists with tags."""
    raise NotImplementedError("POST build_query() to OVERPASS_URL; parse JSON 'elements'.")
