"""Centerline smoothing must not join the two ends of an open road.

smooth_centerline and round_sharp_corners both indexed neighbours with `% m` unconditionally. On a
closed lap that's correct. On an open road it means vertex 0 averages against the LAST vertex — so
the ends get dragged toward each other every iteration. On the 25 km Dragon Tail stage that inflated
the swept route from 25.2 km to 37.7 km and pulled endpoints 17.7 km apart down to 5.1 km.
"""

import math

from scripts.geometry import build_mesh


def _length(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2])
               for i in range(len(pts) - 1))


def _long_open_road(n=800, length=20000.0):
    """A straight-ish open road with small lateral wobble — the shape a resampled OSM way has."""
    step = length / (n - 1)
    return [(i * step, 0.0, 4.0 * math.sin(i * 0.7)) for i in range(n)]


def test_open_road_keeps_its_length_and_its_endpoints():
    pts = _long_open_road()
    before_len = _length(pts)
    out = build_mesh.round_sharp_corners(build_mesh.smooth_centerline(pts))
    assert len(out) == len(pts)
    # endpoints pinned exactly — they are real places in the world (the start line and the finish)
    assert math.isclose(out[0][0], pts[0][0], abs_tol=1e-9)
    assert math.isclose(out[-1][0], pts[-1][0], abs_tol=1e-9)
    # smoothing may shorten slightly by removing wobble, but must never inflate the route
    assert _length(out) <= before_len + 1.0
    assert _length(out) > before_len * 0.9


def test_open_road_ends_do_not_migrate_toward_each_other():
    pts = _long_open_road()
    sep_before = math.hypot(pts[0][0] - pts[-1][0], pts[0][2] - pts[-1][2])
    out = build_mesh.round_sharp_corners(build_mesh.smooth_centerline(pts))
    sep_after = math.hypot(out[0][0] - out[-1][0], out[0][2] - out[-1][2])
    assert math.isclose(sep_after, sep_before, rel_tol=1e-6)


def test_open_road_interior_is_still_smoothed():
    # The fix must not turn smoothing OFF — only stop it wrapping. Four Laplacian passes at lam=0.45
    # take roughly a third out of this wobble; the assertion just has to be well clear of "unchanged".
    pts = _long_open_road()
    out = build_mesh.smooth_centerline(pts)
    rough = lambda P: sum(abs(P[i - 1][2] - 2 * P[i][2] + P[i + 1][2]) for i in range(1, len(P) - 1))
    assert rough(out) < rough(pts) * 0.75


def test_closed_loop_still_wraps():
    n = 400
    r = 500.0
    ring = [(r * math.cos(2 * math.pi * i / n), 0.0, r * math.sin(2 * math.pi * i / n))
            for i in range(n)]
    ring.append(ring[0])                      # explicitly closed
    out = build_mesh.smooth_centerline(ring)
    assert len(out) == len(ring)
    assert out[0] == out[-1]                  # still closed
    # every vertex moved (a wrapped smoother has no fixed endpoints on a ring)
    assert not math.isclose(out[0][0], ring[0][0], abs_tol=1e-12)
