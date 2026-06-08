"""Small pure-Python units: archive resolution, model dedup, region clipping."""

from scripts.scs.convert_models import dedup
from scripts.scs.extract import archives_for
from scripts.scs.parse_map import clip_features, region_bbox


def test_archives_for():
    assert archives_for({}) == ["base.scs", "def.scs"]
    # accepts names with or without the dlc_ prefix; no double-prefixing
    assert archives_for({"dlc": ["colorado", "dlc_utah"]}) == [
        "base.scs", "def.scs", "dlc_colorado.scs", "dlc_utah.scs"]


def test_dedup_case_insensitive():
    assert dedup(["a.pmg", "A.PMG", "b.pmg", "b.pmg"]) == ["a.pmg", "b.pmg"]


def test_region_bbox():
    assert region_bbox({"region": {"bbox": [1, 2, 3, 4]}}) == (1, 2, 3, 4)
    assert region_bbox({"region": {}}) is None


def test_clip_features():
    feats = [
        {"geometry": {"coordinates": [[0, 0], [10, 10]]}},      # has a vertex inside
        {"geometry": {"coordinates": [[100, 100], [200, 200]]}},  # fully outside
    ]
    kept = clip_features(feats, (-5, -5, 5, 5))
    assert len(kept) == 1
