"""pbr.load_overrides resolves real-world texture overrides from realworld_capture.json (no bpy)."""

import json
import tempfile
from pathlib import Path

from scripts.ac import pbr


def _proj(root, overrides):
    proj = Path(root)
    (proj / "source").mkdir()
    (proj / "source" / "realworld_capture.json").write_text(
        json.dumps({"texture_overrides": overrides}))
    return proj


def test_resolves_paths_relative_to_project():
    with tempfile.TemporaryDirectory() as d:
        proj = _proj(d, [{"material": "1ROAD", "diffuse": "source/textures/r_d.jpg",
                          "normal": "source/textures/r_n.jpg", "source": "bundle"}])
        ov = pbr.load_overrides(proj)
        assert set(ov) == {"1ROAD"}
        assert ov["1ROAD"]["diffuse"] == str(proj / "source/textures/r_d.jpg")
        assert ov["1ROAD"]["normal"] == str(proj / "source/textures/r_n.jpg")


def test_absent_capture_is_empty():
    with tempfile.TemporaryDirectory() as d:
        assert pbr.load_overrides(Path(d)) == {}


def test_material_key_uppercased_and_diffuse_only_ok():
    with tempfile.TemporaryDirectory() as d:
        proj = _proj(d, [{"material": "1grass", "diffuse": "x.jpg"}])
        ov = pbr.load_overrides(proj)
        assert "1GRASS" in ov
        assert ov["1GRASS"]["diffuse"].endswith("x.jpg")
        assert "normal" not in ov["1GRASS"]
