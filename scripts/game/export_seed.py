"""Export the built seed as the bundle the game repo commits under ``seed/``.

Reads ``projects/<slug>/data/`` (built by ``build_seed``) and writes:

- ``gala_seed.json``  — self-describing: ENU centerline + widths, projection origin, landmarks,
  heightfield metadata, and provenance (this repo's git SHA + config slug/version).
- ``heightfield.r16`` — the terrain grid as uint16 little-endian, row 0 = north, normalized
  ``z = min_m + v * (max_m - min_m) / 65535``. UE-friendly.

The game (``GalaSeedImport``) consumes exactly these two files and nothing else from this repo.

Run:  python -m scripts.game.export_seed projects/gala-seed ../k10-1978/seed
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

from scripts.config import load_config
from scripts.geometry.build_mesh import read_npy


def _git_sha(repo: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def export(project_dir: str | Path, out_dir: str | Path) -> Path:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config(project_dir)

    local = json.loads((data / "centerline.local.json").read_text(encoding="utf-8"))
    landmarks = json.loads((data / "landmarks.local.json").read_text(encoding="utf-8"))
    meta = json.loads((data / "heightfield.meta.json").read_text(encoding="utf-8"))
    grid = read_npy(data / "heightfield.npy")

    zmin = min(min(r) for r in grid)
    zmax = max(max(r) for r in grid)
    span = (zmax - zmin) or 1.0
    buf = bytearray()
    for row in grid:
        for v in row:
            buf += struct.pack("<H", round((v - zmin) / span * 65535))
    (out_dir / "heightfield.r16").write_bytes(bytes(buf))

    bundle = {
        "game": "1978",
        "codename": "Gala",
        "frame": local["frame"],
        "origin": local["origin"],
        "true_north_rotation_deg": local.get("true_north_rotation_deg", 0.0),
        "provenance": {
            "repo": "k10-motorsports/prodrive-ac-builder",
            "git_sha": _git_sha(project_dir),
            "project": cfg.slug,
            "config_version": cfg.version,
            "elevation_source": "USGS 3DEP",
            "roads_source": "OpenStreetMap (ODbL)",
        },
        "centerline": {
            "closed": False,
            "anchors": [a["name"] for a in cfg.raw["route"]["anchors"]],
            "points_xyz_m": local["points_xyz_m"],
            "widths_m": local["widths_m"],
        },
        "landmarks": landmarks["landmarks"],
        "landmarks_y": landmarks["y"],
        "heightfield": {
            "file": "heightfield.r16",
            "encoding": "uint16 LE, row-major, row 0 = north; z_m = min_m + v * (max_m - min_m) / 65535",
            "nx": meta["nx"], "ny": meta["ny"],
            "spacing_m": meta["spacing_m"],
            "bbox_swne": meta["bbox_swne"],
            "min_m": round(zmin, 2), "max_m": round(zmax, 2),
        },
    }
    out = out_dir / "gala_seed.json"
    out.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(f"[seed] exported {out} + heightfield.r16 "
          f"({meta['nx']}x{meta['ny']} @ {meta['spacing_m']} m, {len(buf)//1024} KiB)")
    return out


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: python -m scripts.game.export_seed projects/<slug> <out-dir>")
    export(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
