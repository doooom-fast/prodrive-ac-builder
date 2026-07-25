"""The road_surface fork: one config knob must change BOTH the physics and the look.

A rally stage and its fantasy-paved twin share every vertex of geometry, so ``road_surface`` is the
only thing standing between "drives like dirt" and "drives like asphalt". These tests pin both
halves — surfaces.ini (track_folder) and the texture binding (pbr) — plus the guard that a typo in
the config fails the build instead of silently shipping tarmac.
"""

import json
import tempfile
from pathlib import Path

from scripts.ac import pbr, track_folder


def _road_block(ini: str) -> dict:
    """Parse the SURFACE_* block whose KEY=ROAD into a plain dict."""
    for block in ini.split("\n\n"):
        kv = dict(ln.split("=", 1) for ln in block.splitlines() if "=" in ln)
        if kv.get("KEY") == "ROAD":
            return kv
    raise AssertionError("no ROAD surface block")


def test_tarmac_is_the_default_and_keeps_full_grip():
    road = _road_block(track_folder.surfaces_ini())
    assert road["FRICTION"] == "0.99"
    assert road["DIRT_ADDITIVE"] == "0"
    assert road["IS_VALID_TRACK"] == "1"


def test_gravel_is_loose_dirty_and_still_valid_track():
    road = _road_block(track_folder.surfaces_ini(road_surface="gravel"))
    assert float(road["FRICTION"]) < 0.8          # loose surface, far less grip than tarmac
    assert float(road["DAMPING"]) > 0             # soft surface absorbs energy
    assert road["DIRT_ADDITIVE"] == "1"           # car actually picks up dust
    assert road["IS_VALID_TRACK"] == "1"          # still the racing surface — not run-off
    assert road["WAV"] == "gravel.wav"


def test_only_the_road_surface_changes_between_variants():
    # The gravel fork must not quietly alter grass/kerb/runoff — a stage still has to behave
    # correctly when the car leaves the road.
    tar = track_folder.surfaces_ini()
    gra = track_folder.surfaces_ini(road_surface="gravel")
    strip = lambda s: [b for b in s.split("\n\n") if "KEY=ROAD\n" not in b + "\n"]
    assert strip(tar) == strip(gra)


def test_unknown_road_surface_is_an_error_not_a_silent_tarmac():
    try:
        track_folder.surfaces_ini(road_surface="dirt")   # plausible typo for "gravel"
    except ValueError as e:
        assert "dirt" in str(e) and "gravel" in str(e)
    else:
        raise AssertionError("an unknown road_surface must fail the build")


def _proj(root, cfg):
    proj = Path(root)
    (proj / "track.config.json").write_text(json.dumps(cfg))
    return proj


def test_gravel_config_binds_the_gravel_road_texture():
    with tempfile.TemporaryDirectory() as d:
        ov = pbr.load_overrides(_proj(d, {"slug": "t", "road_surface": "gravel"}))
        assert ov["1ROAD"]["diffuse"].endswith("gravel_road_diffuse.png")
        assert ov["1ROAD"]["normal"].endswith("gravel_road_normal.png")
        assert ov["1RUNOFF"]["diffuse"].endswith("gravel_road_diffuse.png")
        # the texture the config points at has to actually exist, or the road renders black in-engine
        assert Path(ov["1ROAD"]["diffuse"]).is_file()
        assert Path(ov["1ROAD"]["normal"]).is_file()


def test_tarmac_config_leaves_the_stock_asphalt_binding_alone():
    with tempfile.TemporaryDirectory() as d:
        ov = pbr.load_overrides(_proj(d, {"slug": "t", "road_surface": "tarmac"}))
        assert "1ROAD" not in ov and "1RUNOFF" not in ov


def test_explicit_texture_override_beats_the_gravel_default():
    with tempfile.TemporaryDirectory() as d:
        proj = _proj(d, {"slug": "t", "road_surface": "gravel",
                         "texture_overrides": {"1ROAD": {"diffuse": "source/my_road.png"}}})
        ov = pbr.load_overrides(proj)
        assert ov["1ROAD"]["diffuse"].endswith("my_road.png")
        assert ov["1RUNOFF"]["diffuse"].endswith("gravel_road_diffuse.png")   # untouched key still forks
