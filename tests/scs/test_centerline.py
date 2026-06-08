"""The seam: region.geojson -> centerline.local.json, and reuse of geometry.ribbon."""

import math

from scripts.scs import centerline as cl
from scripts.scs.road_looks import CrossSection

LOOKS = {
    "hw": CrossSection("hw", lanes_left=2, lanes_right=2, lane_width_m=3.5),  # 14.0
    "loc": CrossSection("loc"),  # 9.0 (default)
}


def _region():
    # An L: road A east along z=0 (x 0..100), road B north at x=100 (z 0..100); they share (100,0).
    a = [[0, 0], [50, 0], [100, 0]]
    b = [[100, 0], [100, 50], [100, 100]]
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "A", "road_look": "hw"},
         "geometry": {"type": "LineString", "coordinates": a}},
        {"type": "Feature", "properties": {"name": "B", "road_look": "loc"},
         "geometry": {"type": "LineString", "coordinates": b}},
    ]}


def test_route_from_region_stitches_and_widths():
    route, elev, widths = cl.route_from_region(_region(), ["A", "B"], LOOKS)
    assert len(route) == 5  # 3 + 3 - 1 shared junction vertex
    assert route[0] == (0.0, 0.0) and route[-1] == (100.0, 100.0)
    assert widths[0] == 14.0 and widths[-1] == 9.0
    assert all(e == 0.0 for e in elev)


def test_resample_even_spacing():
    out, oa = cl.resample_route([(0, 0), (100, 0)], {"w": [10, 10]}, spacing=10.0)
    ds = [math.dist(out[i], out[i + 1]) for i in range(len(out) - 1)]
    assert max(ds) <= 10.0 + 1e-6
    assert abs(out[-1][0] - 100.0) < 1e-6
    assert all(abs(w - 10.0) < 1e-9 for w in oa["w"])


def test_build_local_centerline_schema_and_centering():
    route, elev, widths = cl.route_from_region(_region(), ["A", "B"], LOOKS)
    local = cl.build_local_centerline(route, elev, widths,
                                      location={"lon": -105.0, "lat": 39.7}, spacing=5.0)
    for key in ("frame", "source", "origin", "points_xyz_m", "widths_m",
                "point_count", "true_north_rotation_deg"):
        assert key in local
    assert local["source"] == "scs"
    pts = local["points_xyz_m"]
    assert local["point_count"] == len(pts) == len(local["widths_m"])
    # centered on the centroid -> mean x and z near zero
    assert abs(sum(p[0] for p in pts) / len(pts)) < 0.1
    assert abs(sum(p[2] for p in pts) / len(pts)) < 0.1
    # resampled to ~5 m horizontal spacing
    ds = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2]) for i in range(len(pts) - 1)]
    assert max(ds) <= 5.0 + 0.5
    # widths carried from the road_looks across the stitch
    assert 13.9 <= local["widths_m"][0] <= 14.1
    assert 8.9 <= local["widths_m"][-1] <= 9.1


def test_ribbon_reuse_builds_mesh():
    route, elev, widths = cl.route_from_region(_region(), ["A", "B"], LOOKS)
    local = cl.build_local_centerline(route, elev, widths, spacing=5.0)
    mesh = cl.road_mesh_from_local(local)  # <-- reuses scripts.geometry.ribbon (the back-half)
    n = local["point_count"]
    assert len(mesh["vertices"]) == 2 * n  # open route: left+right vertex per cross-section
    assert len(mesh["tris"]) == 2 * (n - 1)
    assert all(len(t) == 3 for t in mesh["tris"])
