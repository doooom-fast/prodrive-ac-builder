"""build_open_path — chaining roads into a point-to-point route instead of a lap.

build_ring closes a loop by trimming every road at the junctions with its neighbours, *including*
the wrap from the last road back to the first. Handed a single open road that wrap is the road
against itself, both "corners" land on the same vertex, and the route collapses to one point — which
is exactly what a 25 km rally stage did before this existed.
"""

from scripts.gps import centerline


def test_single_road_survives_intact():
    line = [(float(i), 0.0) for i in range(50)]
    path, gaps = centerline.build_open_path([line])
    assert path == line          # not trimmed, not collapsed
    assert gaps == []


def test_single_road_through_build_ring_would_collapse():
    # Pins WHY the open path exists: the loop builder is not a safe fallback for an open route.
    line = [(float(i), 0.0) for i in range(50)]
    ring, _ = centerline.build_ring([line])
    assert len(ring) < len(line)


def test_two_roads_chain_end_to_end_keeping_both_free_ends():
    a = [(float(i), 0.0) for i in range(20)]           # x 0..19
    b = [(19.0 + float(i), 0.0) for i in range(20)]    # x 19..38, joins a at its end
    path, gaps = centerline.build_open_path([a, b])
    xs = [p[0] for p in path]
    assert xs[0] == 0.0 and xs[-1] == 38.0             # both far ends kept
    assert xs == sorted(xs)                            # monotonic: no backtrack at the junction
    assert len(gaps) == 1


def test_second_road_is_flipped_when_it_points_the_wrong_way():
    a = [(float(i), 0.0) for i in range(20)]                    # x 0..19
    b = [(38.0 - float(i), 0.0) for i in range(20)]             # x 38..19 — reversed in OSM
    path, _ = centerline.build_open_path([a, b])
    xs = [p[0] for p in path]
    assert xs[0] == 0.0 and xs[-1] == 38.0
    assert xs == sorted(xs)


def test_first_road_is_flipped_when_its_junction_is_at_its_head():
    a = [(19.0 - float(i), 0.0) for i in range(20)]             # x 19..0, joins b at its HEAD
    b = [(19.0 + float(i), 0.0) for i in range(20)]             # x 19..38
    path, _ = centerline.build_open_path([a, b])
    xs = [p[0] for p in path]
    assert xs[0] == 0.0 and xs[-1] == 38.0
    assert xs == sorted(xs)


def test_three_roads_chain_in_order():
    segs = [[(float(k * 10 + i), 0.0) for i in range(11)] for k in range(3)]   # 0..10, 10..20, 20..30
    path, gaps = centerline.build_open_path(segs)
    xs = [p[0] for p in path]
    assert xs[0] == 0.0 and xs[-1] == 30.0
    assert xs == sorted(xs)
    assert len(gaps) == 2
