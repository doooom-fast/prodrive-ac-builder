"""Build the real-world seed for *1978*: route spine + elevation + landmarks, in ENU meters.

Reads ``track.config.json`` (anchors + OSM landmark ids), routes the ordered anchors along the
live OSM road network (Dijkstra over drivable ways), samples USGS 3DEP elevation, projects to
the standard ENU local frame (X=east, Y=up, Z=north), and fetches/projects the landmark regions
(sanctum, water, school, home). Everything a clean checkout needs to regenerate the seed.

Run:  python -m scripts.game.build_seed projects/gala-seed
Then: python -m scripts.game.export_seed projects/gala-seed <game-repo>/seed
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.config import load_config
from scripts.elevation import usgs_3dep
from scripts.elevation.heightfield import (
    HF_MARGIN_M, HF_SPACING_M, CENTERLINE_SPACING_M, build_heightfield, haversine,
    smooth_profile, write_npy,
)
from scripts.geometry.projection import centroid, project_to_local
from scripts.gps.centerline import _feature, polyline_length, resample
from scripts.gps.road_route import route_waypoints
from scripts.trace.osm import OVERPASS_URL, USER_AGENT

Vertex = tuple[float, float]

# smooth_profile smooths a CLOSED loop (wraps around). The seed route is open, so reflect-pad the
# ends with edge values before smoothing and trim after — otherwise the start (home) would be
# blended with the end (school), tens of meters of elevation apart.
_PAD = 40


def _smooth_open(z: list[float], spacing_m: float) -> list[float]:
    padded = [z[0]] * _PAD + list(z) + [z[-1]] * _PAD
    return smooth_profile(padded, spacing_m=spacing_m)[_PAD:_PAD + len(z)]


def _fetch_osm_elements(ids: list[str]) -> dict[str, list[Vertex]]:
    """Fetch OSM ways/relations by id ('way/123') -> closed outline (lon, lat) vertices."""
    parts = []
    for ref in ids:
        kind, num = ref.split("/")
        parts.append(f"{kind}({num});")
    query = f"[out:json][timeout:60];({''.join(parts)});out geom;"
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(4):  # Overpass 504s routinely under load
        req = urllib.request.Request(OVERPASS_URL, data=body,
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(4 * (attempt + 1))
    out: dict[str, list[Vertex]] = {}
    for el in payload.get("elements", []):
        ref = f"{el['type']}/{el['id']}"
        if el["type"] == "way":
            out[ref] = [(g["lon"], g["lat"]) for g in el.get("geometry") or []]
        elif el["type"] == "relation":  # outer ring(s) concatenated
            ring: list[Vertex] = []
            for m in el.get("members", []):
                if m.get("role") == "outer":
                    ring += [(g["lon"], g["lat"]) for g in m.get("geometry") or []]
            out[ref] = ring
    return out


def build(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    data.mkdir(exist_ok=True)
    cfg = load_config(project_dir)

    # --- route: ordered anchors -> on-road path -> resampled spine -----------------------------
    anchors = cfg.raw["route"]["anchors"]
    waypoints = [(a["lon"], a["lat"]) for a in anchors]
    margin = float(cfg.raw["route"].get("graph_margin_m", 600.0))
    path = route_waypoints(waypoints, margin_m=margin)
    spine = resample(path, CENTERLINE_SPACING_M)
    widths = [cfg.default_width_m] * len(spine)
    length_m = polyline_length(spine)

    gj = {"type": "FeatureCollection", "features": [
        _feature("centerline", "full", spine,
                 {"closed": False, "default_width_m": cfg.default_width_m,
                  "widths_m": [round(w, 2) for w in widths], "length_m": round(length_m, 1),
                  "point_count": len(spine),
                  "anchors": [a["name"] for a in anchors]}),
    ]}
    (data / "centerline.geojson").write_text(json.dumps(gj), encoding="utf-8")
    print(f"[seed] route: {length_m/1000:.2f} km, {len(spine)} pts through {len(anchors)} anchors")

    # --- landmarks: fetch OSM outlines + config points ------------------------------------------
    lm_cfg = cfg.raw["landmarks"]
    osm_ids = [v["osm"] for v in lm_cfg.values() if isinstance(v, dict) and "osm" in v]
    outlines = _fetch_osm_elements(osm_ids)
    landmarks: dict[str, dict] = {}
    for name, spec in lm_cfg.items():
        if not isinstance(spec, dict) or ("osm" not in spec and "point" not in spec):
            continue
        if "osm" in spec:
            verts = outlines.get(spec["osm"], [])
            if not verts:
                raise SystemExit(f"[seed] landmark '{name}': no geometry for {spec['osm']}")
            landmarks[name] = {"label": spec.get("label", name), "osm": spec["osm"],
                               "kind": "region", "outline_lonlat": verts}
        else:
            landmarks[name] = {"label": spec.get("label", name), "kind": "point",
                               "point_lonlat": list(spec["point"])}
    (data / "landmarks.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"name": n, "label": lm["label"], "kind": lm["kind"]},
             "geometry": ({"type": "Polygon", "coordinates": [[[lo, la] for lo, la in lm["outline_lonlat"]]]}
                          if lm["kind"] == "region" else
                          {"type": "Point", "coordinates": lm["point_lonlat"]})}
            for n, lm in landmarks.items()],
    }), encoding="utf-8")
    print(f"[seed] landmarks: {', '.join(landmarks)}")

    # --- elevation: profile along the spine + a heightfield covering spine AND landmarks --------
    z_raw = usgs_3dep.sample_points(spine)
    z_smooth = _smooth_open(z_raw, CENTERLINE_SPACING_M)
    dist = [0.0]
    for i in range(1, len(spine)):
        dist.append(dist[-1] + haversine(spine[i - 1], spine[i]))
    (data / "centerline.elevation.json").write_text(json.dumps({
        "spacing_m": CENTERLINE_SPACING_M, "open_route": True, "point_count": len(spine),
        "distance_m": [round(x, 1) for x in dist],
        "z_raw_m": [round(v, 2) for v in z_raw], "z_smooth_m": [round(v, 2) for v in z_smooth],
        "stats": {"min_m": round(min(z_smooth), 1), "max_m": round(max(z_smooth), 1),
                  "route_m": round(dist[-1], 1)},
    }), encoding="utf-8")

    extent: list[Vertex] = list(spine)
    for lm in landmarks.values():
        extent += lm.get("outline_lonlat") or [tuple(lm["point_lonlat"])]
    grid, meta = build_heightfield(extent, HF_SPACING_M, HF_MARGIN_M)
    write_npy(data / "heightfield.npy", grid)
    (data / "heightfield.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"[seed] elevation: {min(z_smooth):.0f}-{max(z_smooth):.0f} m along route; "
          f"heightfield {meta['nx']}x{meta['ny']} @ {HF_SPACING_M} m (covers landmarks)")

    # --- projection: ENU local meters, one origin for everything --------------------------------
    from scripts.geometry import projection
    stats = projection.build(project_dir)
    local = json.loads((data / "centerline.local.json").read_text(encoding="utf-8"))
    origin = (local["origin"]["lon"], local["origin"]["lat"])
    elev0 = local["origin"]["elev_m"]

    lm_local: dict[str, dict] = {}
    for name, lm in landmarks.items():
        pts = lm.get("outline_lonlat") or [tuple(lm["point_lonlat"])]
        # Landmarks are 2D regions/points; Y comes from the heightfield in-engine (drape on import).
        loc = project_to_local(pts, [elev0] * len(pts), origin, elev0)
        lm_local[name] = {"label": lm["label"], "kind": lm["kind"],
                          "points_xz_m": [[round(x, 2), round(z, 2)] for x, _y, z in loc]}
    (data / "landmarks.local.json").write_text(json.dumps({
        "frame": local["frame"], "origin": local["origin"], "y": "drape on heightfield",
        "landmarks": lm_local,
    }), encoding="utf-8")
    print(f"[seed] projected: extent {stats['extent_x_m']} x {stats['extent_z_m']} m, "
          f"height {stats['height_m']} m")
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.game.build_seed projects/<slug>")
    build(sys.argv[1])


if __name__ == "__main__":
    main()
