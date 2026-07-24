"""Audit check F (curb-not-flush) must actually SEE the built curbs.

Built OBJ curb groups are named 1KERB_sidewalk_a / 1KERB_corners / ... — F used to load them with
prefix "KERB", which matches NONE of them, so it reported "0 (of 0 curb verts)" on every track
ever built: a vacuous gate. These tests pin that the prefix matches 1KERB-style names (curb_verts
must be non-zero when 1KERB groups exist), that a flush rolled curb passes, and that a curb
stepped vertically away from everything is flagged. Plain ``test_*`` for tests/run_tests.py.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tests.geometry.test_drive_test import _grass_plane, _write_obj

from scripts.geometry import ribbon
from scripts.geometry.audit_mesh import audit

N_M = 200


def _curb(y: float, x0: float = 4.1, x1: float = 4.4) -> dict:
    """Thin curb strip just outside the road edge (road half-width 4.0), verts on the
    centerline's 5 m stations so they sit within reach of the road-edge vertex rows."""
    zs = [float(z) for z in range(0, N_M + 1, 5)]
    verts, tris = [], []
    for i, z in enumerate(zs):
        verts.append((x0, y, z))
        verts.append((x1, y, z))
        if i:
            a = 2 * (i - 1)
            tris.append((a, a + 2, a + 3))
            tris.append((a, a + 3, a + 1))
    return {"vertices": verts, "tris": tris, "uvs": [(0.0, 0.0)] * len(verts)}


def _project(curb_y: float) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "data").mkdir()
    (d / "track.config.json").write_text(json.dumps({"slug": "t", "mirror_x": False}))
    cl = [(0.0, 0.0, float(z)) for z in range(0, N_M + 1, 5)]
    widths = [8.0] * len(cl)
    groups = [("1ROAD_main", ribbon.road_ribbon(cl, widths)),
              ("1GRASS", _grass_plane()),
              ("1KERB_sidewalk_a", _curb(curb_y))]     # the REAL naming scheme — the F prefix pin
    _write_obj(d / "data" / "track.obj", groups)
    return d


def test_f_sees_1kerb_groups_and_flush_rolled_curb_passes():
    # rolled curb 5 cm above the road deck — real curbs sit ~3-6 cm proud and must pass
    r = audit(_project(curb_y=0.05))
    assert r["curb_verts"] > 0          # the vacuity pin: "0 curb verts" means the prefix regressed
    assert r["F_curb_not_flush"] == 0


def test_f_flags_curb_stepped_away_from_road_and_ground():
    # curb 1.2 m over both the road (y=0) and the grass (y=-0.02): a genuine step/gap
    r = audit(_project(curb_y=1.2))
    assert r["curb_verts"] > 0
    assert r["F_curb_not_flush"] > 0
