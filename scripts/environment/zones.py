"""Fetch + classify the environment zones around the route — regenerates data/environment.geojson.

This is the reproducibility backfill for the zone layer ``build_env.py`` consumes (the file was
originally produced by a one-off query). Pulls land-use polygons, water, and major-road lines from
Overpass and classifies them into the documented schema:

    {"features": [{"cls": water|highway|green|wetland|industrial|commercial|residential|other,
                   "kind": line|poly, "name": str|null, "coords": [[lon,lat]...]}]}

Run (writes data/environment.geojson):
    python -m scripts.environment.zones projects/<slug>
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.config import load_config

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "prodrive-ac-builder/0.1 (https://github.com/k10-motorsports/prodrive-ac-builder)"


def _classify(tags: dict) -> str | None:
    if tags.get("natural") in ("water",) or "waterway" in tags \
            or tags.get("landuse") in ("basin", "reservoir"):
        return "water"
    if tags.get("natural") == "wetland":
        return "wetland"
    if tags.get("highway") in ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"):
        return "highway"
    if tags.get("landuse") in ("grass", "meadow", "recreation_ground", "village_green", "forest",
                               "farmland", "greenfield", "brownfield", "cemetery", "flowerbed") \
            or tags.get("leisure") in ("park", "nature_reserve", "golf_course", "pitch",
                                       "playground", "garden", "common") \
            or tags.get("natural") in ("scrub", "grassland", "wood", "heath", "shrubbery"):
        return "green"
    if tags.get("landuse") == "industrial":
        return "industrial"
    if tags.get("landuse") in ("commercial", "retail"):
        return "commercial"
    if tags.get("landuse") == "residential":
        return "residential"
    if "landuse" in tags or "leisure" in tags:
        return "other"
    return None


def _query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    bb = f"({s},{w},{n},{e})"
    parts = [
        f'way["landuse"]{bb};', f'way["leisure"]{bb};',
        f'way["natural"~"^(water|wetland|scrub|grassland|wood|heath|shrubbery)$"]{bb};',
        f'way["waterway"]{bb};',
        f'relation["natural"="water"]{bb};', f'relation["landuse"]{bb};',
        f'way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link)$"]{bb};',
    ]
    return f"[out:json][timeout:180];({''.join(parts)});out geom tags;"


def fetch_zones(bbox: tuple[float, float, float, float], *, retries: int = 3) -> list[dict]:
    body = urllib.parse.urlencode({"data": _query(bbox)}).encode()
    payload: dict = {}
    for attempt in range(retries):
        req = urllib.request.Request(OVERPASS_URL, data=body,
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    feats = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        cls = _classify(tags)
        if cls is None:
            continue
        rings = []
        if el.get("type") == "way" and el.get("geometry"):
            rings = [el["geometry"]]
        elif el.get("type") == "relation":
            rings = [m["geometry"] for m in el.get("members", [])
                     if m.get("role") == "outer" and m.get("geometry")]
        for ring in rings:
            coords = [(g["lon"], g["lat"]) for g in ring]
            closed = len(coords) >= 4 and coords[0] == coords[-1]
            kind = "line" if ("highway" in tags or ("waterway" in tags and not closed)) else "poly"
            feats.append({"cls": cls, "kind": kind, "name": tags.get("name"), "coords": coords})
    return feats


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.environment.zones <project-dir>")
    project_dir = Path(sys.argv[1])
    cfg = load_config(project_dir)
    s, w, n, e = cfg.raw.get("route", {}).get("bbox") or \
        [cfg.lat - 0.01, cfg.lon - 0.013, cfg.lat + 0.01, cfg.lon + 0.013]
    # pad beyond the route bbox: the freeway corridors and creek greens that dress the view
    # sit just outside it (the I-70 corridor is south of the route's southern edge)
    pad = float(cfg.raw.get("environment", {}).get("zone_margin_deg", 0.005))
    s, w, n, e = s - pad, w - pad * 1.3, n + pad, e + pad * 1.3
    feats = fetch_zones((s, w, n, e))
    out = project_dir / "data" / "environment.geojson"
    out.write_text(json.dumps({"features": feats}), encoding="utf-8")
    from collections import Counter
    counts = Counter(f["cls"] for f in feats)
    print(f"wrote {out} — " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
