"""curb_sidewalk cross-section: road/curb/sidewalk/grass meet at shared seam vertices (no hovering).

The profile is P points per station per side (5 without a ``ground`` sampler — lane edge, curb top,
sidewalk back, slope start, verge lip; 6 with one — the extra draped embankment/buried-hem point).
Tests derive P from the mesh instead of hard-coding it so the profile can grow without breaking the
seam/height invariants they actually guard.

Plain asserts so it runs under tests/run_tests.py and pytest.
"""

import math

from scripts.geometry import ribbon

LIFT = 0.1
CLEAR = 0.25


def _flat_line(length=200, step=5, width=9.0):
    cl = [(0.0, 0.0, float(z)) for z in range(0, length + 1, step)]
    return cl, [width] * len(cl)


def _stride(side, n_stations):
    p, rem = divmod(len(side["vertices"]), 2 * n_stations)
    assert rem == 0, "sidewalk verts must be an integer profile per station per side"
    return p


def test_road_and_curb_seam_is_coincident():
    cl, w = _flat_line()
    road = ribbon.road_ribbon(cl, w)
    road["vertices"] = [(x, y + LIFT, z) for x, y, z in road["vertices"]]   # build_mesh lifts the road
    side = ribbon.curb_sidewalk(cl, w, lift=LIFT, grass_clearance=CLEAR)
    m = len(road["vertices"]) // 2
    p = _stride(side, m)
    for i in range(m):
        road_left = road["vertices"][2 * i]      # left edge
        road_right = road["vertices"][2 * i + 1]  # right edge
        sw_left_inner = side["vertices"][i * p]                 # side +1, profile pt 0
        sw_right_inner = side["vertices"][(m + i) * p]          # side -1, profile pt 0
        assert math.dist(road_left, sw_left_inner) < 1e-9
        assert math.dist(road_right, sw_right_inner) < 1e-9


def test_grass_meet_matches_conform_target():
    # the verge profile point must sit at the height conform_terrain_to_road grades the grass to:
    # the road-edge SAMPLE height (centerline edge, no lift) minus the clearance.
    cl, w = _flat_line()
    side = ribbon.curb_sidewalk(cl, w, lift=LIFT, grass_clearance=CLEAR)
    p = _stride(side, len(cl))
    i = 10
    prof = [side["vertices"][i * p + q] for q in range(p)]
    road_edge_sample_y = 0.0          # flat centerline edge, no lift
    assert abs(prof[3][1] - (road_edge_sample_y - CLEAR)) < 1e-9   # slope start
    assert abs(prof[-1][1] - (road_edge_sample_y - CLEAR)) < 1e-9  # verge lip (no-ground fallback)
    # profile is monotonic outward and rises over the curb then steps down to grass
    offs = [abs(v[0]) for v in prof]
    assert all(offs[q] < offs[q + 1] for q in range(len(offs) - 1))
    assert prof[1][1] > prof[0][1]            # curb rises above the road
    assert abs(prof[2][1] - prof[1][1]) < 1e-9  # sidewalk is flat
    assert prof[3][1] < prof[2][1]            # grades down to grass


def test_curb_height_is_configurable():
    cl, w = _flat_line()
    side = ribbon.curb_sidewalk(cl, w, lift=LIFT, curb_h=0.20, grass_clearance=CLEAR)
    p = _stride(side, len(cl))
    prof = [side["vertices"][0 * p + q] for q in range(4)]
    assert abs((prof[1][1] - prof[0][1]) - 0.20) < 1e-9   # curb top is curb_h above the lane edge
    assert side["tris"]                                    # physical, non-empty
