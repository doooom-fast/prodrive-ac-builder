"""Unit tests for evidence-driven elevation correction (scripts/capture/evidence.py).

The correction is reined-in: it rejects transient altitude spikes, gates corrections to ~0 on near-flat
terrain, and permits a metre-scale lift ONLY inside a declared bridge span (the bare-earth DEM is ground
truth everywhere else). These tests pin that behaviour. Plain tempfile + asserts so they run under
tests/run_tests.py and pytest alike.
"""

import json
import math
import tempfile
from pathlib import Path

from scripts.capture import evidence


def _line(length=400, step=5, y=0.0):
    """Straight centerline along +Z; station of vertex i == i*step. Flat heightfield at ``y``."""
    return [(0.0, y, float(z)) for z in range(0, length + 1, step)]


def _valley(length=400, step=5, lo=120, hi=260, depth=6.0):
    """Flat heightfield with a smooth raised-cosine valley dipping to ``-depth`` over stations lo..hi —
    the bare-earth shape under a real bridge/overpass (deck stays level while the ground drops away).
    ~140 m wide, like the real Sand Creek crossing, so the strong smoothing keeps the deck correction."""
    pts = []
    c, half = (lo + hi) / 2.0, (hi - lo) / 2.0
    for z in range(0, length + 1, step):
        u = (z - c) / half
        y = -depth * 0.5 * (1 + math.cos(math.pi * u)) if -1 < u < 1 else 0.0
        pts.append((0.0, y, float(z)))
    return pts


def _capture(stations):
    """stations = list of (station_m, alt_m, n)."""
    return {"stations": [{"station_m": s, "alt_m": a, "n": n} for s, a, n in stations]}


def _maxabs(a, b):
    return max(abs(p[1] - q[1]) for p, q in zip(a, b))


def _lift_at(pts, out, station):
    return {int(p[2]): o[1] - p[1] for p, o in zip(pts, out)}[station]


def test_agreement_zone_is_untouched():
    # captured road == heightfield everywhere → no correction, keep the cleaner heightfield
    pts = _line(y=0.0)
    cap = _capture([(z, 0.0, 50) for z in range(0, 401, 5)])
    out, st = evidence.corrected_elevation(pts, cap)
    assert _maxabs(out, pts) < 0.1
    assert st["n_corrected"] == 0


def test_constant_offset_is_removed():
    # a uniform +5 m offset (car height / GPS bias) is NOT a real divergence → corrected to ~0
    pts = _line(y=0.0)
    cap = _capture([(z, 5.0, 50) for z in range(0, 401, 5)])
    out, st = evidence.corrected_elevation(pts, cap)
    assert _maxabs(out, pts) < 0.15
    assert abs(st["offset_m"] - 5.0) < 0.01


def test_flat_terrain_divergence_is_noise():
    # THE core fix: a sustained divergence on FLAT terrain (no DEM relief, no declared bridge) is GPS/baro
    # noise, not a road deck — it must be gated to ~0 so the road follows the clean heightfield.
    pts = _line(y=0.0)
    stations = [(z, 6.0 if 150 <= z <= 200 else 0.0, 50) for z in range(0, 401, 5)]
    out, st = evidence.corrected_elevation(pts, _capture(stations))
    assert _maxabs(out, pts) < 0.2
    assert st["max_offbridge_m"] < 0.2


def test_off_bridge_divergence_over_real_relief_is_capped_sub_metre():
    # bare earth dips ~6 m and the capture reads level over it, but it's NOT a declared crossing (a road
    # that follows a real swale, e.g. E 56th). Can't tell it from a bridge without a declaration, so the
    # correction is hard-capped sub-metre — the road follows the DEM.
    pts = _valley()
    stations = [(z, 0.0, 50) for z in range(0, 401, 5)]   # level captured road over the valley
    out, st = evidence.corrected_elevation(pts, _capture(stations))
    assert st["max_offbridge_m"] <= 0.51
    assert st["max_corr_m"] <= 0.51


def test_divergent_deck_corrected_at_declared_bridge():
    # the genuine case: bare earth dips into a creek bed, the captured deck stays level, and the crossing
    # IS declared → the road is lifted back toward the level deck (the road bridges the dip).
    pts = _valley(depth=6.0)
    stations = [(z, 0.0, 50) for z in range(0, 401, 5)]
    out, st = evidence.corrected_elevation(pts, _capture(stations),
                                           bridges=[(190.0, 160.0)], max_correction_m=8.0)
    assert _lift_at(pts, out, 190) > 3.5            # the deck is lifted up out of the bare-earth valley
    assert abs(_lift_at(pts, out, 50)) < 0.2        # flat approaches well outside the span stay put
    assert st["max_corr_m"] > 3.5


def test_same_deck_suppressed_without_a_declared_bridge():
    # identical geometry to the test above but NO bridge declared → suppressed to sub-metre. The bridge
    # declaration is the ONLY thing that earns a metre-scale lift (a positive signal, not just divergence).
    pts = _valley(depth=6.0)
    stations = [(z, 0.0, 50) for z in range(0, 401, 5)]
    out, st = evidence.corrected_elevation(pts, _capture(stations))   # no bridges
    assert st["max_corr_m"] <= 0.51


def test_transient_spike_rejected_even_inside_a_bridge():
    # a single station spikes 10 m off its neighbours (the phone fell / GPS glitch) WITH enough passes to
    # clear min_n. Place it inside a bridge so only the Hampel outlier filter can suppress it.
    pts = _line(y=0.0)
    stations = [(z, 0.0, 50) for z in range(0, 401, 5)]
    stations[33] = (165, 10.0, 50)                  # n=50 spike at station 165 (passes min_n)
    out, st = evidence.corrected_elevation(pts, _capture(stations),
                                           bridges=[(165.0, 30.0)], max_correction_m=8.0)
    assert _maxabs(out, pts) < 1.0                  # the spike does not move the road
    assert st["n_outliers"] >= 1


def test_low_sample_stations_ignored():
    # a single-pass GPS spike (n < min_n) must not move the road, even inside a bridge
    pts = _line(y=0.0)
    stations = [(z, 0.0, 50) for z in range(0, 401, 5)]
    stations[33] = (165, 10.0, 2)                   # n=2 spike at station 165
    out, _ = evidence.corrected_elevation(pts, _capture(stations), bridges=[(165.0, 30.0)])
    assert _maxabs(out, pts) < 0.3


def test_bridge_correction_is_capped():
    # an absurd divergence inside a declared bridge is still capped at max_correction_m
    pts = _valley(depth=12.0)                       # a 12 m bare-earth dip, far deeper than the 4 m cap
    stations = [(z, 0.0, 50) for z in range(0, 401, 5)]
    out, st = evidence.corrected_elevation(pts, _capture(stations),
                                           bridges=[(190.0, 180.0)], max_correction_m=4.0)
    assert st["max_corr_m"] <= 4.01 and st["max_corr_m"] > 2.0


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
    True, missing config True."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        assert evidence.use_capture_elevation(proj) is True            # no config -> default on
        (proj / "track.config.json").write_text(json.dumps({"slug": "t"}))
        assert evidence.use_capture_elevation(proj) is True            # key absent -> default on
        (proj / "track.config.json").write_text(json.dumps({"capture": {"use_elevation": False}}))
        assert evidence.use_capture_elevation(proj) is False           # explicit opt-out
        (proj / "track.config.json").write_text(json.dumps({"capture": {"use_elevation": True}}))
        assert evidence.use_capture_elevation(proj) is True


def test_bridge_spans_config():
    """capture.bridges → [(center_m, len_m)] declared deck crossings; absent/no-config → []."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        assert evidence.bridge_spans(proj) == []                       # no config
        (proj / "track.config.json").write_text(json.dumps({"slug": "t"}))
        assert evidence.bridge_spans(proj) == []                       # key absent
        (proj / "track.config.json").write_text(json.dumps(
            {"capture": {"bridges": [{"name": "creek", "center_m": 5950, "len_m": 130}]}}))
        assert evidence.bridge_spans(proj) == [(5950.0, 130.0)]
