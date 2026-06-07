"""Phase S2 — parse the ``.mbd`` map graph and clip it to the configured region.

Emits two artifacts:
  * ``data/region.geojson`` — road centerlines (LineStrings) tagged with their ``road_look`` template,
    in SCS world coordinates. This is the seam: after resampling it becomes ``data/centerline.geojson``,
    the exact shape ``scripts/geometry`` already consumes.
  * ``data/items.json`` — prefabs, model placements, and terrain items for the asset + junction passes.

The parse itself is delegated to a map-parser binary (truckermudgeon/maps, which already emits
GeoJSON, and/or TruckLib for the item graph); point at it with ``SCS_MAP_PARSER_BIN``. Region
selection and all paths come from ``track.config.json`` — nothing hardcoded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# (x0, z0, x1, z1) in SCS world meters; SCS is X/Z-planar with Y up.
Bbox = tuple[float, float, float, float]


def region_bbox(source: dict[str, Any]) -> Bbox | None:
    """Return the region bbox if ``source.region`` is given as one, else ``None`` (city-list mode)."""
    region = source.get("region", {})
    bbox = region.get("bbox")
    return tuple(bbox) if bbox else None  # type: ignore[return-value]


def clip_features(features: list[dict], bbox: Bbox) -> list[dict]:
    """Keep GeoJSON features with any vertex inside ``bbox`` (pure-Python, parser-agnostic)."""
    x0, z0, x1, z1 = bbox
    lo_x, hi_x = sorted((x0, x1))
    lo_z, hi_z = sorted((z0, z1))

    def inside(pt: list[float]) -> bool:
        return lo_x <= pt[0] <= hi_x and lo_z <= pt[1] <= hi_z

    kept = []
    for feat in features:
        coords = feat.get("geometry", {}).get("coordinates", [])
        flat = coords if coords and isinstance(coords[0][0], (int, float)) else [p for ring in coords for p in ring]
        if any(inside(pt) for pt in flat):
            kept.append(feat)
    return kept


def parse_region(source: dict[str, Any], asset_tree: Path, data_dir: Path) -> tuple[Path, Path]:
    """Parse the map under ``asset_tree``, clip to the region, write region.geojson + items.json."""
    map_dir = asset_tree / "map"
    if not map_dir.is_dir():
        raise FileNotFoundError(f"no map/ directory in asset tree: {asset_tree}")
    data_dir.mkdir(parents=True, exist_ok=True)
    region_geojson = data_dir / "region.geojson"
    items_json = data_dir / "items.json"

    binary = os.environ.get("SCS_MAP_PARSER_BIN")
    if not binary:
        raise RuntimeError("set SCS_MAP_PARSER_BIN (truckermudgeon/maps parser or a TruckLib host)")

    map_name = source.get("map", "usa" if source.get("game") == "ats" else "europe")
    cmd = [binary, "parse", "--map", map_name, "--in", str(map_dir), "--out", str(data_dir)]
    # TODO(scs): the parser emits roads/prefabs/models; normalize its output into the two files
    # below, then `clip_features` to the region bbox. Junction geometry from prefabs is imperfect
    # (see docs) — carry raw prefab refs in items.json for the dedicated prefab pass.
    raise NotImplementedError(f"wire up the map parser subprocess: {' '.join(cmd)}")

    _ = (region_geojson, items_json, json, clip_features, region_bbox)  # interface placeholders
    return region_geojson, items_json
