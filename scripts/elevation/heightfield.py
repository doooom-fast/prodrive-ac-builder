"""Sample the DEM along the centerline (+ margin grid) and emit a smoothed heightfield.

Smooth aggressively ALONG the racing line to avoid stepping; keep the margin grid natural for grass.
Outputs centerline z-values and ``data/heightfield.npy``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MARGIN_M = 120.0  # terrain grid margin around the centerline bbox


def sample_along_path(dem_path: str | Path, points: list[tuple[float, float]]) -> list[float]:
    """Bilinear-sample DEM elevation at each centerline lon/lat point -> z-values (meters)."""
    raise NotImplementedError("rasterio.open(dem); sample at projected coords; bilinear interp.")


def build_heightfield(dem_path: str | Path, bbox: tuple[float, float, float, float], out_path: str | Path) -> Path:
    """Build a regular terrain grid over bbox+MARGIN and save to ``data/heightfield.npy``."""
    raise NotImplementedError("Resample DEM to a regular grid over bbox+MARGIN; np.save.")


def smooth_racing_line(z: list[float], window_m: float = 40.0) -> list[float]:
    """Smooth centerline elevation along arc length to remove DEM stepping."""
    raise NotImplementedError("Savitzky-Golay / Gaussian over arc length (scipy.signal/ndimage).")
