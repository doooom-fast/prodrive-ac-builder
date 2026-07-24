"""Smoke tests for the native kn5 writer + shipped-binary fidelity gate.

scripts/ac/kn5_write builds a kn5 straight from the audited OBJs; scripts/ac/kn5_ground_check
compares the shipped binary back against those OBJs. Together they close the "gates green, game
broken" gap — so the smoke test drives both over a tiny synthetic project: a faithful build must
PASS, and the same kn5 checked against a displaced track.obj must FAIL (the gate has teeth).

Plain ``test_*`` for tests/run_tests.py (no pytest fixtures).
"""

from __future__ import annotations

from tests.geometry.test_drive_test import _project

from scripts.ac.kn5_write import build
from scripts.ac.kn5_ground_check import check


def test_native_kn5_matches_audited_objs():
    d = _project()
    kn5 = build(d)
    assert kn5.exists() and kn5.stat().st_size > 0
    r = check(d)
    assert r["fail"] is False, r["reasons"]


def test_fidelity_gate_catches_displaced_geometry():
    d = _project()
    build(d)
    # displace every OBJ vertex 5 m up AFTER the export: the shipped kn5 no longer matches the
    # audited geometry, exactly the assembly-drift class the gate exists to catch
    objp = d / "data" / "track.obj"
    out = []
    for ln in objp.read_text(encoding="utf-8").splitlines():
        if ln.startswith("v "):
            x, y, z = (float(t) for t in ln.split()[1:4])
            ln = f"v {x:.4f} {y + 5.0:.4f} {z:.4f}"
        out.append(ln)
    objp.write_text("\n".join(out) + "\n", encoding="utf-8")
    r = check(d)
    assert r["fail"] is True
    assert r["reasons"]
