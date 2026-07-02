"""Elevation for a road NETWORK (freeroam), not a single lap.

Samples USGS 3DEP along EVERY edge of ``data/network.geojson`` (so each street carries real z), smooths
each edge open-ended, and samples a coarse terrain grid over the whole network bbox for the ground.

Outputs (data/):
  - network.elevation.json  — per-edge {id, z_raw_m, z_smooth_m}
  - heightfield.npy + heightfield.meta.json — terrain grid over the bbox (row 0 = north)
  - elevation_profile.svg   — quick min/max banding preview

Reuses the 3DEP batch sampler and the .npy writer from the single-loop tool. Stdlib only.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.elevation import usgs_3dep  # noqa: E402
from scripts.elevation.heightfield import smooth_profile, smooth_open, write_npy  # noqa: E402

GRID_SPACING_M = 55.0     # coarse landscape grid (upsampled near roads at mesh time)
GRID_MARGIN_M = 220.0
MEDIAN_M = 33.0
MEAN_M = 45.0
MAX_GRADE = 0.05          # cap road slope at 5% — no "narnia" launches, and a real mountain climb (e.g.
                          # the compressed grade UP to Aspen) becomes a gentle, drivable grade.


def _smooth_edge(z_raw, spacing_m):
    """Open-ended de-spike + smooth for one edge (median kills DEM notches at over/underpasses)."""
    n = len(z_raw)
    if n < 3:
        return list(z_raw)
    mw = max(3, round(MEDIAN_M / spacing_m)) | 1
    h = mw // 2
    med = [sorted(z_raw[max(0, i - h):min(n, i + h + 1)])[(min(n, i + h + 1) - max(0, i - h)) // 2]
           for i in range(n)]
    sw = max(3, round(MEAN_M / spacing_m)) | 1
    sm = smooth_open(med, sw)
    # grade cap: clamp consecutive-vertex slope so no road exceeds MAX_GRADE. Turns steep real terrain
    # (mountain spokes) into gentle drivable grades and removes any residual spike -> no launches.
    cap = MAX_GRADE * spacing_m
    out = [sm[0]]
    for i in range(1, len(sm)):
        dz = max(-cap, min(cap, sm[i] - out[-1]))
        out.append(out[-1] + dz)
    return out


def build(project_dir: str | Path) -> dict:
    proj = Path(project_dir)
    data = proj / "data"
    fc = json.loads((data / "network.geojson").read_text())
    F = fc["features"]
    spacing = float(fc["properties"].get("resample_m", 4.0))

    # --- per-edge elevation: one big batched fetch for all edge vertices, then split back ----
    flat_pts = []
    spans = []
    for f in F:
        c = f["geometry"]["coordinates"]
        spans.append((len(flat_pts), len(c)))
        flat_pts.extend((lon, lat) for lon, lat in c)
    print(f"sampling 3DEP for {len(flat_pts)} edge vertices across {len(F)} edges ...")
    z_all = usgs_3dep.sample_points(flat_pts)

    edges_elev = []
    zmin, zmax = 1e9, -1e9
    for f, (off, ln) in zip(F, spans):
        zr = z_all[off:off + ln]
        zs = _smooth_edge(zr, spacing)
        zmin = min(zmin, min(zs)); zmax = max(zmax, max(zs))
        edges_elev.append({"id": f["properties"]["id"], "z_raw_m": [round(v, 2) for v in zr],
                           "z_smooth_m": [round(v, 2) for v in zs]})
    (data / "network.elevation.json").write_text(json.dumps({
        "spacing_m": spacing, "median_m": MEDIAN_M, "mean_m": MEAN_M,
        "edge_count": len(F), "z_min_m": round(zmin, 1), "z_max_m": round(zmax, 1),
        "edges": edges_elev,
    }), encoding="utf-8")

    # --- coarse terrain grid over the whole bbox (config can OVERRIDE to include peaks + the coast) ----
    lons = [c[0] for f in F for c in f["geometry"]["coordinates"]]
    lats = [c[1] for f in F for c in f["geometry"]["coordinates"]]
    midlat = (min(lats) + max(lats)) / 2
    from scripts.config import load_config  # noqa: E402
    terr = (load_config(proj).raw.get("scenery", {}) or {}).get("terrain", {}) or {}
    if terr.get("bbox_swne"):
        s, w, n, e = terr["bbox_swne"]
        print(f"terrain bbox OVERRIDE from config: {terr['bbox_swne']}")
    else:
        mlat = GRID_MARGIN_M / 111_000.0
        mlon = GRID_MARGIN_M / (111_000.0 * math.cos(math.radians(midlat)))
        s, w, n, e = min(lats) - mlat, min(lons) - mlon, max(lats) + mlat, max(lons) + mlon
    gy = GRID_SPACING_M / 111_000.0
    gx = GRID_SPACING_M / (111_000.0 * math.cos(math.radians(midlat)))
    ny = int((n - s) / gy) + 1
    nx = int((e - w) / gx) + 1
    points = [(w + i * gx, n - j * gy) for j in range(ny) for i in range(nx)]
    # NEAR-ROAD MASK: only query USGS for grid cells within BUFFER of a road. On a wide multi-spoke map
    # (compressed I-70 E/W + I-25 S) the full bbox is mostly empty land far from any road, and those far
    # cells are pruned from the mesh anyway (build_network_mesh grass corridor-mask, 500 m). Sampling only
    # near-road cells keeps this from ballooning into millions of USGS requests; far cells fill flat.
    BUFFER_M = 700.0
    from collections import defaultdict
    bdlat = BUFFER_M / 111_000.0
    bdlon = BUFFER_M / (111_000.0 * math.cos(math.radians(midlat)))
    rb = defaultdict(list)
    for lo, la in flat_pts:
        rb[(int(lo / bdlon), int(la / bdlat))].append((lo, la))

    def _near_road(lo, la):
        ci, cj = int(lo / bdlon), int(la / bdlat)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for rlo, rla in rb.get((ci + di, cj + dj), ()):
                    if abs(lo - rlo) <= bdlon and abs(la - rla) <= bdlat:
                        return True
        return False
    sample_idx = [k for k, (lo, la) in enumerate(points) if _near_road(lo, la)]
    print(f"sampling terrain grid {nx}x{ny} @ {GRID_SPACING_M}m — {len(sample_idx)}/{len(points)} "
          f"near-road cells (rest filled flat) ...")
    sampled = usgs_3dep.sample_points([points[k] for k in sample_idx])
    fill = min(sampled) if sampled else float(round(zmin, 1))
    flat = [fill] * len(points)
    for k, z in zip(sample_idx, sampled):
        flat[k] = z
    grid = [flat[j * nx:(j + 1) * nx] for j in range(ny)]
    write_npy(data / "heightfield.npy", grid)
    meta = {"bbox_swne": [round(s, 6), round(w, 6), round(n, 6), round(e, 6)],
            "nx": nx, "ny": ny, "spacing_m": GRID_SPACING_M, "margin_m": GRID_MARGIN_M, "row0": "north"}
    (data / "heightfield.meta.json").write_text(json.dumps(meta), encoding="utf-8")

    stats = {"z_min_m": round(zmin, 1), "z_max_m": round(zmax, 1),
             "range_m": round(zmax - zmin, 1), "grid": f"{nx}x{ny}@{GRID_SPACING_M}m"}
    print("network elevation done:", stats)
    return stats


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "projects/san-diego-cruise")
