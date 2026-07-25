"""Point-to-point (loop=false) timing geometry — a rally stage, not a lap.

The failure these pin down is subtle and only shows up in-game: on an open road the loop code wraps
sector gates modulo the lap length, so a gate meant for 2/3 distance lands back near the start,
behind the driver, and the run can never be timed. Here the finish must be at the far END and every
gate must sit between start and finish, in driving order.
"""

import math

from scripts.geometry import dummies


def _straight_road(length_m=3000.0, n=301):
    """A straight open road along +X, 6 m wide, flat."""
    step = length_m / (n - 1)
    pts = [(i * step, 0.0, 0.0) for i in range(n)]
    return pts, [6.0] * n


def _arc_of(pts, p):
    """Distance along the road (it runs along +X) of a placed dummy."""
    return p[0]


def test_finish_is_at_the_far_end_not_next_to_the_grid():
    pts, w = _straight_road()
    d = dummies.place_dummies(pts, w, n_sectors=3, loop=False)
    start = _arc_of(pts, d["AC_START_0"])
    finish = (_arc_of(pts, d["AC_TIME_0_L"]) + _arc_of(pts, d["AC_TIME_0_R"])) / 2
    assert finish > 2900.0, "AC_TIME_0 must be the finish, at the end of the stage"
    assert finish - start > 2800.0


def test_sector_gates_stay_between_start_and_finish_in_driving_order():
    pts, w = _straight_road()
    d = dummies.place_dummies(pts, w, n_sectors=3, loop=False)
    start = _arc_of(pts, d["AC_START_0"])
    finish = _arc_of(pts, d["AC_TIME_0_L"])
    splits = [_arc_of(pts, d[f"AC_TIME_{k}_L"]) for k in (1, 2)]
    assert splits == sorted(splits), "splits must be crossed in order"
    for s in splits:
        assert start < s < finish, f"split at {s} m is outside the run ({start}..{finish})"


def test_grid_is_at_the_start_of_the_road():
    pts, w = _straight_road()
    d = dummies.place_dummies(pts, w, n_sectors=3, loop=False)
    assert _arc_of(pts, d["AC_START_0"]) < 60.0
    assert d["AC_HOTLAP_START_0"] == d["AC_START_0"]


def test_gates_span_the_road_width_across_it_not_along_it():
    # A gate is a line ACROSS the road: its two ends differ in Z (lateral) and share X (along).
    pts, w = _straight_road()
    d = dummies.place_dummies(pts, w, n_sectors=3, loop=False)
    left, right = d["AC_TIME_0_L"], d["AC_TIME_0_R"]
    assert math.isclose(left[0], right[0], abs_tol=1.0)
    assert abs(left[2] - right[2]) > 5.0          # ~ the 6 m road width


def test_end_tangents_do_not_wrap_around_to_the_other_end():
    # On an L-shaped open road the last vertex is far from the first. If the tangent wrapped, the
    # start gate would be laid out using a heading taken across the map.
    pts = [(float(i) * 10.0, 0.0, 0.0) for i in range(100)]          # east
    pts += [(990.0, 0.0, float(i) * 10.0) for i in range(1, 100)]    # then north
    w = [6.0] * len(pts)
    d = dummies.place_dummies(pts, w, n_sectors=3, loop=False)
    left, right = d["AC_TIME_0_L"], d["AC_TIME_0_R"]
    # finish is on the northward leg, so its gate spans in X and shares Z
    assert abs(left[0] - right[0]) > 5.0
    assert math.isclose(left[2], right[2], abs_tol=1.0)


def test_loop_still_wraps_and_keeps_its_start_line_ahead_of_the_grid():
    # The closed-circuit path is unchanged: TIME_0 sits just ahead of the grid, not at "the end".
    n = 400
    r = 500.0
    pts = [(r * math.cos(2 * math.pi * i / n), 0.0, r * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    w = [10.0] * n
    d = dummies.place_dummies(pts, w, n_sectors=3, loop=True)
    assert {"AC_TIME_0_L", "AC_TIME_1_L", "AC_TIME_2_L"} <= set(d)
    gate = d["AC_TIME_0_L"]
    start = d["AC_START_0"]
    gap = math.hypot(gate[0] - start[0], gate[2] - start[2])
    assert 10.0 < gap < 80.0, f"start line should sit ~30 m ahead of the grid, got {gap:.1f} m"
