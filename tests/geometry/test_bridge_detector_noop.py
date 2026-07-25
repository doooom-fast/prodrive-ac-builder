"""A track with NO bridges must still build.

_bridge_detector's docstring promises "a no-op if there are none", but it returned None — while all
six of its call sites invoke bridge_of(...) unguarded. Any genuinely bridge-free road therefore died
with "'NoneType' object is not callable" deep inside the ring construction. It stayed hidden because
every track built so far happened to have at least one detected span.
"""

from scripts.geometry.build_mesh import _bridge_detector


def _flat_world(n=200, step=5.0):
    """A road lying exactly on flat ground — nothing to span anywhere."""
    centerline = [(i * step, 0.0, 0.0) for i in range(n)]
    # natural_grid mirrors the road height, so the road never rides above bare earth
    grid = [[(i * step, 0.0, j * step) for i in range(n)] for j in range(3)]
    return centerline, grid


def test_no_bridges_returns_a_callable_not_none():
    centerline, grid = _flat_world()
    bridge_of = _bridge_detector(centerline, grid)
    assert bridge_of is not None, "call sites invoke this unguarded"
    assert callable(bridge_of)


def test_the_no_op_reports_no_bridge_anywhere():
    centerline, grid = _flat_world()
    bridge_of = _bridge_detector(centerline, grid)
    for station in (0.0, 100.0, 500.0, 12345.0, -5.0):
        assert bridge_of(station) is False


def test_no_op_records_an_empty_span_list():
    # downstream persistence reads last_spans; a stale list from a previous track would be worse
    # than none at all
    centerline, grid = _flat_world()
    _bridge_detector(centerline, grid)
    assert _bridge_detector.last_spans == []
