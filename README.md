# Prodrive AC Builder

Turn a real-world road loop into a playable **Assetto Corsa** track. Feed it a Google Maps
screenshot, a location, and route notes; get back a complete, installable AC track folder — real
geometry from OpenStreetMap, real elevation from USGS 3DEP, accurate sun/lighting, and multiple
layout variants — all reproducible from a single `track.config.json`.

First target: **a street loop in Commerce City, Colorado** (`projects/commerce-city-loop/`).

> **First principle:** the screenshot is a *selection aid, not data*. Precise geometry comes from
> OpenStreetMap via Overpass; hand-drawn KML is used only where the route leaves the real network.

## How it works

| Phase | Task | Where | Skill |
|-------|------|-------|-------|
| 0 | Provide screenshot, location, route notes | Claude Code | — |
| 1 | Identify roads → Overpass/KML → resampled centerline | Mac | `gps-extraction` |
| 2 | Sample USGS 3DEP elevation + margin grid, smooth | Mac | `elevation` |
| 3 | Project lat/lon/elev → local meters, set origin + true north | Mac | `geometry` / `lighting` |
| 4 | Road ribbon (`1ROAD`) + grass heightfield (`GRASS`) + dummies | Mac | `geometry` / `ac` |
| 5 | Material JSON → headless Blender → kn5 + track config | Mac | `ac` / `lighting` |
| 6 | Install, drive, record AI lines, QA | **Windows** | `ac` |
| 7+ | Objects: barriers, kerbs, trees, buildings — iterative | Mac → Win | `ac` |

Phases 1–5 run headless on macOS; phase 6 is the manual loop on Windows (AC + Content Manager + CSP).

## Tech stack

- **Python 3.11+** — pipeline engine (Overpass, projection, sampling, mesh prep)
- **Blender 4.x** + **AC Blender Tools** addon — mesh build & `.kn5` export
- Geospatial: `requests`, `pyproj`, `shapely`, `numpy`, `scipy`, `rasterio`, `trimesh`, `astral`
- **Windows** for driving/QA: Assetto Corsa, Content Manager, Custom Shaders Patch

## Layout

```
scripts/        gps · elevation · geometry · lighting · ac   (pipeline code)
.claude/skills/ gps-extraction · elevation · lighting · ac-track-modding
projects/<slug>/source · data · blender · build · track.config.json
```

See **[CLAUDE.md](CLAUDE.md)** for conventions (units, axes, surface naming, source priority) and
**[docs/PLAN.md](docs/PLAN.md)** for the full project plan and a survey of existing AC track-building
tools and 3D asset sources.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .          # geospatial deps (rasterio needs system GDAL)
# Blender 4.x + AC Blender Tools addon installed separately for kn5 export
```

## Build

```bash
blender --background --python scripts/ac/build_kn5.py -- projects/commerce-city-loop
```

## Status

🚧 Early scaffold. Pipeline modules are stubbed (`NotImplementedError`) and tracked per skill.
