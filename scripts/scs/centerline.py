"""Phase S3 seam — turn a parsed SCS region into the local-metre centerline the mesh builder eats.

This is where the "reuse the existing back-half" thesis becomes concrete. The GPS pipeline goes
``centerline.geojson (lon/lat) -> projection -> centerline.local.json (ENU metres) -> ribbon``.
SCS map coordinates are *already* planar metres, so we skip the geographic projection entirely and
emit ``centerline.local.json`` directly — then ``scripts.geometry.ribbon.road_ribbon`` builds the
1ROAD mesh from it unchanged.

A region is an open network; the existing mesh path is built around one centerline, so here we take
a single **route** (an ordered list of road names → one stitched polyline), which is exactly the
"freeroam + carved routes as layouts" model. Width comes from each road's ``road_look`` cross-section.

Map-plane convention: region.geojson coordinates are ``[mx, my]`` in SCS metres (mx≈east, my≈north),
with optional per-vertex elevation as a 3rd coordinate. We map ``(mx, my, elev) -> (x_east, y_up,
z_north)`` about the route centroid. True-north alignment of the SCS map is a later refinement
(``true_north_rotation_deg`` is left null), and does not affect the self-consistent mesh.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from scripts.config import load_config

MapPt = tuple[float, float]  # (mx, my) SCS metres
SPACING_M = 3.0  # match the GPS pipeline's resample spacing


def _dist(a: MapPt, b: MapPt) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def resample_route(pts: list[MapPt], attrs: dict[str, list[float]], spacing: float = SPACING_M
                   ) -> tuple[list[MapPt], dict[str, list[float]]]:
    """Arc-length resample a metric polyline to even ``spacing``; linearly interpolate each attr.

    ``attrs`` holds parallel per-vertex values (e.g. elevation, width) carried onto the new points.
    """
    n = len(pts)
    if n < 2:
        return [tuple(p) for p in pts], {k: [float(x) for x in v] for k, v in attrs.items()}
    out: list[MapPt] = [tuple(pts[0])]
    oa = {k: [float(v[0])] for k, v in attrs.items()}
    acc = 0.0  # distance since the last emitted point
    for i in range(n - 1):
        a, b = tuple(pts[i]), tuple(pts[i + 1])
        seg = _dist(a, b)
        if seg == 0:
            continue
        d = 0.0  # distance travelled into this segment
        while acc + (seg - d) >= spacing:
            d += spacing - acc
            t = d / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            for k, v in attrs.items():
                oa[k].append(float(v[i]) + (float(v[i + 1]) - float(v[i])) * t)
            acc = 0.0
        acc += seg - d
    if out[-1] != tuple(pts[-1]):
        out.append(tuple(pts[-1]))
        for k, v in attrs.items():
            oa[k].append(float(v[-1]))
    return out, oa


def local_frame(pts: list[MapPt], elev: list[float]) -> tuple[MapPt, float]:
    """Origin for the local frame: horizontal centroid + lowest elevation (Y=0 at the low point)."""
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return (cx, cy), (min(elev) if elev else 0.0)


def to_local_xyz(pts: list[MapPt], elev: list[float], origin: MapPt, elev0: float
                 ) -> list[tuple[float, float, float]]:
    """Map (mx, my, elev) about ``origin`` to ENU metres (X=east, Y=up, Z=north)."""
    cx, cy = origin
    return [((mx - cx), (e - elev0), (my - cy)) for (mx, my), e in zip(pts, elev)]


def build_local_centerline(route: list[MapPt], elev: list[float], widths: list[float], *,
                           location: dict | None = None, spacing: float = SPACING_M) -> dict:
    """Resample + project a route to the ``centerline.local.json`` schema the mesh builder reads."""
    pts, oa = resample_route(route, {"elev": elev, "width": widths}, spacing)
    relev, rwidth = oa["elev"], oa["width"]
    origin, elev0 = local_frame(pts, relev)
    xyz = to_local_xyz(pts, relev, origin, elev0)
    xs, ys, zs = [p[0] for p in xyz], [p[1] for p in xyz], [p[2] for p in xyz]
    loc = location or {}
    return {
        "frame": "ENU local metres (X=east, Y=up, Z=north) — from SCS map plane",
        "source": "scs",
        "origin": {"lon": loc.get("lon", 0.0), "lat": loc.get("lat", 0.0), "elev_m": round(elev0, 2),
                   "map_x_m": round(origin[0], 2), "map_y_m": round(origin[1], 2)},
        "true_north_rotation_deg": None,  # SCS map orientation: resolved in a later pass
        "extent_x_m": round(max(xs) - min(xs), 1),
        "extent_z_m": round(max(zs) - min(zs), 1),
        "height_m": round(max(ys) - min(ys), 1),
        "point_count": len(xyz),
        "points_xyz_m": [[round(x, 2), round(y, 2), round(z, 2)] for x, y, z in xyz],
        "widths_m": [round(w, 2) for w in rwidth],
    }


def route_from_region(region: dict, road_order: list[str], road_looks: dict, *,
                      default_width_m: float = 9.0) -> tuple[list[MapPt], list[float], list[float]]:
    """Stitch the named roads from a region.geojson into one polyline + per-vertex elev & width."""
    feats = {f["properties"].get("name"): f for f in region.get("features", [])}
    route: list[MapPt] = []
    elev: list[float] = []
    widths: list[float] = []
    for name in road_order:
        f = feats.get(name)
        if f is None:
            raise KeyError(f"road {name!r} not found in region.geojson")
        look = f["properties"].get("road_look")
        w = road_looks[look].total_width_m if look in road_looks else default_width_m
        for c in f["geometry"]["coordinates"]:
            mx, my = float(c[0]), float(c[1])
            e = float(c[2]) if len(c) > 2 else 0.0
            if route and _dist(route[-1], (mx, my)) < 1e-6:
                continue  # drop the shared junction vertex between consecutive roads
            route.append((mx, my))
            elev.append(e)
            widths.append(w)
    return route, elev, widths


def road_mesh_from_local(local: dict) -> dict:
    """Reuse the existing ribbon sweeper to build the 1ROAD mesh from our local centerline."""
    from scripts.geometry import ribbon  # the back-half we explicitly reuse
    pts = [tuple(p) for p in local["points_xyz_m"]]
    return ribbon.road_ribbon(pts, local["widths_m"])


def write_road_obj(path: Path, mesh: dict, name: str = "1ROAD_main") -> None:
    """Tiny OBJ writer (kept local to avoid coupling to the geometry module's writer)."""
    lines = ["mtllib scs_road.mtl", f"o {name}", "usemtl road"]
    lines += [f"v {x:.3f} {y:.3f} {z:.3f}" for x, y, z in mesh["vertices"]]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in mesh["tris"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_local(project_dir: str | Path, *, build_obj: bool = True) -> tuple[Path, dict]:
    """CLI entry: region.geojson (+ optional road_looks) -> data/centerline.local.json (+ road OBJ)."""
    project_dir = Path(project_dir)
    cfg = load_config(project_dir)
    data = project_dir / "data"
    region = json.loads((data / "region.geojson").read_text(encoding="utf-8"))
    order = cfg.raw.get("route", {}).get("roads") or [f["properties"].get("name") for f in region["features"]]

    looks: dict = {}
    tree = data / "extracted"
    if (tree / "def" / "world").is_dir():
        from scripts.scs.road_looks import parse_road_looks
        looks = parse_road_looks(tree)

    route, elev, widths = route_from_region(region, order, looks, default_width_m=cfg.default_width_m)
    local = build_local_centerline(route, elev, widths, location=cfg.location)
    out = data / "centerline.local.json"
    out.write_text(json.dumps(local), encoding="utf-8")

    stats = {"points": local["point_count"], "extent_x_m": local["extent_x_m"],
             "extent_z_m": local["extent_z_m"], "roads": len(order)}
    if build_obj:
        mesh = road_mesh_from_local(local)
        write_road_obj(data / "scs_road.obj", mesh)
        stats["road_vertices"] = len(mesh["vertices"])
    return out, stats


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.scs.centerline <project-dir>")
    out, stats = build_local(sys.argv[1])
    print(f"wrote {out}")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
