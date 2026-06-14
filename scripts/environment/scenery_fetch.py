"""Fetch trackside scenery features from OSM — the detail layer beyond zones/buildings.

One Overpass query pulls everything the scenery pass places as real objects: individual trees,
storage tanks/silos (the Commerce City refinery skyline), fences, power lines + towers, railways,
bridge decks, traffic signals / stop signs / crossings, street lamps, and the *named* cross streets
(for street-blade signs at junctions). Classified client-side by tags into one cached geojson.

Run (caches to data/scenery.geojson):
    python -m scripts.environment.scenery_fetch projects/<slug>
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


def _query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    bb = f"({s},{w},{n},{e})"
    parts = [
        f'node["natural"="tree"]{bb};',
        f'way["man_made"~"storage_tank|silo|water_tower"]{bb};',
        f'node["man_made"~"storage_tank|water_tower|chimney|flare"]{bb};',
        f'way["barrier"~"fence|wall"]{bb};',
        f'way["power"~"^(line|minor_line)$"]{bb};',
        f'node["power"~"^(tower|pole)$"]{bb};',
        f'way["railway"="rail"]{bb};',
        f'way["highway"]["bridge"]{bb};',
        f'node["highway"="traffic_signals"]{bb};',
        f'node["highway"="stop"]{bb};',
        f'node["highway"="crossing"]{bb};',
        f'node["highway"="street_lamp"]{bb};',
        f'way["highway"~"^(residential|secondary|tertiary|unclassified|primary)$"]["name"]{bb};',
    ]
    return f"[out:json][timeout:180];({''.join(parts)});out geom tags;"


def fetch(bbox: tuple[float, float, float, float], *, retries: int = 3) -> dict:
    """Run the scenery query and classify elements into the scenery.geojson schema."""
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

    out: dict = {"trees": [], "tanks": [], "fences": [], "power_lines": [], "power_towers": [],
                 "rail": [], "bridges": [], "signals": [], "stops": [], "crossings": [],
                 "street_lamps": [], "roads": []}
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        if el.get("type") == "node":
            pt = (el["lon"], el["lat"])
            if tags.get("natural") == "tree":
                out["trees"].append(pt)
            elif tags.get("power") in ("tower", "pole"):
                out["power_towers"].append({"pt": pt, "kind": tags["power"]})
            elif tags.get("highway") == "traffic_signals":
                out["signals"].append(pt)
            elif tags.get("highway") == "stop":
                out["stops"].append(pt)
            elif tags.get("highway") == "crossing":
                out["crossings"].append(pt)
            elif tags.get("highway") == "street_lamp":
                out["street_lamps"].append(pt)
            elif "man_made" in tags:
                out["tanks"].append({"coords": [pt], "kind": tags["man_made"],
                                     "height_m": _float_tag(tags, "height", 0.0)})
        elif el.get("type") == "way" and el.get("geometry"):
            coords = [(g["lon"], g["lat"]) for g in el["geometry"]]
            if "man_made" in tags:
                out["tanks"].append({"coords": coords, "kind": tags["man_made"],
                                     "height_m": _float_tag(tags, "height", 0.0)})
            elif "barrier" in tags:
                out["fences"].append({"coords": coords, "kind": tags["barrier"]})
            elif tags.get("power"):
                out["power_lines"].append({"coords": coords, "kind": tags["power"]})
            elif tags.get("railway") == "rail":
                out["rail"].append({"coords": coords})
            elif "bridge" in tags and "highway" in tags:
                out["bridges"].append({"coords": coords, "highway": tags["highway"],
                                       "layer": _float_tag(tags, "layer", 1.0)})
            elif "highway" in tags:
                out["roads"].append({"coords": coords, "name": tags.get("name", ""),
                                     "highway": tags["highway"],
                                     "maxspeed": tags.get("maxspeed", "")})
    return out


def _float_tag(tags: dict, key: str, default: float) -> float:
    try:
        return float(str(tags.get(key, default)).split()[0])
    except (ValueError, TypeError):
        return default


def load_or_fetch(project_dir: str | Path, *, force: bool = False) -> dict:
    """Cached scenery features for a project (fetches once, then reads data/scenery.geojson)."""
    project_dir = Path(project_dir)
    cache = project_dir / "data" / "scenery.geojson"
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))
    cfg = load_config(project_dir)
    s, w, n, e = cfg.raw.get("route", {}).get("bbox") or \
        [cfg.lat - 0.01, cfg.lon - 0.013, cfg.lat + 0.01, cfg.lon + 0.013]
    data = fetch((s, w, n, e))
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.environment.scenery_fetch <project-dir> [--force]")
    data = load_or_fetch(sys.argv[1], force="--force" in sys.argv)
    print(f"scenery features: " + ", ".join(f"{k}={len(v)}" for k, v in data.items()))


if __name__ == "__main__":
    main()
