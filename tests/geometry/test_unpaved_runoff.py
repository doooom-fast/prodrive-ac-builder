"""Unpaved run-off: the shoulder may fall away, but a cliff is still a cliff.

The excursion sweep steps laterally every 0.5 m, so an ordinary 2:1 fill slope (0.25 m per step)
trips its 0.12 m drop test at every sample. On a paved circuit that is correct — run-off there is a
flat apron. On a graded dirt road the slope IS the surface. These tests pin the relaxation to
exactly two escapes and prove it cannot swallow a real ledge.
"""

import json
import math
import tempfile
from pathlib import Path

from scripts.geometry import drive_test


def _project(road_surface, edge_profile):
    """A short straight road with a caller-supplied lateral ground profile beyond the pavement.

    ``edge_profile(off)`` returns ground height at lateral offset ``off`` (m) from the centre.
    """
    d = Path(tempfile.mkdtemp())
    (d / "data").mkdir()
    (d / "track.config.json").write_text(json.dumps(
        {"slug": "t", "road_surface": road_surface, "loop": False}))
    n, half, step = 240, 3.25, 3.0
    pts = [(i * step, 0.0, 0.0) for i in range(n)]
    (d / "data" / "finished_centerline.json").write_text(json.dumps(
        {"points_xyz_m": [list(p) for p in pts], "widths_m": [half * 2] * n}))

    # ONE global vertex list — OBJ face indices are file-global, not per-group. (Restarting them
    # per group makes the grass reference the road's vertices, which silently produces a mesh with
    # no attributable pavement: built_edge never gets set and every drop reads as out-of-band.)
    verts: list = []
    groups: list = []

    def quad(p0, p1, p2, p3):
        b = len(verts) + 1
        verts.extend([p0, p1, p2, p3])
        return [(b, b + 1, b + 2), (b, b + 2, b + 3)]

    road_faces: list = []
    for i in range(n - 1):
        x0, x1 = i * step, (i + 1) * step
        road_faces += quad((x0, 0.0, -half), (x1, 0.0, -half), (x1, 0.0, half), (x0, 0.0, half))
    groups.append(("1ROAD_main", road_faces))

    grass_faces: list = []
    offs = [half + 0.5 * k for k in range(0, 25)]     # grass starts AT the pavement edge, no gap
    for i in range(n - 1):
        x0, x1 = i * step, (i + 1) * step
        for sgn in (1.0, -1.0):
            for a, b in zip(offs, offs[1:]):
                grass_faces += quad((x0, edge_profile(a), sgn * a), (x1, edge_profile(a), sgn * a),
                                    (x1, edge_profile(b), sgn * b), (x0, edge_profile(b), sgn * b))
    groups.append(("1GRASS_a", grass_faces))

    lines = ["v %.3f %.3f %.3f" % v for v in verts]
    for name, faces in groups:
        lines.append("o " + name)
        lines += ["f %d %d %d" % f for f in faces]
    (d / "data" / "track.obj").write_text("\n".join(lines) + "\n")
    return d


def _fill_slope(off):
    """A real graded shoulder: ~1.5 m of flat verge, then a 2:1 embankment that falls away and
    DAYLIGHTS into the hillside after ~2 m — embankments stop when they meet natural ground, they
    do not fall forever. This is the shape Dragon Tail measures; its worst drops sit at +/-9 m and
    its fall across the swept band is under 2 m."""
    return -min(2.0, 0.5 * max(0.0, off - 5.0))


def _cliff(off):
    """Flat shoulder, then a 3 m ledge — deeper than build_mesh's 2 m parapet warrant."""
    return 0.0 if off < 6.0 else -3.0


def _edge_ledge(off):
    """A 0.6 m drop immediately off the pavement edge — a ledge on any surface."""
    return 0.0 if off < 3.75 else -0.6


def test_gravel_tolerates_an_ordinary_fill_slope():
    r = drive_test.run(_project("gravel", _fill_slope))
    assert r["excursion_drops"] == 0, "a 2:1 embankment is the surface on a dirt road, not a defect"


def test_tarmac_still_fails_the_same_fill_slope():
    # Unchanged behaviour for paved tracks: run-off there is meant to be a flat apron.
    r = drive_test.run(_project("tarmac", _fill_slope))
    assert r["excursion_drops"] > int(r["lap_m"] / 1000)


def test_gravel_still_fails_a_real_cliff():
    r = drive_test.run(_project("gravel", _cliff))
    assert r["excursion_drops"] > 0, "a 3 m unguarded ledge must fail on any surface"


def test_gravel_still_fails_a_drop_at_the_pavement_edge():
    r = drive_test.run(_project("gravel", _edge_ledge))
    assert r["excursion_drops"] > 0, "leave the road and fall immediately — a ledge on any surface"
