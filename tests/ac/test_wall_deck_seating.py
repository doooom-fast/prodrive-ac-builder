"""Wall-seating gate: elevated decks are legitimate support (the San Diego freeway lesson).

kn5_ground_check's base-seating lens used to measure wall/barrier feet against terrain triangles
only — on a network track whose walls stand on elevated 1ROAD / HWYSTRUCT decks, that read "walls
hovering 40.3%" while ~96% of feet sat at their own height on the decks (k10-san-diego PR #3).
The lens now seats feet against a SUPPORT hash (terrain + 1ROAD + HWYSTRUCT) with a ~4 m
closest-to-reference layer window so stacked interchange decks don't cross-grab.

These tests pin both directions: a wall standing on an elevated HWYSTRUCT deck must read SEATED
(this fails on the old grass-only lens: gap ~6 m), and a wall genuinely hovering over the ground
must still FAIL the gate. Plain ``test_*`` for tests/run_tests.py (no pytest fixtures).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tests.geometry.test_drive_test import _grass_plane, _write_obj

from scripts.ac.kn5_ground_check import check
from scripts.ac.kn5_write import build
from scripts.geometry import ribbon

N_M = 200
DECK_Y = 6.0


def _plate(x0: float, x1: float, z0: float, z1: float, y: float, cell: float = 4.0) -> dict:
    """Flat horizontal grid plate (small cells: the gate hashes triangles by centroid)."""
    xs = [x0 + i * cell for i in range(int(round((x1 - x0) / cell)) + 1)]
    zs = [z0 + j * cell for j in range(int(round((z1 - z0) / cell)) + 1)]
    verts = [(x, y, z) for z in zs for x in xs]
    nx = len(xs)
    tris = []
    for j in range(len(zs) - 1):
        for i in range(nx - 1):
            a = j * nx + i
            tris.append((a, a + 1, a + nx + 1))
            tris.append((a, a + nx + 1, a + nx))
    return {"vertices": verts, "tris": tris, "uvs": [(0.0, 0.0)] * len(verts)}


def _wall(x: float, z0: float, z1: float, y0: float, h: float = 1.0, step: float = 2.0) -> dict:
    """Vertical wall ribbon along z at fixed x, feet at y0."""
    zs = [z0 + i * step for i in range(int(round((z1 - z0) / step)) + 1)]
    verts, tris = [], []
    for i, z in enumerate(zs):
        verts.append((x, y0, z))
        verts.append((x, y0 + h, z))
        if i:
            a = 2 * (i - 1)
            tris.append((a, a + 2, a + 3))
            tris.append((a, a + 3, a + 1))
    return {"vertices": verts, "tris": tris, "uvs": [(0.0, 0.0)] * len(verts)}


def _project(wall_on_deck: bool = False, hovering_wall: bool = False) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "data").mkdir()
    (d / "track.config.json").write_text(json.dumps({"slug": "t", "mirror_x": False}))
    cl = [(0.0, 0.0, float(z)) for z in range(0, N_M + 1, 5)]
    widths = [8.0] * len(cl)
    (d / "data" / "centerline.local.json").write_text(json.dumps(
        {"points_xyz_m": [list(p) for p in cl], "widths_m": widths,
         "origin": {"lon": 0.0, "lat": 0.0, "elev_m": 0.0}}))
    groups = [("1ROAD_main", ribbon.road_ribbon(cl, widths)), ("1GRASS", _grass_plane())]
    if wall_on_deck:
        # elevated structural deck + a wall seated ON it, plus a second deck stacked well above:
        # the layer window must seat the wall on ITS deck, not cross-grab the upper one.
        groups.append(("HWYSTRUCT_deck", _plate(14.0, 30.0, 40.0, 160.0, DECK_Y)))
        groups.append(("HWYSTRUCT_upper", _plate(14.0, 30.0, 40.0, 160.0, DECK_Y + 12.0)))
        groups.append(("1WALL_deck", _wall(22.0, 60.0, 140.0, DECK_Y)))
    if hovering_wall:
        # feet 1.5 m over the grass plane (y=-0.02) with NO deck anywhere near: a genuine hover
        groups.append(("1WALL_hover", _wall(-15.0, 60.0, 140.0, 1.5)))
    _write_obj(d / "data" / "track.obj", groups)
    return d


def test_wall_on_elevated_deck_reads_seated():
    d = _project(wall_on_deck=True)
    build(d)
    r = check(d)
    assert r["fail"] is False, r["reasons"]
    assert not any("walls" in reason for reason in r["reasons"])


def test_genuinely_hovering_wall_still_fails():
    d = _project(hovering_wall=True)
    build(d)
    r = check(d)
    assert r["fail"] is True
    assert any("walls" in reason for reason in r["reasons"]), r["reasons"]
