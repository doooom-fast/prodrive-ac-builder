"""Fetch a DEM for the track region. Source priority: USGS 3DEP 1 m -> OpenTopography -> SRTM 30 m.

USGS 3DEP 1 m is primary for US locations (Commerce City). Falls back when coverage is missing.
"""

from __future__ import annotations

from pathlib import Path

# USGS 3DEP dynamic services (1 m / 1/3 arc-second) — see The National Map.
USGS_3DEP_IMAGE_SERVER = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"


def fetch_dem(bbox: tuple[float, float, float, float], out_path: str | Path) -> Path:
    """Download a DEM GeoTIFF covering ``bbox`` (south, west, north, east) to ``out_path``.

    Try USGS 3DEP 1 m first; fall back to OpenTopography, then SRTM 30 m on failure/no coverage.
    """
    raise NotImplementedError("Request 3DEP ImageServer exportImage (GeoTIFF); fallbacks on miss.")
