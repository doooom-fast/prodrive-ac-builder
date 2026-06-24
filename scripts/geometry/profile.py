"""Hand-authored elevation + camber drama layered on top of the real road.

The first principle holds for *route* (OSM/KML), but a personal track gets to sculpt how the road
*feels* — a dramatic dip, a corkscrew roll, a slight camber along a straight. This module turns the
``road_profile`` block of ``track.config.json`` into two cheap callables keyed by **lap station**
(metres along the centerline):

    dip_of(s)  -> metres to LOWER the centerline Y at station s (a smooth raised-cosine bell)
    bank_at(s) -> road roll in RADIANS at station s (+ve banks a RIGHT-hander: left/outside edge up)

Every swept generator (road ribbon, shoulder, kerbs, runoff, markings, crosswalk, painted names)
asks ``bank_at(station)`` for the roll at each vertex and adds ``offset * tan(bank)`` to its Y, so the
whole cross-section banks together. The dip is baked into the centerline before sweeping, so the
terrain grade, the grass conform and the dummies all follow it.

Config (stations are absolute metres along the lap; resolve them from data/street_labels.json):

  "road_profile": {
    "dips":    [ {"name":..., "center_m":3500, "len_m":160, "depth_m":4.0} ],
    "cambers": [ {"name":..., "start_m":3484, "len_m":70, "bank_deg":9, "ramp_m":20} ]
  }

Pure stdlib.
"""

from __future__ import annotations

import math
from typing import Callable


def _bell(s: float, center: float, length: float) -> float:
    """Raised-cosine bell in [0,1]: 0 at the edges, 1 at ``center``, width ``length``."""
    half = length / 2.0
    if half <= 0:
        return 0.0
    u = (s - center) / half          # -1 .. +1 across the bell
    if u <= -1.0 or u >= 1.0:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * u))


def _window(s: float, start: float, length: float, ramp: float) -> float:
    """Trapezoid with raised-cosine ramps in [0,1]: 0 -> 1 over ``ramp`` m, hold, 1 -> 0 over ``ramp``."""
    u = s - start
    if u <= 0.0 or u >= length:
        return 0.0
    ramp = max(1e-6, min(ramp, length / 2.0))
    if u < ramp:
        return 0.5 * (1.0 - math.cos(math.pi * u / ramp))
    if u > length - ramp:
        return 0.5 * (1.0 - math.cos(math.pi * (length - u) / ramp))
    return 1.0


def build_profile(road_profile: dict | None) -> tuple[Callable[[float], float], Callable[[float], float], bool]:
    """Return (dip_of, bank_at, active). ``active`` is False (and both callables are no-ops) when the
    config has no road_profile, so the flat pipeline is unchanged."""
    rp = road_profile or {}
    dips = rp.get("dips", []) or []
    cambers = rp.get("cambers", []) or []
    active = bool(dips or cambers)

    def dip_of(s: float) -> float:
        return sum(float(d.get("depth_m", 0.0)) * _bell(s, float(d["center_m"]), float(d["len_m"]))
                   for d in dips)

    def bank_at(s: float) -> float:
        deg = sum(float(c.get("bank_deg", 0.0)) *
                  _window(s, float(c["start_m"]), float(c["len_m"]), float(c.get("ramp_m", 15.0)))
                  for c in cambers)
        return math.radians(deg)

    return dip_of, bank_at, active
