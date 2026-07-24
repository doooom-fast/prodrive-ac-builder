"""Smoke tests for the virtual drive test gate (scripts/geometry/drive_test.run).

Builds a tiny synthetic project — a straight, flat 200 m road ribbon seated on a grass plane —
and drives it: a clean build must PASS; a wall dropped across the lane must be reported as an
obstruction and FAIL the gate. Plain ``test_*`` for tests/run_tests.py (no pytest fixtures).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.geometry import ribbon
from scripts.geometry.drive_test import run as drive_run

W = 8.0
N_M = 200


def _write_obj(path: Path, groups: list[tuple[str, dict]]) -> None:
    lines: list[str] = []
    base = 1
    for name, mesh in groups:
        lines.append(f"o {name}")
        for x, y, z in mesh["vertices"]:
            lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
        for u, v in mesh.get("uvs") or [(0.0, 0.0)] * len(mesh["vertices"]):
            lines.append(f"vt {u:.4f} {v:.4f}")
        for a, b, c in mesh["tris"]:
            lines.append(f"f {base+a}/{base+a} {base+b}/{base+b} {base+c}/{base+c}")
        base += len(mesh["vertices"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _grass_plane(y: float = -0.02, half: float = 40.0, zmax: float = float(N_M), cell: float = 10.0) -> dict:
    xs, zs = [], []
    x = -half
    while x <= half + 1e-9:
        xs.append(x); x += cell
    z = -20.0
    while z <= zmax + 20.0 + 1e-9:
        zs.append(z); z += cell
    verts = [(x, y, z) for z in zs for x in xs]
    nx = len(xs)
    tris = []
    for j in range(len(zs) - 1):
        for i in range(nx - 1):
            a = j * nx + i
            tris.append((a, a + 1, a + nx + 1))
            tris.append((a, a + nx + 1, a + nx))
    return {"vertices": verts, "tris": tris,
            "uvs": [(0.0, 0.0)] * len(verts)}


def _project(with_wall_across_lane: bool = False) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "data").mkdir()
    (d / "track.config.json").write_text(json.dumps({"slug": "t", "mirror_x": False}))
    cl = [(0.0, 0.0, float(z)) for z in range(0, N_M + 1, 5)]
    widths = [W] * len(cl)
    (d / "data" / "centerline.local.json").write_text(json.dumps(
        {"points_xyz_m": [list(p) for p in cl], "widths_m": widths,
         "origin": {"lon": 0.0, "lat": 0.0, "elev_m": 0.0}}))
    road = ribbon.road_ribbon(cl, widths)
    groups = [("1ROAD_main", road), ("1GRASS", _grass_plane())]
    if with_wall_across_lane:
        wall = {"vertices": [(-2.0, 0.0, 100.0), (2.0, 0.0, 100.0),
                             (2.0, 1.2, 100.0), (-2.0, 1.2, 100.0)],
                "tris": [(0, 1, 2), (0, 2, 3)],
                "uvs": [(0.0, 0.0)] * 4}
        groups.append(("BARRIER_block", wall))
    _write_obj(d / "data" / "track.obj", groups)
    return d


def test_clean_straight_road_passes():
    r = drive_run(_project())
    assert r["fail"] is False
    assert r["soft_top_in_lane"] == 0
    assert r["obstruction_stations"] == 0
    assert r["daylight_gaps"] == 0


def test_wall_across_the_lane_is_an_obstruction_and_fails():
    r = drive_run(_project(with_wall_across_lane=True))
    assert r["obstruction_stations"] > 0
    assert any(k.startswith("BARRIER") for k in r["obstruction_by_mesh"]), r["obstruction_by_mesh"]
    assert r["fail"] is True
