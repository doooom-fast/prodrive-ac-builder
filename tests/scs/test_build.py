"""Full SCS track build reuses the geometry back-half (ribbon + grass + dummies)."""

import json
import tempfile
from pathlib import Path

from scripts.scs.build import build_track, flat_ground

CFG = {
    "name": "Demo", "slug": "demo",
    "location": {"lon": -105.0, "lat": 39.7, "timezone": "America/Denver"},
    "source": {"type": "scs", "game": "ats"}, "loop": False, "default_width_m": 9.0,
    "origin": "centroid", "surfaces": {"road": "1ROAD", "grass": "GRASS", "kerb": "1KERB"},
    "layouts": [], "lighting": {"presets": []}, "route": {"roads": ["A", "B"]},
}
REGION = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "A", "road_look": None},
     "geometry": {"type": "LineString", "coordinates": [[0, 0], [120, 0]]}},
    {"type": "Feature", "properties": {"name": "B", "road_look": None},
     "geometry": {"type": "LineString", "coordinates": [[120, 0], [120, 90]]}},
]}


def test_flat_ground_grid():
    grid = flat_ground([(0, 0, 0), (100, 0, 50)], margin_m=10.0, spacing_m=10.0)
    assert len(grid) >= 2 and len(grid[0]) >= 2
    assert all(v[1] == 0.0 for row in grid for v in row)  # flat


def test_build_track_full_obj_and_dummies():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "data").mkdir()
        (proj / "track.config.json").write_text(json.dumps(CFG))
        (proj / "data" / "region.geojson").write_text(json.dumps(REGION))
        stats = build_track(proj)  # also derives centerline.local.json from region.geojson
        obj = (proj / "data" / "track.obj").read_text()
        assert (proj / "data" / "track.mtl").exists()
        dums = json.loads((proj / "data" / "dummies.json").read_text())
    assert "o GRASS" in obj and "o 1ROAD_main" in obj
    assert {"AC_START_0", "AC_HOTLAP_START_0", "AC_TIME_0_L", "AC_TIME_0_R"} <= set(dums)
    assert stats["triangles"] > 0
    assert stats["dummies"] >= 10  # 3 sector gates (L/R) + start + hotlap + 4 pits
