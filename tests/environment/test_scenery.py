"""Geometry invariants for the scenery dressing helpers in scripts/environment/build_env.

Plain ``test_*`` functions (no pytest fixtures) so tests/run_tests.py can discover them under the
dependency-free system python. Covers the power-line generator (poles + sagging cables) added for the
industrial Commerce City look — there was no coverage for build_env before.
"""

from __future__ import annotations

from scripts.environment.build_env import _utility_pole, _wire


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
