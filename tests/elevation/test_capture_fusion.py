"""Hermetic tests for capture fusion: DEM profile + synthetic phone evidence → z_fused_m.

Same conventions as the capture tests: plain ``test_*`` functions, ``tempfile``, no pytest fixtures,
so they run under both ``tests/run_tests.py`` and pytest.

The synthetic world: a flat 100 m road. The DEM disagrees with a +2 m "ground" bump (vegetation /
cut-fill — the road-maps-to-the-ground-but-not-the-road problem) between 200–260 m. The phone drove
the real road, so its altitude is flat — plus a sensor height (phone above the road) and a constant
datum bias (GPS vertical + geoid), both of which fusion must absorb without inventing corrections.
"""

import json
import tempfile
from pathlib import Path

from scripts.elevation import capture_fusion

LAP_M = 600
SPACING = 3.0
ROAD_Z = 100.0            # true road elevation, flat
BUMP = (200.0, 260.0, 2.0)  # DEM-only ground bump: start, end, height
SENSOR_H = 1.35           # matches the fusion default
DATUM = 3.0               # constant GPS-vertical + geoid bias baked into the phone alt
ORIGIN_ELEV = 95.0
COVER = (100.0, 500.0)    # stations exist only on this span (every 5 m)


def _dem_z(d: float) -> float:
    s, e, h = BUMP
    return ROAD_Z + (h if s <= d <= e else 0.0)


def _write_project(root: Path, *, bump=True, fall_span=None, cfg_extra=None) -> Path:
    proj = root / "track"
    data = proj / "data"
    data.mkdir(parents=True)

    cfg = {
        "name": "Test Track", "slug": "test_track",
        "location": {"lat": 39.78, "lon": -104.94, "timezone": "America/Denver"},
        "source": {"type": "osm"}, "loop": True, "default_width_m": 9.0, "width_overrides": [],
        "origin": "centroid", "true_north_rotation_deg": 0.0,
        "surfaces": {"road": "1ROAD", "grass": "GRASS", "kerb": "1KERB"},
        "layouts": [], "lighting": {"presets": []},
    }
    if cfg_extra:
        cfg.update(cfg_extra)
    (proj / "track.config.json").write_text(json.dumps(cfg))

    dist = [i * SPACING for i in range(int(LAP_M / SPACING) + 1)]
    z = [(_dem_z(d) if bump else ROAD_Z) for d in dist]
    (data / "centerline.elevation.json").write_text(json.dumps({
        "spacing_m": SPACING, "point_count": len(dist),
        "distance_m": dist, "z_raw_m": z, "z_smooth_m": z,
    }))

    stations = []
    d = COVER[0]
    while d <= COVER[1]:
        alt = ROAD_Z + SENSOR_H + DATUM - ORIGIN_ELEV   # phone measured the flat road
        if fall_span and fall_span[0] <= d <= fall_span[1]:
            alt += 8.0                                   # phone fell / re-seated: bad run of samples
        stations.append({"station_m": d, "lat_offset_m": 0.0, "alt_m": round(alt, 3),
                         "gps_hacc_m": 4.0, "n": 5, "frames": []})
        d += 5.0
    (proj / "source").mkdir()
    (proj / "source" / "realworld_capture.json").write_text(json.dumps({
        "schema_version": 1, "track_slug": "test_track",
        "origin": {"lon": -104.94, "lat": 39.78, "elev_m": ORIGIN_ELEV},
        "stations": stations, "sources": [], "placements": [], "texture_overrides": [],
    }))
    return proj


def _fused(proj: Path):
    elev = json.loads((proj / "data" / "centerline.elevation.json").read_text())
    return elev.get("z_fused_m"), elev


def test_constant_offset_absorbed():
    """Sensor height + datum bias alone must produce ~zero correction (relative fusion)."""
    with tempfile.TemporaryDirectory() as d:
        proj = _write_project(Path(d), bump=False)
        stats = capture_fusion.build(proj)
        assert not stats.get("skipped"), stats
        assert abs(stats["datum_offset_m"] - DATUM) < 0.15, stats
        z_fused, _ = _fused(proj)
        assert max(abs(v - ROAD_Z) for v in z_fused) < 0.05


def test_dem_bump_flattened_where_covered():
    """The DEM-only ground bump is pulled to the measured road; uncovered spans stay pure DEM."""
    with tempfile.TemporaryDirectory() as d:
        proj = _write_project(Path(d), bump=True)
        stats = capture_fusion.build(proj)
        assert not stats.get("skipped"), stats
        z_fused, elev = _fused(proj)
        dist = elev["distance_m"]
        mid = min(range(len(dist)), key=lambda i: abs(dist[i] - 230.0))   # bump centre, covered
        assert abs(z_fused[mid] - ROAD_Z) < 0.3, z_fused[mid]
        assert abs(z_fused[0] - ROAD_Z) < 0.05                            # station 0: no evidence → DEM
        assert stats["max_abs_correction_m"] > 1.5, stats


def test_phone_fall_rejected():
    """A locally-consistent bad run (mount fell) is rejected, not averaged into the road."""
    with tempfile.TemporaryDirectory() as d:
        proj = _write_project(Path(d), bump=True, fall_span=(300.0, 340.0))
        stats = capture_fusion.build(proj)
        assert not stats.get("skipped"), stats
        rejected = stats["rejected_short_segment"] + stats["rejected_offset_segment"]
        assert rejected == 9, stats                     # 300,305,...,340 — the fall segment, whole
        assert stats["segments_rejected"] == 1, stats   # bounded by two impossible altitude steps
        z_fused, elev = _fused(proj)
        dist = elev["distance_m"]
        k = min(range(len(dist)), key=lambda i: abs(dist[i] - 320.0))
        assert abs(z_fused[k] - ROAD_Z) < 0.3, z_fused[k]   # fall span heals to the road, not +8 m


def test_disabled_via_config():
    with tempfile.TemporaryDirectory() as d:
        proj = _write_project(Path(d), cfg_extra={
            "elevation": {"capture_fusion": {"enabled": False}}})
        stats = capture_fusion.build(proj)
        assert stats.get("skipped")
        z_fused, _ = _fused(proj)
        assert z_fused is None


def test_projection_prefers_fused():
    """scripts.geometry.projection picks z_fused_m over z_smooth_m when present."""
    from scripts.geometry import projection
    with tempfile.TemporaryDirectory() as d:
        proj = _write_project(Path(d), bump=False)
        data = proj / "data"
        n = 5
        coords = [[-104.94 + i * 1e-4, 39.78] for i in range(n)]
        (data / "centerline.geojson").write_text(json.dumps({
            "type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {"kind": "full", "widths_m": [9.0] * n},
                "geometry": {"type": "LineString", "coordinates": coords}}]}))
        (data / "centerline.elevation.json").write_text(json.dumps({
            "spacing_m": SPACING, "distance_m": [i * 10.0 for i in range(n)],
            "z_raw_m": [100.0] * n, "z_smooth_m": [100.0] * n,       # flat: height would be 0
            "z_fused_m": [100.0, 101.0, 102.0, 103.0, 104.0],        # fused: 4 m of height
        }))
        out = projection.build(proj)
        assert out["height_m"] == 4.0, out
