"""Phase 1b: turn config-declared side streets into drivable connector roads on the SAME kn5.

The loop is one closed centerline; "filling in the neighbourhood" means adding real streets that branch
off it. Each is declared in ``track.config.json`` under ``route.connectors_kml`` and pulled from one of the
Google My Maps exports, projected into the loop's exact local frame (shared origin, UN-mirrored — build_mesh
applies mirror_x), with elevation sampled from the SAME heightfield the grass uses so the road sits on the
real ground. Output is ``data/connectors.local.json``, which build_mesh ribbons as ``1ROAD_<name>`` (the grass
corridor conforms around them). Reproducible: re-run to regenerate byte-for-byte from config + KML + terrain.

    "route": { "connectors_kml": [
        {"name": "cowles_mountain_blvd", "kml": "../san-diego-cruise/source/San Diego 1.kmz",
         "match": "Cowles Mountain Blvd", "width_m": 10.0}
    ]}

    python -m scripts.gps.connectors_from_kml projects/san-diego-loop
"""

from __future__ import annotations

import json
import math
import re
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET


OVERPASS = "https://overpass-api.de/api/interpreter"


def _strip(tag: str) -> str:
    return re.sub(r"\{.*?\}", "", tag)


def _osm_way_line(road_name: str, bbox: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    """Fetch a named road from OSM and stitch its ways into ONE ordered lon/lat polyline. Cleaner than a
    Google-Directions route (no doubling-back), but a divided arterial comes back as many segments, so
    greedily chain ways by shared endpoints (~10 m) extending both ends from the longest seed."""
    import urllib.request
    import urllib.parse
    s, w, n, e = bbox
    q = (f'[out:json][timeout:60];way["name"="{road_name}"]["highway"]'
         f'({s},{w},{n},{e});out geom;')
    req = urllib.request.Request(OVERPASS, data=("data=" + urllib.parse.quote(q)).encode(),
                                 headers={"User-Agent": "prodrive-ac-builder/1.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=120).read())
    ways = [[(p["lon"], p["lat"]) for p in wy["geometry"]]
            for wy in d.get("elements", []) if wy.get("type") == "way" and "geometry" in wy]
    if not ways:
        return []
    eps2 = (10.0 / 111_000.0) ** 2

    def d2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    chain = ways.pop(max(range(len(ways)), key=lambda i: len(ways[i])))   # seed with the longest single way
    grew = True
    while grew and ways:
        grew = False
        for at_tail in (True, False):
            end = chain[-1] if at_tail else chain[0]
            best = None
            for i, sg in enumerate(ways):
                for pt, order in ((sg[0], sg), (sg[-1], sg[::-1])):
                    dd = d2(end, pt)
                    if dd < eps2 and (best is None or dd < best[0]):
                        best = (dd, i, order)
            if best:
                _, i, order = best
                ways.pop(i)
                chain = (chain + order[1:]) if at_tail else (order[::-1][:-1] + chain)
                grew = True
    return chain


def _load_kml_text(p: Path) -> str:
    if p.suffix.lower() == ".kmz":
        z = zipfile.ZipFile(p)
        name = next(x for x in z.namelist() if x.endswith(".kml"))
        return z.read(name).decode("utf-8", "replace")
    return p.read_text(encoding="utf-8", errors="replace")


def _placemark_line(kml_path: Path, match: str) -> list[tuple[float, float]]:
    """The longest LineString whose Placemark name contains ``match`` (case-insensitive)."""
    root = ET.fromstring(_load_kml_text(kml_path))
    best: list[tuple[float, float]] = []
    for pm in root.iter():
        if _strip(pm.tag) != "Placemark":
            continue
        nm = ""
        for c in pm:
            if _strip(c.tag) == "name":
                nm = (c.text or "").strip()
        if match.lower() not in nm.lower():
            continue
        for el in pm.iter():
            if _strip(el.tag) == "coordinates":
                pts = [tuple(map(float, t.split(",")[:2])) for t in (el.text or "").split() if "," in t]
                if len(pts) > len(best):
                    best = pts
    return best


def _meters_per_degree(lat: float) -> tuple[float, float]:
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    return m_lon, m_lat


def build(project_dir: str | Path) -> dict:
    project = Path(project_dir)
    data = project / "data"
    cfg = json.loads((project / "track.config.json").read_text())
    specs = cfg.get("route", {}).get("connectors_kml", [])
    if not specs:
        print("[connectors] no route.connectors_kml in config — nothing to do")
        return {"connectors": 0}

    local = json.loads((data / "centerline.local.json").read_text())
    lon0, lat0 = local["origin"]["lon"], local["origin"]["lat"]
    elev0 = local["origin"]["elev_m"]
    m_lon, m_lat = _meters_per_degree(lat0)

    # Heightfield sampler — index the SAME grid the grass is built from (bbox_swne, nx x ny), bilinear.
    grid = json.loads((data / "heightfield.npy.json").read_text()) if (data / "heightfield.npy.json").exists() else None
    if grid is None:
        import numpy as np  # noqa
        grid = np.load(data / "heightfield.npy").tolist()
    meta = json.loads((data / "heightfield.meta.json").read_text())
    s, w, n, e = meta["bbox_swne"]
    ny, nx = len(grid), len(grid[0])
    gx = (e - w) / (nx - 1)
    gy = (n - s) / (ny - 1)

    def sample_elev(lon: float, lat: float) -> float:
        fi = min(max((lon - w) / gx, 0.0), nx - 1.0001)
        fj = min(max((lat - s) / gy, 0.0), ny - 1.0001)
        i0, j0 = int(fi), int(fj)
        ti, tj = fi - i0, fj - j0
        g = grid
        top = g[j0][i0] * (1 - ti) + g[j0][i0 + 1] * ti
        bot = g[j0 + 1][i0] * (1 - ti) + g[j0 + 1][i0 + 1] * ti
        return top * (1 - tj) + bot * tj

    from scripts.elevation.heightfield import smooth_profile

    loop = local["points_xyz_m"]   # loop centreline in UN-mirrored local metres (x, y, z)

    def nearest_loop(pt):
        b = min(loop, key=lambda q: (q[0] - pt[0]) ** 2 + (q[2] - pt[2]) ** 2)
        return math.hypot(b[0] - pt[0], b[2] - pt[2]), b

    def conform_to_roads(pts, roads, near_m=45.0):
        """Where a connector passes NEAR an already-placed road, pull its height to that road's — so a
        CROSSING becomes a flat, drivable intersection instead of a cliff (the raw terrain sample sent
        connectors 150 m up over hills next to the loop). Weight by proximity (squared, so it stays glued
        to road height through the whole junction), fading to the connector's own grade by ``near_m``."""
        rpts = [q for road in roads for q in road]               # full resolution — don't miss a crossing
        for p in pts:
            best_d, best_y = near_m * near_m, None
            for q in rpts:
                d2 = (p[0] - q[0]) ** 2 + (p[2] - q[2]) ** 2
                if d2 < best_d:
                    best_d, best_y = d2, q[1]
            if best_y is not None:
                wgt = (best_d / (near_m * near_m)) ** 0.75        # 0 on the road -> 1 at near_m, firm pull
                p[1] = p[1] * wgt + best_y * (1 - wgt)

    def clip_road(line, spec):
        """Clip a long OSM road around its loop-junction. ``span_km`` keeps BOTH arms (a through-road that
        crosses the loop, e.g. Jackson both ways); ``target``+``max_km`` keeps ONE arm toward a point;
        ``full`` keeps the whole way (a short cross-street that links two already-placed connectors)."""
        if not line or spec.get("full"):
            return line
        ji = min(range(len(line)), key=lambda i: nearest_loop([(line[i][0] - lon0) * m_lon, 0,
                                                               (line[i][1] - lat0) * m_lat])[0])

        def walk(step, limit_m):
            out, acc, i = [line[ji]], 0.0, ji
            while 0 <= i + step < len(line) and acc < limit_m:
                a, b = line[i], line[i + step]
                acc += math.hypot((b[0] - a[0]) * m_lon, (b[1] - a[1]) * m_lat)
                out.append(b); i += step
            return out
        span = spec.get("span_km")
        if span:                                             # keep both arms through the junction
            return walk(-1, span * 1000)[::-1][:-1] + walk(1, span * 1000)
        max_km = float(spec.get("max_km", 1.5))
        target = spec.get("target")
        fwd, bwd = walk(1, max_km * 1000), walk(-1, max_km * 1000)
        tx, tz = ((target[0] - lon0) * m_lon, (target[1] - lat0) * m_lat) if target else (0, 0)
        end = lambda seg: ((seg[-1][0] - lon0) * m_lon - tx) ** 2 + ((seg[-1][1] - lat0) * m_lat - tz) ** 2
        return fwd if (target and end(fwd) < end(bwd)) or (not target and len(fwd) >= len(bwd)) else bwd

    placed_roads = [loop]                                        # conform each new connector to these

    def nearest_placed(pt):
        """Nearest point over the loop AND every already-placed connector — so a cross-street can weld to
        Jackson/Baltimore, not only the loop."""
        best_d, best_q = 1e18, None
        for road in placed_roads:
            for q in road:
                d = (pt[0] - q[0]) ** 2 + (pt[2] - q[2]) ** 2
                if d < best_d:
                    best_d, best_q = d, q
        return math.sqrt(best_d), best_q

    out_connectors = []
    for spec in specs:
        if spec.get("osm"):                                      # clean named road straight from OSM
            line = _osm_way_line(spec["osm"], tuple(spec.get("fetch_bbox", [s, w, n, e])))
            line = clip_road(line, spec)
            if not line:
                print(f"[connectors] WARNING: no OSM way named {spec['osm']!r}")
                continue
        else:
            kml_path = (project / spec["kml"]).resolve()
            line = _placemark_line(kml_path, spec["match"])
            if not line:
                print(f"[connectors] WARNING: no placemark matching {spec['match']!r} in {kml_path.name}")
                continue
        # clip to the terrain bbox (drop any tail that leaves the sampled ground)
        line = [(lon, lat) for lon, lat in line if s <= lat <= n and w <= lon <= e]
        # project to UN-mirrored local metres (x east, z north); y from the shared heightfield
        pts = [[(lon - lon0) * m_lon, sample_elev(lon, lat) - elev0, (lat - lat0) * m_lat]
               for lon, lat in line]
        # SMOOTH the grade: a connector is a street, not the racing line. Raw terrain sampling sends it
        # up every hill and DEM spike (Fletcher hit 214 m over a hilltop next to the 16 m loop). A median
        # deletes the spikes; a wide mean flattens hills to a gentle, drivable grade.
        if len(pts) >= 5:
            step_m = max(1.0, sum(math.dist(pts[i][::2], pts[i - 1][::2])
                                  for i in range(1, len(pts))) / (len(pts) - 1))
            zs = smooth_profile([p[1] for p in pts], spacing_m=step_m, median_m=80.0, mean_m=160.0)
            for p, zz in zip(pts, zs):
                p[1] = zz
        # Orient so the end that JOINS the loop is LAST, then snap+blend it flush. A Google-directions
        # line ends at an address, not a junction, so without this the branch floats ~tens of m off the
        # loop with an elevation step (unreachable / a wall). Bridge the small gap to the nearest loop
        # point and taper the branch's terrain-sampled height to the loop road height over ``blend_m``,
        # so you can actually turn onto it and there's no bump at the mouth. The far end stays a dead-end
        # spur (drive up + back).
        # Find where the connector comes CLOSEST to the loop — anywhere along it, not just an endpoint.
        # A "Directions" round-trip (e.g. Fletcher Pkwy, 8285 -> 8285) has both ENDS at the same address
        # far from the loop, but its MIDDLE crosses right by it; an out-and-back spur (Cowles) is closest
        # at an end. Handling both: pick the min-gap vertex, blend the connector's terrain height toward
        # the loop road height in a window around it (kills the step at the crossing), and only WELD a
        # vertex onto the loop centreline when the closest point is an END with a real gap (a spur mouth).
        blend_m = 90.0
        gi = min(range(len(pts)), key=lambda i: nearest_placed(pts[i])[0])
        gap, join = nearest_placed(pts[gi])
        is_end = gi <= 1 or gi >= len(pts) - 2
        RIBBON_OVERLAP_M = 12.0    # within this, the two road ribbons already overlap — no weld needed
        if gap <= 120.0:
            if is_end and gap > RIBBON_OVERLAP_M:
                if gi <= 1:
                    pts.insert(0, [join[0], join[1], join[2]]); gi = 0
                else:
                    pts.append([join[0], join[1], join[2]]); gi = len(pts) - 1
                gap = 0.0
            # blend Y toward the loop height outward from the junction vertex in BOTH directions
            for step in (1, -1):
                acc = 0.0; k = gi
                while 0 <= k + step < len(pts):
                    acc += math.dist(pts[k + step][::2], pts[k][::2])
                    if acc >= blend_m:
                        break
                    t = acc / blend_m
                    pts[k + step][1] = pts[k + step][1] * t + join[1] * (1 - t)
                    k += step
            pts[gi][1] = join[1]
            note = f"joined loop at {'end' if is_end else 'mid-street'} (gap {gap:.0f} m, blended {blend_m:.0f} m)"
        else:
            note = f"NOT joined (nearest loop {gap:.0f} m) — floating spur, SKIPPED"
            continue
        # Keep it a STREET, not a mountain road: clamp each point to within ±BAND m of the nearest loop
        # point's height. A "Directions" route can detour up a hill (Fletcher hit 212 m next to the 16 m
        # loop); a suburban connector should hug the neighbourhood grade. Do this BEFORE conforming so the
        # crossing-flatten has the final say at junctions.
        BAND = 20.0
        for p in pts:
            _lg, lp = nearest_loop(p)
            p[1] = max(lp[1] - BAND, min(lp[1] + BAND, p[1]))
        # Smooth the clamp shoulders, THEN flatten crossings last (so junctions stay level). near_m is
        # wide so the approach to a lower road ramps gradually instead of dropping off a cliff.
        if len(pts) >= 5:
            zf = smooth_profile([p[1] for p in pts], spacing_m=step_m, median_m=55.0, mean_m=110.0)
            for p, zz in zip(pts, zf):
                p[1] = zz
        conform_to_roads(pts, placed_roads, near_m=85.0)
        placed_roads.append([tuple(p) for p in pts])
        width = float(spec.get("width_m", 10.0))
        out_connectors.append({"name": spec["name"], "points_xyz_m": [[round(c, 3) for c in p] for p in pts],
                               "widths_m": [width] * len(pts)})
        length = sum(math.dist(pts[i][::2], pts[i - 1][::2]) for i in range(1, len(pts)))
        print(f"[connectors] {spec['name']}: {len(pts)} pts, {length/1000:.2f} km, width {width} m — {note}")

    (data / "connectors.local.json").write_text(json.dumps({"connectors": out_connectors}), encoding="utf-8")
    print(f"[connectors] wrote data/connectors.local.json ({len(out_connectors)} connectors)")
    return {"connectors": len(out_connectors)}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.gps.connectors_from_kml <project-dir>")
    build(sys.argv[1])


if __name__ == "__main__":
    main()
