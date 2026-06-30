"""End-to-end front-end: aerial screenshot → centerline.geojson (auto-trace and trace_px paths)."""

import json
import tempfile
from pathlib import Path

from scripts.aerial import build_aerial
from tests.aerial._png import ring_image, write_png

# Two opposite corners of an 80px image tied to a small real-world box near Dacono, CO.
CONTROL = [
    {"px": [0.1, 0.1], "lonlat": [-104.9501, 40.04498], "_corner": "NW"},
    {"px": [0.9, 0.9], "lonlat": [-104.94607, 40.03976], "_corner": "SE"},
]


def _project(tmp: Path, *, source: dict, png: bool) -> Path:
    pd = tmp
    (pd / "source").mkdir(parents=True)
    (pd / "data").mkdir()
    if png:
        write_png(pd / "source" / "ring.png", 80, 80, ring_image(80, 40, 40, 28, 7))
    cfg = {
        "name": "Synthetic Loop", "slug": "synthetic_loop", "version": "0.1.0",
        "location": {"lat": 40.0423, "lon": -104.9482, "timezone": "America/Denver"},
        "source": source, "loop": True, "default_width_m": 8.0, "origin": "centroid",
        "surfaces": {"road": "1ROAD", "grass": "GRASS", "kerb": "1KERB"},
        "layouts": [{"id": "full", "ai": None, "uses_connectors": []}],
        "lighting": {"presets": ["noon"]},
    }
    (pd / "track.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return pd


def _full_feature(pd: Path) -> dict:
    gj = json.loads((pd / "data" / "centerline.geojson").read_text())
    return next(f for f in gj["features"] if f["properties"].get("kind") == "full")


def test_build_auto_trace_from_png():
    with tempfile.TemporaryDirectory() as d:
        pd = _project(Path(d), source={
            "type": "aerial", "screenshot": "source/ring.png",
            "nearby_roads": ["Summit Blvd"], "control_points": CONTROL, "detect_step": 1,
        }, png=True)
        stats = build_aerial.build(pd)
        assert stats["trace_mode"] == "auto"
        f = _full_feature(pd)
        coords = f["geometry"]["coordinates"]
        assert f["properties"]["closed"] and coords[0] == coords[-1]
        assert f["properties"]["source"] == "aerial"
        assert f["properties"]["nearby_roads"] == ["Summit Blvd"]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        # The ring sits inside the control box, so every point is georeferenced within it.
        assert -104.9501 <= min(lons) and max(lons) <= -104.94607
        assert 40.03976 <= min(lats) and max(lats) <= 40.04498


def test_build_trace_px_path_and_widths():
    trace = [[0.5, 0.2], [0.8, 0.5], [0.5, 0.8], [0.2, 0.5]]  # a diamond, normalised
    with tempfile.TemporaryDirectory() as d:
        pd = _project(Path(d), source={
            "type": "aerial", "screenshot": "source/none.png",  # unused: trace_px short-circuits
            "control_points": CONTROL, "trace_px": trace,
        }, png=False)
        # image_size still needs the file; write a tiny one.
        write_png(pd / "source" / "none.png", 80, 80, ring_image(80, 40, 40, 5, 2))
        stats = build_aerial.build(pd)
        assert stats["trace_mode"] == "trace_px"
        f = _full_feature(pd)
        assert f["properties"]["closed"]
        assert len(f["properties"]["widths_m"]) == f["properties"]["point_count"]
        assert all(w == 8.0 for w in f["properties"]["widths_m"])
        assert stats["length_km"] > 0


def test_missing_control_point_lonlat_errors():
    with tempfile.TemporaryDirectory() as d:
        pd = _project(Path(d), source={
            "type": "aerial", "screenshot": "source/r.png",
            "control_points": [{"px": [0.1, 0.1], "lonlat": None},
                               {"px": [0.9, 0.9], "lonlat": [-104.94, 40.03]}],
            "trace_px": [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6]],
        }, png=False)
        write_png(pd / "source" / "r.png", 40, 40, ring_image(40, 20, 20, 5, 2))
        try:
            build_aerial.build(pd)
        except SystemExit:
            return
        raise AssertionError("expected SystemExit when a control point lacks lonlat")
