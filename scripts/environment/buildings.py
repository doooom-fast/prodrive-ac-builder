"""Fetch OSM building footprints and extrude them into simple boxes for trackside dressing.

A street circuit reads as a real place mostly because of the buildings around it. OpenStreetMap has
the footprints (and often heights / level counts), so we pull ``way["building"]`` in the route bbox,
keep the ones near the lap, and extrude each into walls + a flat roof. Pure stdlib for the fetch.

Run (caches to data/buildings.geojson):
    python -m scripts.environment.buildings projects/<slug>
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.config import load_config

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "prodrive-ac-builder/0.1 (https://github.com/k10-motorsports/prodrive-ac-builder)"

Vertex = tuple[float, float]


def _height(tags: dict) -> float:
    """Best-effort building height in metres from OSM tags, else a warehouse-ish default."""
    if "height" in tags:
        try:
            return max(2.5, float(str(tags["height"]).split()[0]))
        except ValueError:
            pass
    if "building:levels" in tags:
        try:
            return max(2.5, float(tags["building:levels"]) * 3.2)
        except ValueError:
            pass
    return 6.5


def fetch_buildings(bbox: tuple[float, float, float, float], *, retries: int = 3) -> list[dict]:
    """Return ``[{coords:[(lon,lat)...], height_m, name}]`` for OSM buildings in bbox (S,W,N,E)."""
    s, w, n, e = bbox
    q = (f"[out:json][timeout:120];("
         f'way["building"]({s},{w},{n},{e});'
         f'relation["building"]["type"="multipolygon"]({s},{w},{n},{e});'
         f");out geom tags;")
    body = urllib.parse.urlencode({"data": q}).encode()
    payload: dict = {}
    for attempt in range(retries):
        req = urllib.request.Request(OVERPASS_URL, data=body,
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=200) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    out: list[dict] = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        coords = None
        if el.get("type") == "way" and el.get("geometry"):
            coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
        elif el.get("type") == "relation":
            for m in el.get("members", []):
                if m.get("role") == "outer" and m.get("geometry"):
                    coords = [(g["lon"], g["lat"]) for g in m["geometry"]]
                    break
        if coords and len(coords) >= 4:
            out.append({"coords": coords, "height_m": round(_height(tags), 1),
                        "name": tags.get("name", "")})
    return out


def classify(b: dict, area_m2: float, zone: str | None = None) -> str:
    """Facade family for a building. The OSM zone polygon it sits in (industrial / commercial /
    residential, from environment.geojson) decides first; size/height heuristics fill the gaps."""
    h = b.get("height_m", 6.5)
    if h >= 9.5:
        return "off"
    if zone == "industrial":
        return "ind"
    if zone == "commercial":
        return "com"
    if zone == "residential":
        return "res" if area_m2 < 280 else "com"
    return "ind" if area_m2 >= 850 else ("res" if area_m2 < 160 else "com")


# facade UV strategy per family: (u_tile metres, v mode) — "span" maps base→texture bottom and
# textureheight world metres up (doors/storefronts stay at grade); "floor" tiles every storey.
FACADE_UV = {
    "ind": {"u_tile": 8.0, "v": ("span", 8.5)},
    "com": {"u_tile": 8.0, "v": ("span", 6.5)},
    "off": {"u_tile": 10.0, "v": ("span", 12.0)},
    "res": {"u_tile": 7.0, "v": ("span", 5.5)},
}


def extrude(footprint_xz: list[tuple[float, float]], base_y: float, height: float,
            *, variant: str = "ind", roof_tile: float = 8.0, parapet: float = 0.45) -> dict:
    """Extrude a local-metre footprint into walls + a parapet-sunken flat roof. Wall UVs follow
    the variant's facade mapping so doors/windows sit at grade and don't repeat vertically."""
    pts = footprint_xz[:-1] if footprint_xz[0] == footprint_xz[-1] else list(footprint_xz)
    # normalise winding so the roof fan faces up (AC culls one-sided; OSM rings are either-handed).
    # In the Y-up frame an up-facing fan needs the ring clockwise in maths-(x,z) terms, i.e.
    # negative shoelace sum — reverse when it comes out positive.
    if sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
           for i in range(len(pts))) > 0:
        pts = pts[::-1]
    n = len(pts)
    uvm = FACADE_UV.get(variant, FACADE_UV["ind"])
    u_tile = uvm["u_tile"]
    vmode, vparam = uvm["v"]
    wall_top = base_y + height + parapet

    def v_of(y: float) -> float:
        if vmode == "floor":
            return (y - base_y) / vparam
        return (y - base_y) / max(vparam, height + parapet)

    wv: list = []
    wu: list = []
    wt: list = []
    perim = 0.0
    for i in range(n):
        x0, z0 = pts[i]
        x1, z1 = pts[(i + 1) % n]
        seg = math.hypot(x1 - x0, z1 - z0)
        b = len(wv)
        wv += [(x0, base_y, z0), (x1, base_y, z1), (x1, wall_top, z1), (x0, wall_top, z0)]
        wu += [(perim / u_tile, v_of(base_y)), ((perim + seg) / u_tile, v_of(base_y)),
               ((perim + seg) / u_tile, v_of(wall_top)), (perim / u_tile, v_of(wall_top))]
        wt += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
        # inward-facing copy so walls read from above/inside too (cheap; footprints are small)
        wt += [(b, b + 2, b + 1), (b, b + 3, b + 2)]
        perim += seg
    top = base_y + height
    rv = [(x, top, z) for x, z in pts]  # roof fan (fine for simple footprints), behind the parapet
    ru = [(x / roof_tile, z / roof_tile) for x, z in pts]
    rt = [(0, i, i + 1) for i in range(1, n - 1)]
    return {"walls": {"vertices": wv, "uvs": wu, "tris": wt},
            "roof": {"vertices": rv, "uvs": ru, "tris": rt}}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.environment.buildings <project-dir>")
    project_dir = Path(sys.argv[1])
    cfg = load_config(project_dir)
    route = cfg.raw.get("route", {})
    s, w, n, e = route.get("bbox") or [cfg.lat - 0.01, cfg.lon - 0.013, cfg.lat + 0.01, cfg.lon + 0.013]
    buildings = fetch_buildings((s, w, n, e))
    out = project_dir / "data" / "buildings.geojson"
    out.write_text(json.dumps({"buildings": buildings}), encoding="utf-8")
    heights = [b["height_m"] for b in buildings]
    print(f"wrote {out} — {len(buildings)} buildings"
          + (f", height {min(heights):.0f}-{max(heights):.0f} m" if heights else ""))


if __name__ == "__main__":
    main()
