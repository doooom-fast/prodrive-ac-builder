"""Generate the installable Assetto Corsa track folder (everything except the kn5 + AI).

All layouts share one kn5 and differ only in AC config. Emits, under build/<slug>/:
  models_<layout>.ini, data/surfaces.ini, data/map.ini, map.png, ui/<layout>/ui_track.json,
  ui/<layout>/{preview,outline}.png, ai/<layout>/ (placeholder), README.txt.
The kn5 is produced by Blender (scripts/ac/build_kn5.py); the AI fast_lane is recorded in-game (Windows).

Run:  python -m scripts.ac.track_folder projects/<slug>
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.config import load_config
from scripts.ac import ext_config


# --- AC config files -----------------------------------------------------------

def surfaces_ini() -> str:
    """data/surfaces.ini — physical surfaces keyed to the 1ROAD/1KERB/GRASS mesh prefixes."""
    blocks = [
        ("ROAD",  dict(FRICTION=0.99, DAMPING=0, IS_VALID_TRACK=1, DIRT_ADDITIVE=0, IS_PITLANE=0)),
        ("KERB",  dict(FRICTION=0.92, DAMPING=0, IS_VALID_TRACK=1, DIRT_ADDITIVE=0, IS_PITLANE=0,
                       VIBRATION_GAIN=1.0, VIBRATION_LENGTH=1.5)),
        ("GRASS", dict(FRICTION=0.60, DAMPING=0.1, IS_VALID_TRACK=0, DIRT_ADDITIVE=1, IS_PITLANE=0)),
    ]
    out = []
    for i, (key, p) in enumerate(blocks):
        lines = [f"[SURFACE_{i}]", f"KEY={key}", "WAV=", "WAV_PITCH=0", "FF_EFFECT=0",
                 "SIN_HEIGHT=0", "SIN_LENGTH=0", "BLACK_FLAG_TIME=0"]
        lines += [f"{k}={v}" for k, v in p.items()]
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def ui_track_json(cfg, layout: str, length_m: float, n_pits: int) -> dict:
    return {
        "name": f"{cfg.name}" + ("" if layout == "full" else f" — {layout}"),
        "description": "Real-world street circuit built from OpenStreetMap + USGS 3DEP by "
                       "prodrive-ac-builder. First target: Commerce City, CO.",
        "tags": ["street", "loop", "fictional", "real-roads"],
        "geotags": [f"{cfg.lat}", f"{cfg.lon}"],
        "country": "United States", "city": "Commerce City",
        "length": str(round(length_m)), "width": str(round(cfg.default_width_m)),
        "pitboxes": str(n_pits), "run": "clockwise",
        "author": "prodrive-ac-builder", "version": "0.1", "year": 2026,
    }


def models_ini(kn5_name: str) -> str:
    return f"[MODEL_0]\nFILE={kn5_name}\nPOSITION=0,0,0\nROTATION=0,0,0\n"


# --- minimap / images ----------------------------------------------------------

def _xz(local: dict) -> list[tuple[float, float]]:
    return [(p[0], p[2]) for p in local["points_xyz_m"]]  # (X east, Z north) metres


def _map_params(xz, size: int = 900, margin: int = 28):
    """Square, centered canvas so nothing clips and map.png matches map.ini exactly."""
    xs = [p[0] for p in xz]; zs = [p[1] for p in xz]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    rx, rz = maxx - minx, maxz - minz
    scale = (size - 2 * margin) / max(rx, rz)
    ox, oz = (size - rx * scale) / 2, (size - rz * scale) / 2  # centering offsets (px)
    params = {"WIDTH": size, "HEIGHT": size, "SCALE_FACTOR": round(scale, 6),
              "X_OFFSET": round(ox / scale - minx, 3), "Z_OFFSET": round(oz / scale - minz, 3),
              "MARGIN": margin, "DRAWING_SIZE": 10}
    geom = {"minx": minx, "minz": minz, "maxz": maxz, "scale": scale, "ox": ox, "oz": oz, "S": size}
    return params, geom


def map_ini(params: dict) -> str:
    body = "\n".join(f"{k}={v}" for k, v in params.items())
    return f"[PARAMETERS]\n{body}\n"


def _track_svg(xz, geom, *, stroke: str, width: float, bg: str | None, flip_y: bool = False) -> str:
    minx, minz, maxz, scale, ox, oz, S = (geom[k] for k in ("minx", "minz", "maxz", "scale", "ox", "oz", "S"))

    def px(x, z):
        py = ((maxz - z) if flip_y else (z - minz)) * scale + oz  # flip_y=True → north up (UI); else AC HUD
        return round((x - minx) * scale + ox, 1), round(py, 1)

    pts = " ".join(f"{a},{b}" for a, b in (px(x, z) for x, z in xz))
    rect = f'<rect width="100%" height="100%" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" viewBox="0 0 {S} {S}">'
            f'{rect}<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')


def _rasterize(svg: str, png: Path, size: int) -> bool:
    """qlmanage SVG→PNG (macOS build host). Falls back to writing the .svg if unavailable."""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
            f.write(svg); tmp = f.name
        subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", str(png.parent), tmp],
                       capture_output=True, timeout=30)
        out = png.parent / (Path(tmp).name + ".png")
        if out.exists():
            out.replace(png)
            return True
    except Exception:
        pass
    png.with_suffix(".svg").write_text(svg, encoding="utf-8")
    return False


# --- orchestration -------------------------------------------------------------

def generate(project_dir: str | Path, kn5_name: str | None = None) -> dict:
    project_dir = Path(project_dir)
    cfg = load_config(project_dir)
    local = json.loads((project_dir / "data" / "centerline.local.json").read_text(encoding="utf-8"))
    dummies = json.loads((project_dir / "data" / "dummies.json").read_text(encoding="utf-8")) \
        if (project_dir / "data" / "dummies.json").exists() else {}
    n_pits = sum(1 for k in dummies if k.startswith("AC_PIT_"))
    kn5_name = kn5_name or f"{cfg.slug}.kn5"
    length_m = json.loads((project_dir / "data" / "centerline.geojson").read_text())["features"][0]["properties"]["length_m"]

    out = project_dir / "build" / cfg.slug
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "surfaces.ini").write_text(surfaces_ini(), encoding="utf-8")

    xz = _xz(local)
    params, geom = _map_params(xz)
    (out / "data" / "map.ini").write_text(map_ini(params), encoding="utf-8")
    # HUD minimap — white track, transparent, AC convention (consistent with map.ini)
    _rasterize(_track_svg(xz, geom, stroke="#ffffff", width=params["DRAWING_SIZE"], bg=None, flip_y=False),
               out / "map.png", params["WIDTH"])
    # preview — reuse the Phase-4 3D render (a real view of the track) if present
    render_svg = project_dir / "data" / "track_render.svg"
    preview_src = render_svg.read_text(encoding="utf-8") if render_svg.exists() else \
        _track_svg(xz, geom, stroke="#ff3b30", width=5, bg="#0c1116", flip_y=True)

    layouts = [lo["id"] for lo in cfg.layouts]
    for layout in layouts:
        (out / ("models_%s.ini" % layout)).write_text(models_ini(kn5_name), encoding="utf-8")
        uid = out / "ui" / layout
        uid.mkdir(parents=True, exist_ok=True)
        (uid / "ui_track.json").write_text(json.dumps(ui_track_json(cfg, layout, length_m, n_pits), indent=2),
                                           encoding="utf-8")
        _rasterize(_track_svg(xz, geom, stroke="#e8ecf0", width=3, bg="#0c1116", flip_y=True), uid / "outline.png", params["WIDTH"])
        _rasterize(preview_src, uid / "preview.png", 600)
        aid = out / "ai" / layout
        aid.mkdir(parents=True, exist_ok=True)
        (aid / "README.txt").write_text(
            "fast_lane.ai is recorded in-game (AC + Content Manager, Windows) — see ac-track-modding.\n",
            encoding="utf-8")

    (out / "README.txt").write_text(
        f"{cfg.name} — Assetto Corsa track folder (generated by prodrive-ac-builder).\n\n"
        f"GENERATED HERE: surfaces.ini, map.ini, map.png, models_<layout>.ini, ui/<layout>/*.\n"
        f"STILL NEEDED:\n"
        f"  - {kn5_name}: build with Blender 4.x + AC Blender Tools — `blender --background "
        f"--python scripts/ac/build_kn5.py -- {project_dir}`\n"
        f"  - ai/<layout>/fast_lane.ai: record in-game (Windows).\n"
        f"Install: copy this folder to <AC>/content/tracks/{cfg.slug}/. Validate in Content Manager.\n",
        encoding="utf-8")
    ext_config.generate(project_dir)  # extension/ext_config.ini — CSP GrassFX / water shader / lights
    return {"out": str(out), "layouts": layouts, "length_m": length_m, "n_pits": n_pits,
            "map_px": f"{params['WIDTH']}x{params['HEIGHT']}", "kn5": kn5_name}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.ac.track_folder <project-dir>")
    info = generate(sys.argv[1])
    print(f"wrote track folder → {info['out']}")
    for k, v in info.items():
        if k != "out":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
