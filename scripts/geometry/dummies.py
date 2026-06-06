"""Compute AC dummy object placements along the centerline.

Required by AC (see skill: ac-track-modding):
  AC_START_0..N, AC_PIT_0..N, AC_TIME_0_L/R (start-finish), AC_TIME_n_L/R (sectors), AC_HOTLAP_START_0
"""

from __future__ import annotations

from typing import Any


def place_dummies(
    centerline_m: list[tuple[float, float, float]],
    widths_m: list[float],
    n_sectors: int = 3,
    n_pits: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Return named dummy transforms (position + orientation) keyed by AC dummy name."""
    raise NotImplementedError(
        "Place AC_START/AC_TIME_0_L/R at start; AC_TIME_n_L/R at even sector splits; "
        "AC_HOTLAP_START_0 at start; AC_PIT_n along the pit spur."
    )
