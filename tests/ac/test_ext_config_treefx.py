"""ext_config TreeFX integration: data/treefx.json -> extension/trees/trees.txt + [TREES] block.

Drives the real ext_config.generate() over a synthetic project so it exercises the actual wiring
(SURFACE_MATERIALS derived from the track's real groups, the README manifest, the stale-list
cleanup, and the model-resolution gate that stops a build shipping a manifest it can't satisfy).
Plain ``test_*`` for tests/run_tests.py (no pytest fixtures).
"""

from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

from scripts.ac import ext_config
from scripts.environment import treefx as tfx

GROUPS = ["1GRASS", "1ROAD_main", "1KERB_l", "BUILDINGS", "TREES", "MOUNTAINS"]
SPECIES = ["MRS_pine_high_2_1.bin", "treePine1"]


def _project(*, treefx_enabled=True, grassfx=False, models=SPECIES, bundle=False):
    """Synthetic project. ``models`` is which species actually have a .bin on disk — the point of
    several tests below is what happens when that is NOT the full declared species list."""
    d = Path(tempfile.mkdtemp())
    (d / "data").mkdir()
    (d / "track.config.json").write_text(json.dumps({"slug": "t", "lighting": {"grassfx": grassfx}}))
    (d / "data" / "environment.obj").write_text("\n".join(f"o {g}" for g in GROUPS) + "\n")
    trees_src = d / "source" / "trees"
    trees_src.mkdir(parents=True)
    for sp in models:
        (trees_src / (sp if sp.endswith(".bin") else f"{sp}.bin")).write_bytes(b"\0fake-model")
    cfg = {"enabled": treefx_enabled, "seed": 99, "bundle": bundle,
           "zones": {"forest": {"source": "fill_terrain",
                                "species": list(SPECIES),
                                "size_variance": [0.85, 1.15],
                                "density": {"by": "constant", "keep": 1.0}}}}
    c = tfx.TreeFXCollector(cfg)
    rng = random.Random(99)
    for i in range(6):
        c.add("fill_terrain", 100.0 + i, 1900.0, -float(i), rng=rng)
    c.write_json(d / "data" / "treefx.json")
    return d


def test_treefx_emits_trees_block_and_text_list():
    d = _project()
    txt = ext_config.generate(d).read_text()
    assert "[TREES]" in txt
    assert "LIST_0 = trees/trees.txt" in txt
    # SURFACE_MATERIALS is derived from the track's REAL groups (grass + road), not hardcoded
    for ln in txt.splitlines():
        if ln.startswith("SURFACE_MATERIALS"):
            assert "1GRASS_mat" in ln and "1ROAD_main_mat" in ln
            break
    else:
        raise AssertionError("no SURFACE_MATERIALS line")
    trees = (d / "build" / "t" / "extension" / "trees" / "trees.txt")
    assert trees.exists()
    body = trees.read_text()
    assert "tree: MRS_pine_high_2_1.bin;" in body or "tree: treePine1;" in body
    assert "configure: seed = 99" in body
    # the manifest lists the species this build references
    readme = (d / "build" / "t" / "extension" / "trees" / "README").read_text()
    assert "MRS_pine_high_2_1.bin" in readme
    # not bundled by default: the models stay user-supplied, nothing is copied into the build
    assert not list((d / "build" / "t" / "extension" / "trees").glob("*.bin"))


def test_species_without_a_model_is_dropped_not_referenced():
    # THE manifest-missing bug: only one of the two declared species has a .bin on disk. The build
    # must ship trees for the resolvable one and NO reference at all to the other.
    d = _project(models=["MRS_pine_high_2_1.bin"])
    txt = ext_config.generate(d).read_text()
    assert "[TREES]" in txt
    assert "treePine1" not in txt
    body = (d / "build" / "t" / "extension" / "trees" / "trees.txt").read_text()
    assert "tree: MRS_pine_high_2_1.bin;" in body
    assert "treePine1" not in body
    assert "treePine1" not in (d / "build" / "t" / "extension" / "trees" / "README").read_text()


def test_no_trees_block_at_all_when_no_model_resolves():
    # Nothing resolves -> an empty manifest would be worse than none. Skip [TREES] entirely.
    d = _project(models=[])
    txt = ext_config.generate(d).read_text()
    assert "[TREES]" not in txt
    assert not (d / "build" / "t" / "extension" / "trees" / "trees.txt").exists()


def test_bundle_copies_models_into_the_build_and_prunes_stale():
    d = _project(bundle=True)
    ext_config.generate(d)
    trees_dir = d / "build" / "t" / "extension" / "trees"
    bundled = {p.name for p in trees_dir.glob("*.bin")}
    assert bundled == {"MRS_pine_high_2_1.bin", "treePine1.bin"}
    assert "bundle" not in trees_dir.joinpath("trees.txt").read_text().lower()  # models, not config
    # a model left over from a previous build is pruned on the next one
    (trees_dir / "gone_from_config.bin").write_bytes(b"\0stale")
    ext_config.generate(d)
    assert not (trees_dir / "gone_from_config.bin").exists()
    assert {p.name for p in trees_dir.glob("*.bin")} == bundled


def test_treefx_block_independent_of_grassfx():
    # TreeFX is its own effect: a [TREES] block appears even with GrassFX off (they gate separately).
    txt = ext_config.generate(_project(grassfx=False)).read_text()
    assert "[TREES]" in txt
    assert "[GRASS_FX]" not in txt


def test_no_treefx_when_sidecar_disabled():
    txt = ext_config.generate(_project(treefx_enabled=False)).read_text()
    assert "[TREES]" not in txt


def test_stale_trees_txt_removed_on_rebuild_without_treefx():
    d = _project(treefx_enabled=True)
    ext_config.generate(d)                       # writes trees.txt
    trees = d / "build" / "t" / "extension" / "trees" / "trees.txt"
    assert trees.exists()
    (d / "data" / "treefx.json").unlink()        # rebuild WITHOUT treefx (full-rebuild discipline)
    ext_config.generate(d)
    assert not trees.exists()                     # stale list cleaned so [TREES] never dangles
