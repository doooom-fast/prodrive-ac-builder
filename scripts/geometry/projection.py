"""Project lat/lon/elev -> local meters about an origin, in AC's Y-up frame.

Origin is set by config (default = centerline centroid). Do the lon/lat -> meters conversion here,
once, then keep everything metric and Y-up downstream.
"""

from __future__ import annotations

from typing import Any


def centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Mean lon/lat of the centerline — the default projection origin."""
    raise NotImplementedError("Return (mean_lon, mean_lat).")


def project_to_local(
    lonlat: list[tuple[float, float]],
    z: list[float],
    origin: tuple[float, float],
) -> list[tuple[float, float, float]]:
    """Project (lon, lat) + elevation to local meters about ``origin`` in Y-up.

    Returns (x_east, y_up, z_north)-style coords consistent with the AC/kn5 convention.
    """
    raise NotImplementedError(
        "Use pyproj (UTM or azimuthal-equidistant about origin) for lon/lat->meters; map up-axis to Y."
    )
