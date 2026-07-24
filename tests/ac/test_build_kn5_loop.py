"""Smoke tests for the loop front-end (scripts/ac/build_kn5_loop.py + scripts/build_loop.sh).

The loop program preps an EXISTING hand-authored loop.blend — a different program from the
OBJ-import build_kn5.py — so these tests pin its contract without needing Blender: the AC rename
map stays AC-conventional and material-covered, the over-cap guard has teeth, the wrapper is wired
to the right program, and kn5_ground_check runs honestly in kn5-internal mode when a project has
no generated OBJs. Plain ``test_*`` for tests/run_tests.py (no pytest fixtures).
"""

from __future__ import annotations

from pathlib import Path

from tests.geometry.test_drive_test import _project

from scripts.ac import pbr
from scripts.ac.build_kn5_loop import AC_NAME, VERT_CAP, assert_under_cap
from scripts.ac.kn5_ground_check import check
from scripts.ac.kn5_write import build

ROOT = Path(__file__).resolve().parents[2]


def test_ac_name_map_is_ac_conventional():
    # every physical target carries a `1` surface prefix keyed to surfaces.ini, and the two
    # load-bearing remaps (CURB -> collidable sidewalk kerb, GUARDRAIL -> physical wall) exist
    for src, dst in AC_NAME.items():
        assert dst.startswith(("1ROAD", "1KERB", "1GRASS", "1WALL")), (src, dst)
    assert AC_NAME["CURB"] == "1KERB_sidewalk"
    assert AC_NAME["GUARDRAIL"] == "1WALL_guard"


def test_loop_prefixes_covered_by_engine_pbr():
    """Every mesh name the loop program produces (or passes through) must resolve to a TEXTURES
    entry — an unmatched prefix ships a textureless kn5 material, which renders BLACK in-engine."""
    names = list(AC_NAME.values()) + [
        "PALMTRUNK_12", "PALMFROND_12", "TREETRUNK_3", "TREECANOPY_3", "SCRUB_9",
        "HOUSE_4", "BLDGPLAIN_2", "GREEN_1", "MARKINGS_e5", "YLINE_2", "SIDEWALK_1",
    ]
    for name in names:
        key = next((k for k in pbr.TEXTURES if name.upper().startswith(k)), None)
        assert key is not None, f"no pbr.TEXTURES entry covers '{name}'"
    # dict-ordered prefix priority: the sub-prefixed entries must come BEFORE their generic prefix
    keys = list(pbr.TEXTURES)
    assert keys.index("1KERB_SIDEWALK") < keys.index("1KERB")
    assert keys.index("1WALL_GUARD") < keys.index("1WALL")


def test_loop_pbr_textures_exist_on_disk():
    tex = ROOT / "assets" / "textures"
    for key in ("1KERB_SIDEWALK", "1WALL_GUARD", "PALMTRUNK", "PALMFROND", "HOUSE"):
        diff, norm = pbr.TEXTURES[key][0], pbr.TEXTURES[key][1]
        for fn in (diff, norm):
            if fn:
                assert (tex / fn).exists(), f"{key}: missing assets/textures/{fn}"


def test_overcap_guard_has_teeth():
    assert_under_cap("1GRASS_0", VERT_CAP)          # at the cap: fine
    try:
        assert_under_cap("1GRASS_0", VERT_CAP + 1)  # over: FATAL, never a warning
    except SystemExit as e:
        assert "1GRASS_0" in str(e)
    else:
        raise AssertionError("over-cap mesh did not abort the build")


def test_build_loop_wrapper_wired_to_loop_program():
    sh = ROOT / "scripts" / "build_loop.sh"
    assert sh.exists()
    body = sh.read_text(encoding="utf-8")
    assert "build_kn5_loop.py" in body            # the loop program, not the OBJ program
    assert "scripts/ac/build_kn5.py" not in body  # never merged / never cross-wired
    assert "kn5_ground_check" in body and "verify_kn5" in body and "track_folder" in body


def test_ground_check_kn5_internal_mode_without_objs():
    """A Blender-first project has no generated OBJs: the fidelity half must SKIP honestly (no
    'unalignable' / 'missing on one side' failures) while the physical kn5 checks still run."""
    d = _project()
    build(d)                                   # native kn5 from the synthetic OBJs
    (d / "data" / "track.obj").unlink()        # now it looks Blender-authored
    r = check(d)
    assert r["fail"] is False, r["reasons"]


def test_ground_check_full_fidelity_still_gates_with_objs():
    """Adding the kn5-internal mode must NOT loosen the OBJ-backed gate."""
    d = _project()
    build(d)
    objp = d / "data" / "track.obj"
    out = []
    for ln in objp.read_text(encoding="utf-8").splitlines():
        if ln.startswith("v "):
            x, y, z = (float(t) for t in ln.split()[1:4])
            ln = f"v {x:.4f} {y + 5.0:.4f} {z:.4f}"
        out.append(ln)
    objp.write_text("\n".join(out) + "\n", encoding="utf-8")
    r = check(d)
    assert r["fail"] is True and r["reasons"]
