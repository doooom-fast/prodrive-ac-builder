"""SCS .mat/.tobj -> AC material mapping."""

import json
import tempfile
from pathlib import Path

from scripts.scs.materials import build_materials, map_shader, resolve_tobj


def test_map_shader_prefixes():
    assert map_shader("eut2.dif.spec.weight.mult2") == "ksPerPixelMultiMap"
    assert map_shader("eut2.dif.spec") == "ksPerPixel"
    assert map_shader("eut2.dif") == "ksPerPixel"
    assert map_shader("eut2.grass") == "ksGrass"
    assert map_shader("eut2.vegetation.leaf") == "ksTree"
    assert map_shader("nope.unknown") == "ksPerPixel"  # default


def test_resolve_tobj():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.tobj"
        p.write_text("map 2d\n/material/x.dds\n")
        assert resolve_tobj(p) == "/material/x.dds"
        assert resolve_tobj(Path(d) / "missing.tobj") is None


def test_build_materials():
    with tempfile.TemporaryDirectory() as d:
        tree = Path(d)
        (tree / "road.tobj").write_text("/tex/road.dds\n")
        (tree / "road.mat").write_text('effect : "eut2.dif.spec" {\n  texture : "road.tobj"\n}\n')
        out = build_materials([tree / "road.mat"], tree, tree / "data")
        doc = json.loads(Path(out).read_text())
    m = doc["materials"][0]
    assert m["scs_shader"] == "eut2.dif.spec"
    assert m["ac_shader"] == "ksPerPixel", m
    assert m["textures"]["txDiffuse"] == "/tex/road.dds"
