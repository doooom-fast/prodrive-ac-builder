"""Render the seed's roads/route/landmarks over real OSM map tiles -> a PNG the owner can read.

The ENU previews show shape, not streets. This stitches OpenStreetMap raster tiles for the seed
bbox (Web Mercator z16-ish) and draws the route (red), network edges (orange), and landmark
outlines on top, so "which streets is that?" has an answer.

Run: python -m scripts.game.map_overlay projects/gala-seed [out.png]
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "prodrive-ac-builder/0.1 (https://github.com/k10-motorsports/prodrive-ac-builder)"
MAX_TILES = 120


def _tile_xy(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    la = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(la)) / math.pi) / 2.0 * n
    return x, y


def _fetch_tile(z: int, x: int, y: int) -> Image.Image:
    req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y),
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGB")


def render(project_dir: str | Path, out_path: str | Path | None = None) -> Path:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    out_path = Path(out_path) if out_path else data / "seed_map.png"

    routes: list[list[tuple[float, float]]] = []   # red: the spine
    edges: list[list[tuple[float, float]]] = []    # orange: network edges
    cl = data / "centerline.geojson"
    if cl.exists():
        gj = json.loads(cl.read_text(encoding="utf-8"))
        routes += [[tuple(c) for c in f["geometry"]["coordinates"]]
                   for f in gj["features"] if f["properties"].get("kind") == "full"]
    net = data / "network.geojson"
    if net.exists():
        gj = json.loads(net.read_text(encoding="utf-8"))
        edges += [[tuple(c) for c in f["geometry"]["coordinates"]]
                  for f in gj["features"] if f["properties"].get("kind") == "edge"]
    sp = data / "spine.geojson"
    if sp.exists():
        gj = json.loads(sp.read_text(encoding="utf-8"))
        routes += [[tuple(c) for c in f["geometry"]["coordinates"]] for f in gj["features"]]

    landmarks: list[tuple[str, str, list[tuple[float, float]]]] = []
    lmp = data / "landmarks.geojson"
    if lmp.exists():
        gj = json.loads(lmp.read_text(encoding="utf-8"))
        for f in gj["features"]:
            g = f["geometry"]
            if g["type"] == "Polygon":
                landmarks.append((f["properties"]["name"], f["properties"]["label"],
                                  [tuple(c) for c in g["coordinates"][0]]))
            else:
                landmarks.append((f["properties"]["name"], f["properties"]["label"],
                                  [tuple(g["coordinates"])]))

    allpts = [p for ln in routes + edges for p in ln] + [p for _n, _l, o in landmarks for p in o]
    if not allpts:
        raise SystemExit("nothing to draw — run build_seed first")
    lons = [p[0] for p in allpts]
    lats = [p[1] for p in allpts]

    # pick the highest zoom that stays under MAX_TILES
    for z in range(17, 11, -1):
        x0, y1 = _tile_xy(min(lons), min(lats), z)
        x1, y0 = _tile_xy(max(lons), max(lats), z)
        tx0, tx1 = int(x0) - 1, int(x1) + 1
        ty0, ty1 = int(y0) - 1, int(y1) + 1
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= MAX_TILES:
            break

    cols, rows = tx1 - tx0 + 1, ty1 - ty0 + 1
    img = Image.new("RGB", (cols * 256, rows * 256), "#ddd")
    for j in range(rows):
        for i in range(cols):
            try:
                img.paste(_fetch_tile(z, tx0 + i, ty0 + j), (i * 256, j * 256))
            except Exception:
                pass  # missing tile -> grey square, still usable
            time.sleep(0.05)

    def px(lon: float, lat: float) -> tuple[float, float]:
        x, y = _tile_xy(lon, lat, z)
        return (x - tx0) * 256, (y - ty0) * 256

    dr = ImageDraw.Draw(img, "RGBA")
    for _n, _lbl, outline in landmarks:
        if len(outline) > 2:
            dr.polygon([px(*p) for p in outline], fill=(212, 175, 55, 70),
                       outline=(160, 120, 20, 255), width=3)
    for ln in edges:
        dr.line([px(*p) for p in ln], fill=(230, 120, 40, 220), width=4)
    for ln in routes:
        dr.line([px(*p) for p in ln], fill=(200, 30, 30, 255), width=6)
    for _n, lbl, outline in landmarks:
        cx = sum(p[0] for p in outline) / len(outline)
        cy = sum(p[1] for p in outline) / len(outline)
        X, Y = px(cx, cy)
        if len(outline) == 1:
            dr.ellipse([X - 8, Y - 8, X + 8, Y + 8], fill=(20, 20, 20, 255),
                       outline=(255, 255, 255, 255), width=2)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 26)
        except Exception:
            font = ImageFont.load_default()
        dr.text((X + 12, Y - 14), lbl, fill=(10, 10, 10, 255), font=font,
                stroke_width=3, stroke_fill=(255, 255, 255, 230))

    dr.text((14, img.height - 34), "map © OpenStreetMap contributors",
            fill=(60, 60, 60, 255), stroke_width=2, stroke_fill=(255, 255, 255, 220))
    img.save(out_path)
    print(f"[seed] map overlay -> {out_path} (z{z}, {cols}x{rows} tiles)")
    return out_path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.game.map_overlay projects/<slug> [out.png]")
    render(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)


if __name__ == "__main__":
    main()
