"""GrassFX occluder allow-list invariant (scripts/ac/ext_config.generate).

This is the crash-class guard: a far-field or oversized mesh wrongly enrolled as a GrassFX
OCCLUDING_MESH explodes the occlusion bounding volume at session load and freezes the whole PC
(shipped v0.12.1-v0.12.6). The list must include every building WALL/roof variant (so the variety
split stays occlusion-transparent) and MUST NOT include foliage, far-field backdrops, elevated decks,
thin posts/signs, or the see-through chain-link fences.

Plain ``test_*`` for tests/run_tests.py (no pytest fixtures) — drives the real generate() over a
synthetic project so it tests the actual prefix tuple, not a copy.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.ac import ext_config

ALL_GROUPS = [
    "1ROAD_main", "1KERB_l", "1RUNOFF_c", "MARKINGS", "ROADTEXT", "1GRASS",
    "BUILDINGS", "BRICK", "STUCCO", "WAREHOUSE", "WHMETAL", "ROOFS", "RFMETAL", "WATER",
    "TREES", "BUSHES", "LIGHTS", "POLE", "WIRE", "SIGNS", "SIGNPOST", "CHAINLINK",
    "MOUNTAINS", "HIGHWAY", "HWYSTRUCT", "CONTAINER",
]


def _occluding_line(groups):
    d = Path(tempfile.mkdtemp())
    (d / "data").mkdir()
    (d / "track.config.json").write_text(json.dumps({"slug": "t"}))
    (d / "data" / "environment.obj").write_text("\n".join(f"o {g}" for g in groups) + "\n")
    cfg = ext_config.generate(d)
    for ln in cfg.read_text().splitlines():
        if ln.startswith("OCCLUDING_MESHES"):
            return [s.strip() for s in ln.split("=", 1)[1].split(",") if s.strip()]
    raise AssertionError("no OCCLUDING_MESHES line emitted")


def test_building_wall_variants_all_occlude():
    occ = set(_occluding_line(ALL_GROUPS))
    # every wall variant must occlude (grass never grows through a building wall)
    for wall in ("BUILDINGS", "BRICK", "STUCCO", "WAREHOUSE", "WHMETAL"):
        assert wall in occ, f"{wall} wall must be a GrassFX occluder"


def test_farfield_foliage_and_thin_props_never_occlude():
    occ = set(_occluding_line(ALL_GROUPS))
    # the crash class: these MUST stay out of the occluder list
    for banned in ("MOUNTAINS", "HIGHWAY", "HWYSTRUCT", "TREES", "BUSHES",
                   "LIGHTS", "POLE", "WIRE", "SIGNS", "SIGNPOST", "CHAINLINK"):
        assert banned not in occ, f"{banned} must NOT be a GrassFX occluder (PC-freeze risk / cosmetic)"
