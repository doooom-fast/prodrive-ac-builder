"""Regression tests for the loop terrain-conform front-end (build_kn5_loop): declared bridge spans.

The bpy passes (corridor subdivision, contact pin, prop re-seat) run only inside Blender; the
pure-python span detection + declaration they depend on is tested here — it is what keeps the I-8
trench a trench (pin may only push DOWN on a span) and what hands the kn5 ground gate its standard
declared-span exemption for the loop's real bridges."""

import json
import math
import tempfile
from pathlib import Path

from scripts.ac.build_kn5_loop import detect_bridge_spans, declare_bridge_spans, _mpd

LON0, LAT0 = -117.04, 32.78


def _ll(x, z):
    m_lon, m_lat = _mpd(LAT0)
    return (LON0 + x / m_lon, LAT0 + z / m_lat)


def _straight_centerline(n=200, step=4.0):
    return [(0.0, 10.0, i * step) for i in range(n)]


def test_detect_bridge_spans_finds_crossing():
    pts = _straight_centerline()
    ways = [{"hw": "secondary", "geom": [_ll(-30.0, 100.0), _ll(30.0, 100.0)]}]
    spans = detect_bridge_spans(pts, (LON0, LAT0), ways)
    assert len(spans) == 1
    a, b = spans[0]
    assert a < 100.0 < b, f"span {spans[0]} must cover station 100"
    assert b - a < 80.0, "span must stay local to the crossing"


def test_detect_bridge_spans_ignores_freeway_bridges():
    """A motorway bridge crossing OVER the loop must not mark a phantom span on the road below."""
    pts = _straight_centerline()
    ways = [{"hw": "motorway", "geom": [_ll(-30.0, 300.0), _ll(30.0, 300.0)]},
            {"hw": "motorway_link", "geom": [_ll(-30.0, 500.0), _ll(30.0, 500.0)]}]
    assert detect_bridge_spans(pts, (LON0, LAT0), ways) == []


def test_detect_bridge_spans_mirror_x():
    pts = [(-x, y, z) for x, y, z in _straight_centerline()]   # mirrored frame (x flipped)
    ways = [{"hw": "primary", "geom": [_ll(-30.0, 100.0), _ll(30.0, 100.0)]}]
    spans = detect_bridge_spans(pts, (LON0, LAT0), ways, mirror_x=True)
    assert len(spans) == 1 and spans[0][0] < 100.0 < spans[0][1]


def test_declare_bridge_spans_writes_gate_files():
    """declare_bridge_spans must emit the two files kn5_ground_check's declared-span exemption
    reads — bridge.spans.auto.json (station ranges) and finished_centerline.json in the KN5 frame
    (z negated: the Blender-first path ships (x, y, -z) of the local frame)."""
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "data").mkdir()
        pts = _straight_centerline()
        (proj / "data" / "centerline.local.json").write_text(json.dumps({
            "origin": {"lon": LON0, "lat": LAT0},
            "points_xyz_m": [list(p) for p in pts],
            "widths_m": [9.0] * len(pts)}))
        (proj / "data" / "bridges.cache.json").write_text(json.dumps(
            [{"hw": "secondary", "geom": [list(_ll(-30.0, 100.0)), list(_ll(30.0, 100.0))]}]))
        (proj / "track.config.json").write_text(json.dumps({"slug": "t", "mirror_x": False}))
        spans = declare_bridge_spans(proj)
        assert len(spans) == 1
        auto = json.loads((proj / "data" / "bridge.spans.auto.json").read_text())
        assert len(auto) == 1 and auto[0][0] < 100.0 < auto[0][1]
        fc = json.loads((proj / "data" / "finished_centerline.json").read_text())
        assert len(fc["points_xyz_m"]) == len(pts)
        assert fc["widths_m"][0] == 9.0
        # KN5 frame: z negated vs the local frame
        assert math.isclose(fc["points_xyz_m"][50][2], -pts[50][2], abs_tol=1e-6)


def test_declare_bridge_spans_no_bridges_is_clean():
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "data").mkdir()
        pts = _straight_centerline(n=20)
        (proj / "data" / "centerline.local.json").write_text(json.dumps({
            "origin": {"lon": LON0, "lat": LAT0},
            "points_xyz_m": [list(p) for p in pts],
            "widths_m": [7.0] * len(pts)}))
        (proj / "track.config.json").write_text(json.dumps({"slug": "t"}))
        assert declare_bridge_spans(proj) == []
        assert json.loads((proj / "data" / "bridge.spans.auto.json").read_text()) == []
