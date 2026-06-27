"""Geometry invariants for the scenery dressing helpers in scripts/environment/build_env.

Plain ``test_*`` functions (no pytest fixtures) so tests/run_tests.py can discover them under the
dependency-free system python. Covers the power-line generator (poles + sagging cables) added for the
industrial Commerce City look — there was no coverage for build_env before.
"""

from __future__ import annotations

import math

from scripts.environment.build_env import _fence_ring, _utility_pole, _wire


def _indices_in_range(mesh):
    n = len(mesh["vertices"])
    return all(0 <= a < n and 0 <= b < n and 0 <= c < n for (a, b, c) in mesh["tris"])


def test_utility_pole_tips_at_crossarm_height():
    pole, tips = _utility_pole(10.0, 2.0, -5.0, 1.0, 0.0)   # ground y=2, tangent +X
    assert _indices_in_range(pole)
    assert len(tips) == 3                                    # left / centre / right cable attach points
    ch = 2.0 + 9.6                                           # ground + crossarm height
    assert all(abs(t[1] - ch) < 1e-6 for t in tips), tips
    # crossarm spreads along the road normal (perpendicular to tangent) -> tips differ in Z, share X
    assert all(abs(t[0] - 10.0) < 1e-6 for t in tips)
    assert tips[0][2] < tips[1][2] < tips[2][2]
    # pole rises from the ground to the top
    ys = [v[1] for v in pole["vertices"]]
    assert min(ys) == 2.0 and max(ys) > ch


def test_wire_droops_between_equal_height_tips():
    a = (0.0, 11.6, 0.0)
    b = (52.0, 11.6, 0.0)                                    # same height, one span apart
    w = _wire(a, b)
    assert _indices_in_range(w)
    ys = [v[1] for v in w["vertices"]]
    # cable sags below the endpoints but never rises above them (parabolic droop)
    assert min(ys) < 11.6 - 0.5
    assert max(ys) <= 11.6 + 0.07                            # +ribbon thickness only
    # lowest point is near mid-span, not at an end
    lowest = min(w["vertices"], key=lambda v: v[1])
    assert 0.0 < lowest[0] < 52.0


def test_fence_ring_offsets_outward_and_tiles_square():
    foot = [(-10.0, -8.0), (10.0, -8.0), (10.0, 8.0), (-10.0, 8.0)]   # 20x16 footprint
    f = _fence_ring(foot, lambda x, z: 1.0, off=2.5, h=2.3, tile_m=1.6)
    assert _indices_in_range(f)
    assert len(f["tris"]) == 16                                       # 4 edges, double-sided (4 tris each)
    # every fence vertex sits farther from the centroid than the footprint corners -> pushed outward
    cx = sum(p[0] for p in foot) / 4
    cz = sum(p[1] for p in foot) / 4
    foot_r = max(math.hypot(x - cx, z - cz) for x, z in foot)
    fence_r = max(math.hypot(v[0] - cx, v[2] - cz) for v in f["vertices"])
    assert fence_r > foot_r
    # base sits on the ground (y0=1.0), top a fence-height above; v tiles by h/tile_m so diamonds stay square
    ys = [v[1] for v in f["vertices"]]
    assert min(ys) == 1.0 and abs(max(ys) - (1.0 + 2.3)) < 1e-9
    assert any(abs(v - 2.3 / 1.6) < 1e-9 for _u, v in f["uvs"])


def test_chainlink_texture_is_pot_with_holes():
    from pathlib import Path

    from scripts.geometry.road_text import _read_png
    png = Path(__file__).resolve().parents[2] / "assets" / "textures" / "chainlink_diffuse.png"
    W, H, ch, rows = _read_png(png)
    assert ch == 4                                                    # RGBA (alpha cutout)
    assert W & (W - 1) == 0 and H & (H - 1) == 0                      # power-of-two (AC hard-crashes otherwise)
    opaque = sum(1 for y in range(0, H, 4) for x in range(0, W, 4) if rows[y][x * ch + 3] > 127)
    frac = opaque / ((H // 4) * (W // 4))
    assert 0.05 < frac < 0.4                                          # wire present, mostly transparent holes
