"""Two-corner north-up affine: exact round-trip, inverse, and a sane ground scale."""

from scripts.aerial import georef


def test_affine_round_trips_control_points():
    p1_px, p1_ll = (100.0, 800.0), (-104.9501, 40.04498)
    p2_px, p2_ll = (1000.0, 1600.0), (-104.94607, 40.03976)
    p = georef.affine_from_corners(p1_px, p1_ll, p2_px, p2_ll)
    for px, ll in ((p1_px, p1_ll), (p2_px, p2_ll)):
        lon, lat = georef.to_lonlat(p, *px)
        assert abs(lon - ll[0]) < 1e-9 and abs(lat - ll[1]) < 1e-9


def test_to_px_is_inverse_of_to_lonlat():
    p = georef.affine_from_corners((0.0, 0.0), (-105.0, 40.05), (1200.0, 1900.0), (-104.94, 40.0))
    lon, lat = georef.to_lonlat(p, 640.0, 480.0)
    x, y = georef.to_px(p, lon, lat)
    assert abs(x - 640.0) < 1e-6 and abs(y - 480.0) < 1e-6


def test_meters_per_pixel_is_positive_and_plausible():
    # ~0.0046 deg lon over 900 px at 40N ≈ 0.42 m/px.
    p = georef.affine_from_corners((100.0, 800.0), (-104.9501, 40.04498),
                                   (1000.0, 1600.0), (-104.94607, 40.03976))
    mx, my = georef.meters_per_pixel(p, 40.0423)
    assert 0.2 < mx < 0.8 and 0.2 < my < 0.8


def test_degenerate_corners_rejected():
    try:
        georef.affine_from_corners((0.0, 0.0), (-105.0, 40.0), (0.0, 100.0), (-104.9, 40.0))
    except ValueError:
        return
    raise AssertionError("expected ValueError for corners sharing an x coordinate")
