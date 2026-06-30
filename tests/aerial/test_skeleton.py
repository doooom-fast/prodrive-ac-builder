"""Ribbon → 1-px skeleton → ordered loop, plus noise rejection."""

import math

from scripts.aerial import skeleton
from tests.aerial._png import ring_image


def _mask_from_ring(size, cx, cy, r, thick):
    """Reuse the test ring image, thresholding grey (fg) back into a boolean mask."""
    rows = ring_image(size, cx, cy, r, thick)
    mask = []
    for row in rows:
        mask.append([row[3 * x] == 120 for x in range(size)])
    return mask


def test_largest_component_drops_noise():
    mask = _mask_from_ring(60, 30, 30, 20, 5)
    mask[2][2] = mask[2][3] = mask[3][2] = True  # a tiny disconnected speck
    kept = skeleton.largest_component(mask)
    assert not kept[2][2]                              # speck removed
    assert sum(c for row in kept for c in row) > 80    # ring survives


def test_thin_reduces_ribbon_to_thin_line():
    mask = _mask_from_ring(70, 35, 35, 24, 7)
    before = sum(c for row in mask for c in row)
    skel = skeleton.thin(mask)
    assert 0 < len(skel) < before * 0.5  # a 7px-thick ring collapses well under half its area


def test_order_path_traverses_the_loop():
    mask = _mask_from_ring(80, 40, 40, 28, 6)
    path = skeleton.trace_centerline(mask)
    assert len(path) > 60
    # Consecutive points stay adjacent (no big jumps), and the walk returns near its start (a loop).
    hops = [math.dist(path[i], path[i + 1]) for i in range(len(path) - 1)]
    assert max(hops) <= 6.0 + 1e-9
    assert math.dist(path[0], path[-1]) < 12.0
