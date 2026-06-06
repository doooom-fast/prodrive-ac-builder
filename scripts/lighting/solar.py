"""Solar azimuth/elevation for the track location (lat/lon/timezone from config)."""

from __future__ import annotations

from typing import Any


def solar_position(lat: float, lon: float, when_iso: str, timezone: str) -> tuple[float, float]:
    """Return (azimuth_deg, elevation_deg) of the sun at ``when_iso`` for the given site."""
    raise NotImplementedError("Use astral.sun (or pvlib) with lat/lon/tz; return azimuth, elevation.")
