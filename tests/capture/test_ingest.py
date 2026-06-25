"""Hermetic end-to-end test for the capture pipeline: synth bundle → ingest → evidence JSON.

Builds a throwaway project (the real ``data/`` is gitignored and may be absent in a worktree), walks a
synthetic GPS run along its centerline, ingests it, and checks the distilled
``source/realworld_capture.json`` lands on the line. Plain ``tempfile`` + asserts so it runs under both
``tests/run_tests.py`` (no pytest in this env) and pytest in the 3.11 dev env.
"""

import json
import tempfile
from pathlib import Path

from scripts.capture import bundle as bundle_mod
from scripts.capture import ingest, synth

# straight 300 m centerline heading north, +2% grade — easy to predict station / lateral / grade.
LEN_M = 300
GRADE = 0.02
LON0, LAT0, ELEV0 = -104.94, 39.78, 1580.0


def _write_project(root, *, mirror_x=False):
    proj = root / "track"
    data = proj / "data"
    data.mkdir(parents=True)
    pts = [[0.0, round(GRADE * z, 3), float(z)] for z in range(0, LEN_M + 1, 10)]
    (data / "centerline.local.json").write_text(json.dumps({
        "frame": "ENU local meters (X=east, Y=up, Z=north)",
        "origin": {"lon": LON0, "lat": LAT0, "elev_m": ELEV0},
        "true_north_rotation_deg": 0.0,
        "points_xyz_m": pts,
        "widths_m": [9.0] * len(pts),
    }))
    cfg = {
        "name": "Test Track", "slug": "test_track",
        "location": {"lat": LAT0, "lon": LON0, "timezone": "America/Denver"},
        "source": {"type": "osm"}, "loop": True, "default_width_m": 9.0, "width_overrides": [],
        "origin": "centroid", "true_north_rotation_deg": 0.0,
        "surfaces": {"road": "1ROAD", "grass": "GRASS", "kerb": "1KERB"},
        "layouts": [], "lighting": {"presets": []},
    }
    if mirror_x:
        cfg["mirror_x"] = True
    (proj / "track.config.json").write_text(json.dumps(cfg))
    return proj


def _load_capture(proj):
    return json.loads((proj / "source" / "realworld_capture.json").read_text())


def test_roundtrip_centered():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = _write_project(root)
        synth.write_bundle(root / "bundle", proj, session_id="lap1")
        stats = ingest.build(proj, root / "bundle")

        doc = _load_capture(proj)
        assert doc["schema_version"] == 1
        assert doc["track_slug"] == "test_track"
        assert len(doc["sources"]) == 1
        assert doc["sources"][0]["bundle"] == "bundle"
        assert stats["coverage_pct"] >= 95.0
        # GPS walked exactly on the centerline → every station's lateral ≈ 0
        assert max(abs(s["lat_offset_m"]) for s in doc["stations"]) < 0.05
        # placements / texture_overrides are reserved for a later phase — empty now
        assert doc["placements"] == [] and doc["texture_overrides"] == []


def test_grade_recovered():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = _write_project(root)
        synth.write_bundle(root / "bundle", proj, session_id="lap1")
        ingest.build(proj, root / "bundle")
        doc = _load_capture(proj)

        mid = [s for s in doc["stations"] if 100 <= s["station_m"] <= 200]
        assert mid, "expected interior stations"
        for s in mid:
            assert s["grade_pct"] is not None
            assert abs(s["grade_pct"] - GRADE * 100) < 0.2            # ~2.0%
            assert abs(s["alt_m"] - GRADE * s["station_m"]) < 0.2     # mesh-relative altitude tracks ramp


def test_lateral_offset_signed():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = _write_project(root)
        synth.write_bundle(root / "bundle", proj, session_id="lap1", lateral_m=2.0)
        ingest.build(proj, root / "bundle")
        doc = _load_capture(proj)
        interior = [s for s in doc["stations"] if 50 <= s["station_m"] <= 250]
        avg = sum(s["lat_offset_m"] for s in interior) / len(interior)
        assert abs(avg - 2.0) < 0.1   # recovers the synthetic 2 m offset, with sign


def test_ingest_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = _write_project(root)
        synth.write_bundle(root / "bundle", proj, session_id="lap1")
        ingest.build(proj, root / "bundle")
        first = (proj / "source" / "realworld_capture.json").read_text()
        ingest.build(proj, root / "bundle")           # re-ingest same bundle
        second = (proj / "source" / "realworld_capture.json").read_text()
        assert first == second                        # deterministic, no double-count
        assert len(_load_capture(proj)["sources"]) == 1


def test_multilap_merge_strengthens_stations():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = _write_project(root)
        synth.write_bundle(root / "b1", proj, session_id="lap1")
        synth.write_bundle(root / "b2", proj, session_id="lap2")
        ingest.build(proj, root / "b1")
        n_one = {s["station_m"]: s["n"] for s in _load_capture(proj)["stations"]}
        ingest.build(proj, root / "b2")
        two = _load_capture(proj)

        assert len(two["sources"]) == 2
        s150 = next(s for s in two["stations"] if s["station_m"] == 150.0)
        assert sorted(s150["sources"]) == ["b1", "b2"]
        assert s150["n"] == n_one[150.0] * 2     # two laps → double the evidence count


def test_mirror_x_roundtrips():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = _write_project(root, mirror_x=True)
        synth.write_bundle(root / "bundle", proj, session_id="lap1")
        ingest.build(proj, root / "bundle")
        doc = _load_capture(proj)
        # synth + ingest both honor mirror_x, so the line still reconstructs at lateral ≈ 0
        assert max(abs(s["lat_offset_m"]) for s in doc["stations"]) < 0.05


def test_schema_version_mismatch_rejected():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = _write_project(root)
        synth.write_bundle(root / "bundle", proj, session_id="lap1")
        man_path = root / "bundle" / bundle_mod.MANIFEST_NAME
        man = json.loads(man_path.read_text())
        man["schema_version"] = 999
        man_path.write_text(json.dumps(man))
        raised = ""
        try:
            bundle_mod.load_manifest(root / "bundle")
        except ValueError as e:
            raised = str(e)
        assert "schema_version" in raised
