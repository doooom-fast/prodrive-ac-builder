"""Map-matching a GPS drive onto OSM ways — scripts/gps/mapmatch.map_match.

Hermetic: synthetic OSM ways + a wobbly GPS track along them, no network. mapmatch needs numpy (the
vectorised snap); if it's absent these self-skip so the stdlib-only suite still passes.
"""

from __future__ import annotations

import math

try:
    from scripts.gps import mapmatch as mm
    import numpy  # noqa: F401
    HAVE = True
except Exception:
    HAVE = False

LAT0, LON0 = 39.78, -104.94


def _pt_line_dist_m(p, a, b):
    """Distance (m) from point p to segment a-b, all (lon,lat), local-flat."""
    kx = 111320 * math.cos(math.radians(LAT0)); ky = 110540
    px, py = (p[0] - LON0) * kx, (p[1] - LAT0) * ky
    ax, ay = (a[0] - LON0) * kx, (a[1] - LAT0) * ky
    bx, by = (b[0] - LON0) * kx, (b[1] - LAT0) * ky
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def test_snaps_wobbly_gps_onto_a_straight_way():
    if not HAVE:
        return
    # one OSM way running east ~850 m
    way = {"id": 1, "name": "Main St", "highway": "residential",
           "geom": [(LON0 + 0.0001 * i, LAT0) for i in range(100)]}
    # GPS along it with ~5 m lateral wobble
    gps = [(LON0 + 0.0001 * i, LAT0 + (0.00004 if i % 2 else -0.00004)) for i in range(2, 96)]
    out, stats = mm.map_match(gps, [way], max_snap_m=30, min_run=2)
    assert stats["matched_pct"] == 100.0
    assert stats["ways_used"] == 1
    # snapped output should lie ON the way (wobble removed): every point within ~1 m of the way line
    for p in out:
        assert _pt_line_dist_m(p, way["geom"][0], way["geom"][-1]) < 1.0


def test_picks_the_nearer_of_two_parallel_ways_and_ignores_blips():
    if not HAVE:
        return
    south = {"id": 1, "name": "A", "highway": "residential", "geom": [(LON0 + 0.0001 * i, LAT0) for i in range(60)]}
    north = {"id": 2, "name": "B", "highway": "residential", "geom": [(LON0 + 0.0001 * i, LAT0 + 0.002) for i in range(60)]}
    # drive clearly on the south road, with two single-fix jitters toward the north road (should be dropped)
    gps = []
    for i in range(5, 55):
        lat = LAT0 + (0.002 if i in (20, 38) else 0.00002)   # blips at 20, 38
        gps.append((LON0 + 0.0001 * i, lat))
    out, stats = mm.map_match(gps, [south, north], max_snap_m=40, min_run=4)
    assert stats["ways_used"] == 1                            # blips dropped -> one way
    for p in out:                                             # stays on the south road
        assert _pt_line_dist_m(p, south["geom"][0], south["geom"][-1]) < 2.0


def test_no_ways_returns_raw():
    if not HAVE:
        return
    gps = [(LON0 + 0.0001 * i, LAT0) for i in range(10)]
    out, stats = mm.map_match(gps, [])
    assert out == gps and stats["matched_pct"] == 0.0
