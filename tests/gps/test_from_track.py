"""Build a centerline from a recorded GPS drive — scripts/gps/from_track.

Synthesises a small square loop of GPS fixes (the dashcam/redtiger_gps JSON format), runs the
drive->centerline builder into a temp project, and asserts a pipeline-shaped centerline.geojson comes
out (closed, resampled, width-tagged). Plain tempfile + asserts for tests/run_tests.py.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.gps import from_track as ft


def _square_track(path: Path, n_per_side: int = 40, size: float = 0.004, lat0: float = 39.78, lon0: float = -104.94):
    """~square loop (approx 1.3 km/side at this latitude) sampled densely, with timestamps."""
    corners = [(lat0, lon0), (lat0 + size, lon0), (lat0 + size, lon0 + size), (lat0, lon0 + size)]
    fixes, sec = [], 0
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        for k in range(n_per_side):
            t = k / n_per_side
            fixes.append({"t": f"2026-04-06T18:{40 + sec // 60:02d}:{sec % 60:02d}",
                          "lat": a[0] + (b[0] - a[0]) * t, "lon": a[1] + (b[1] - a[1]) * t})
            sec += 1
    path.write_text(json.dumps(fixes))


def test_builds_closed_centerline_from_drive():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        trk = proj / "track.json"
        _square_track(trk)
        out, stats = ft.build_from_track(proj, [str(trk)], loop=True, width_m=8.0)
        assert out.exists()
        gj = json.loads(out.read_text())
        feats = gj["features"]
        cl = next(f for f in feats if f["properties"].get("kind") == "full")
        assert cl["properties"]["closed"] is True
        coords = cl["geometry"]["coordinates"]
        assert len(coords) > 100                                  # resampled to ~3 m over a ~5 km loop
        assert coords[0][0] < 0 and coords[0][1] > 0              # [lon,lat] order: lon negative (W), lat positive (N)
        assert all(w == 8.0 for w in cl["properties"]["widths_m"])
        assert 1.2 < stats["length_km"] < 2.0                     # ~444 m + ~341 m sides, square perimeter
        assert (proj / "data" / "centerline_preview.svg").exists()


def test_resample_spacing_is_even():
    import math
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        trk = proj / "t.json"
        _square_track(trk)
        out, _ = ft.build_from_track(proj, [str(trk)], loop=True)
        coords = json.loads(out.read_text())["features"][0]["geometry"]["coordinates"]
        # consecutive spacings should hover around the 3 m resample target (allow corners/closing slack)
        ds = []
        for i in range(1, min(len(coords), 200)):
            (lo1, la1), (lo2, la2) = coords[i - 1], coords[i]
            ds.append(math.hypot((lo2 - lo1) * 85000, (la2 - la1) * 111000))
        ds = [x for x in ds if x > 0]
        assert 2.0 < (sum(ds) / len(ds)) < 4.5
