"""Elevation profiling must not treat an open road's two ends as adjacent.

snap_to_ground wrapped its median, its mean, and its grade limiter. On a closed lap that's right.
On a point-to-point stage the ends are different places at different heights — Dragon Tail starts at
1,834 m and finishes at 1,978 m — and wrapping makes the limiter see a 144 m drop across one 3 m
step. It answers by pulling the high end DOWN at the cap rate, which buried the last 200 m of road
up to 48 m under the real ground; the terrain then stood through the deck as a 47 m wall.
"""

from scripts.elevation.heightfield import snap_to_ground


def _ramp(n=400, lo=1834.0, hi=1978.0):
    """An open road climbing steadily from lo to hi — the Dragon Tail shape, simplified."""
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def test_open_profile_keeps_both_ends_on_the_ground():
    # ~1 m of slack: a centered median/mean clamped at a boundary is biased by roughly half its
    # window times the local slope. That is the honest edge effect. 48 m is not.
    z = _ramp()
    out = snap_to_ground(z, spacing_m=3.0, grade_cap_pct=18.0, closed=False)
    assert abs(out[0] - z[0]) < 2.0
    assert abs(out[-1] - z[-1]) < 2.0, f"finish moved {z[-1] - out[-1]:.1f} m off the real ground"


def test_open_profile_never_dives_far_below_the_measured_ground():
    # The limiter is allowed to CUT crests, but a 48 m hole is not a cut.
    z = _ramp()
    out = snap_to_ground(z, spacing_m=3.0, grade_cap_pct=18.0, closed=False)
    assert max(a - b for a, b in zip(z, out)) < 2.0


def test_closed_profile_still_wraps_its_grade_limiter():
    # A lap that ends far above where it started is an error the wrap is supposed to resolve.
    z = _ramp()
    out = snap_to_ground(z, spacing_m=3.0, grade_cap_pct=18.0, closed=True)
    assert out[-1] < z[-1] - 10.0, "closed laps should still be pulled into a continuous loop"


def test_open_profile_still_caps_a_real_cliff():
    # A DEM cliff mid-route must still be limited — the fix must not disable the limiter.
    z = [100.0] * 100 + [200.0] * 100
    out = snap_to_ground(z, spacing_m=3.0, grade_cap_pct=10.0, closed=False)
    steps = [abs(out[i + 1] - out[i]) for i in range(len(out) - 1)]
    assert max(steps) <= 0.10 * 3.0 + 1e-6


def test_open_profile_preserves_a_real_descent():
    # A genuine 30 m drop over 150 m (10%) is under the cap and must survive essentially intact.
    z = [500.0] * 50 + [500.0 - 30.0 * i / 49 for i in range(50)] + [470.0] * 50
    out = snap_to_ground(z, spacing_m=3.0, grade_cap_pct=18.0, closed=False)
    assert (out[0] - out[-1]) > 28.0
