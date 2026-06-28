"""Unit tests for evidence-driven elevation correction (scripts/capture/evidence.py).

Plain tempfile + asserts so they run under tests/run_tests.py and pytest alike.
"""

import json
import tempfile
from pathlib import Path

from scripts.capture import evidence


def _line(length=300, step=5, y=0.0):
    """Straight centerline along +Z; station of vertex i == i*step."""
    return [(0.0, y, float(z)) for z in range(0, length + 1, step)]


def _capture(stations):
    """stations = list of (station_m, alt_m, n)."""
    return {"stations": [{"station_m": s, "alt_m": a, "n": n} for s, a, n in stations]}


def _maxabs(a, b):
    return max(abs(p[1] - q[1]) for p, q in zip(a, b))


def test_agreement_zone_is_untouched():
    # captured road == heightfield everywhere → no correction, keep the cleaner heightfield
    pts = _line(y=0.0)
    cap = _capture([(z, 0.0, 50) for z in range(0, 301, 5)])
    out, st = evidence.corrected_elevation(pts, cap)
    assert _maxabs(out, pts) < 0.1
    assert st["n_corrected"] == 0


def test_constant_offset_is_removed():
    # a uniform +5 m offset (car height / GPS bias) is NOT a real divergence → corrected to ~0
    pts = _line(y=0.0)
    cap = _capture([(z, 5.0, 50) for z in range(0, 301, 5)])
    out, st = evidence.corrected_elevation(pts, cap)
    assert _maxabs(out, pts) < 0.15
    assert abs(st["offset_m"] - 5.0) < 0.01


def test_divergent_deck_is_corrected():
    # heightfield flat at 0; the real road sits +6 m over stations 150..180 (a deck) → road lifts there,
    # ramps back to 0, and the agreement zones stay put
    pts = _line(y=0.0)
    stations = [(z, 6.0 if 150 <= z <= 180 else 0.0, 50) for z in range(0, 301, 5)]
    out, st = evidence.corrected_elevation(pts, _capture(stations))
    lift = {int(p[2]): o[1] - p[1] for p, o in zip(pts, out)}
    assert lift[165] > 4.5                      # deck lifted (smoothing keeps most of the 6 m)
    assert abs(lift[50]) < 0.2 and abs(lift[280]) < 0.2   # far agreement zones untouched
    assert st["max_corr_m"] > 4.5


def test_low_sample_stations_ignored():
    # a single-pass GPS spike (n < min_n) must not move the road
    pts = _line(y=0.0)
    stations = [(z, 0.0, 50) for z in range(0, 301, 5)]
    stations[30] = (150, 10.0, 2)               # n=2 spike at station 150
    out, _ = evidence.corrected_elevation(pts, _capture(stations))
    assert _maxabs(out, pts) < 0.3


def test_correction_is_capped():
    pts = _line(y=0.0)
    stations = [(z, 50.0 if 150 <= z <= 180 else 0.0, 50) for z in range(0, 301, 5)]
    out, st = evidence.corrected_elevation(pts, _capture(stations), max_correction_m=12.0)
    assert st["max_corr_m"] <= 12.01 and st["max_corr_m"] > 8.0


def test_no_or_thin_capture_returns_unchanged():
    pts = _line(y=0.0)
    same, st = evidence.corrected_elevation(pts, _capture([(0, 0.0, 50)]))  # only 1 station
    assert same == pts and st["n_corrected"] == 0


def test_load_capture_guard():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "source").mkdir()
        assert evidence.load_capture(proj) is None          # no file
        (proj / "source" / evidence.CAPTURE_NAME).write_text(json.dumps({"stations": []}))
        assert evidence.load_capture(proj) is None          # empty stations
        (proj / "source" / evidence.CAPTURE_NAME).write_text(
            json.dumps({"stations": [{"station_m": 0, "alt_m": 1.0, "n": 9}]}))
        assert evidence.load_capture(proj) is not None       # has evidence


def test_use_capture_elevation_flag():
    """capture.use_elevation in track.config.json gates whether captured altitude is applied; default
    True, missing config True. (Sand Creek sets it false — GPS/baro altitude is too noisy on flat terrain.)"""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        assert evidence.use_capture_elevation(proj) is True            # no config -> default on
        (proj / "track.config.json").write_text(json.dumps({"slug": "t"}))
        assert evidence.use_capture_elevation(proj) is True            # key absent -> default on
        (proj / "track.config.json").write_text(json.dumps({"capture": {"use_elevation": False}}))
        assert evidence.use_capture_elevation(proj) is False           # explicit opt-out
        (proj / "track.config.json").write_text(json.dumps({"capture": {"use_elevation": True}}))
        assert evidence.use_capture_elevation(proj) is True
