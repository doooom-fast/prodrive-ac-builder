"""Synthetic GENTLE elevation for the FICTIONAL K10 inter-track world.

The tracks sit at FABRICATED compressed positions, so sampling real USGS 3DEP across the inter-track
space manufactures fake ~150 m climbs and garbage cells (a reservoir once floated to 23 km — see
network_elev history). Instead, define ONE gentle field: a plane that rises gently toward the far-WEST
Front Range (user: "a gentle slope TOWARD them"), so the tracks, the connectors, and the ground all
share a single consistent, drivable elevation. Each track keeps its OWN internal relief (built in its
own frame by the loop/aerial pipeline); this field only decides where each track's pad SITS in Y.

Consumed by: network_elev (connector road z + heightfield), merge_detailed (per-track seat height),
build_network_env (water + scatter seating via the field-derived heightfield). Pure stdlib; runs on
system python3. Only active when scenery.elevation.synthetic is truthy (other projects keep real 3DEP).
"""
from __future__ import annotations

from pathlib import Path

from scripts.config import load_config
from scripts.geometry.projection import _meters_per_degree

BLEND_M = 3000.0   # each track's base nudges the ground within ~this radius (low curvature -> no undulation)


def enabled(cfg) -> bool:
    return bool(((cfg.raw.get("scenery", {}) or {}).get("elevation", {}) or {}).get("synthetic", False))


def _origin(cfg):
    og = cfg.raw["origin"]
    return float(og["lon"]), float(og["lat"]), float(og["elev_m"])


def projector(cfg):
    """lon/lat -> K10 LOCAL (x, z) metres, matching build_network_mesh / merge_detailed (mirror-aware).
    Under mirror_x, +x = true WEST, so the plane rises with +x toward the western mountains."""
    lon0, lat0, _ = _origin(cfg)
    m_lon, m_lat = _meters_per_degree(lat0)
    sx = -1.0 if cfg.raw.get("mirror_x", True) else 1.0

    def to_xz(lon, lat):
        return (sx * (lon - lon0) * m_lon, (lat - lat0) * m_lat)
    return to_xz


def _params(cfg):
    el = (cfg.raw.get("scenery", {}) or {}).get("elevation", {}) or {}
    return (float(el.get("datum_base_m", 18.0)),
            float(el.get("west_rise_per_km_m", 1.25)),
            el.get("per_track_override", {}) or {})


def plane_y(cfg, x: float) -> float:
    """Gentle base height (m above the origin datum) at local x. +x = WEST -> rises toward the mountains."""
    datum, rise, _ = _params(cfg)
    return datum + rise * (x / 1000.0)


def resolve_track_bases(k10_dir) -> dict:
    """{slug: base_y_m} — each track's chosen gentle base height = the plane at its pad centre, unless
    scenery.elevation.per_track_override pins it. Small total spread (gentle) vs the 190 m real-3DEP spread."""
    k10 = Path(k10_dir); cfg = load_config(k10)
    from scripts.ac.merge_detailed import track_footprints
    _, _, ov = _params(cfg)
    pads = track_footprints(k10)
    return {slug: (float(ov[slug]) if slug in ov else plane_y(cfg, p["cx"])) for slug, p in pads.items()}


def make_field(k10_dir):
    """Return (field_local, to_xz, elev0):
       field_local(x, z) -> intended GROUND height (m above elev0) anywhere in the inter-track world;
       to_xz(lon, lat)   -> K10 local (x, z);
       elev0             -> origin datum, so callers can emit ABSOLUTE z = field_local + elev0.
    A gentle west-rising plane, nudged toward each track's chosen base within BLEND_M so the ground under a
    pad matches the track's seat, blending smoothly (low curvature) so connectors never undulate."""
    k10 = Path(k10_dir); cfg = load_config(k10)
    to_xz = projector(cfg); _, _, elev0 = _origin(cfg)
    from scripts.ac.merge_detailed import track_footprints
    pads = track_footprints(k10)
    bases = resolve_track_bases(k10)
    R2 = BLEND_M * BLEND_M
    anchors = [(pads[s]["cx"], pads[s]["cz"], bases[s] - plane_y(cfg, pads[s]["cx"])) for s in bases]

    def field_local(x, z):
        base = plane_y(cfg, x)
        num = den = 0.0
        for ax, az, dev in anchors:                 # dev = pad's departure from the plane (0 unless overridden)
            w = R2 / (R2 + (x - ax) ** 2 + (z - az) ** 2)   # 1 at the pad, ->0 far, smooth
            num += w * dev; den += w
        return base + (num / den if den else 0.0)
    return field_local, to_xz, elev0
