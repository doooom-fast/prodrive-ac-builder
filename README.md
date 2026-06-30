# Prodrive AC Builder

Turn a real-world road loop into a playable **Assetto Corsa** track. Feed it a Google Maps
screenshot, a location, and route notes; get back a complete, installable AC track folder — real
geometry from OpenStreetMap, real elevation from USGS 3DEP, accurate sun/lighting, and multiple
layout variants — all reproducible from a single `track.config.json`.

First track: **Sand Creek Raceway** — a street loop in Commerce City, Colorado (`projects/sand-creek-raceway/`).

> **First principle:** the screenshot is a *selection aid, not data*. Precise geometry comes from
> OpenStreetMap via Overpass; hand-drawn KML is used only where the route leaves the real network.

## How it works

| Phase | Task | Where | Skill |
|-------|------|-------|-------|
| 0 | Provide screenshot, location, route notes | Claude Code | — |
| 1 | Identify roads → Overpass/KML → resampled centerline | Mac | `gps-extraction` |
| 1-alt | No GPS/OSM data? Trace the asphalt off an aerial screenshot → georeferenced centerline | Mac | `aerial-tracing` |
| 2 | Sample USGS 3DEP elevation + margin grid, smooth | Mac | `elevation` |
| 3 | Project lat/lon/elev → local meters, set origin + true north | Mac | `geometry` / `lighting` |
| 4 | Road ribbon (`1ROAD`) + grass heightfield (`GRASS`) + dummies | Mac | `geometry` / `ac` |
| 5 | Material JSON → headless Blender → kn5 + track config | Mac | `ac` / `lighting` |
| 6 | Install (`scripts.ac.install`, optional), drive, record AI lines, QA | **Windows** | `ac` |
| 7+ | Objects: barriers, kerbs, trees, buildings — iterative | Mac → Win | `ac` |

Phases 1–5 run headless on macOS; phase 6 is the manual loop on Windows (AC + Content Manager + CSP).

## Tech stack

- **Python 3.11+** — pipeline engine (Overpass, projection, sampling, mesh prep)
- **Blender 4.x** + **AC Blender Tools** addon — mesh build & `.kn5` export
- Geospatial: `requests`, `pyproj`, `shapely`, `numpy`, `scipy`, `rasterio`, `trimesh`, `astral`
- **Windows** for driving/QA: Assetto Corsa, Content Manager, Custom Shaders Patch

## Layout

```
scripts/        gps · aerial · elevation · geometry · lighting · ac   (pipeline code)
.claude/skills/ gps-extraction · aerial-tracing · elevation · lighting · ac-track-modding
projects/<slug>/source · data · blender · build · track.config.json
```

See **[CLAUDE.md](CLAUDE.md)** for conventions (units, axes, surface naming, source priority) and
**[docs/PLAN.md](docs/PLAN.md)** for the full project plan and a survey of existing AC track-building
tools and 3D asset sources.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .          # geospatial deps (rasterio needs system GDAL)
# Blender 4.2 + the kn5 export add-on are pinned/vendored — bootstrap fetches them, see Build.
```

## Build

One command runs the whole Mac pipeline (Phases 1–5) for a track, from `track.config.json` to an
installable `.zip`. It pins Blender 4.2 (the add-on's required version) into a stable cache on first
run — no manual Blender install, no ephemeral `/tmp`.

```bash
./scripts/build.sh projects/sand-creek-raceway          # full run, Phases 1–5
./scripts/build.sh projects/sand-creek-raceway mesh      # resume from a stage (skip the OSM/USGS fetch)
./scripts/build.sh projects/sand-creek-raceway --list    # list the stages
```

Stages, in order: `gps` (Overpass centerline + street labels) → `elev` (USGS 3DEP) → `project`
(local metres, origin, true north) → `mesh` (road ribbon + grass + dummies + decals) → `env`
(buildings/trees/highways/mountains) → `blend` → `kn5` (Blender 4.2 + vendored add-on) → `pack`
(AC folder + zip). The `gps`/`elev` front half hits the network and only re-runs when the route or
region changes; the geometry→package back half is offline and deterministic.

## Install (optional, phase 6 — Windows)

Drop a built track into your local Assetto Corsa `content/tracks`. It auto-detects the AC folder
(Steam library scan on Windows/macOS/Linux) and **asks where tracks are if it can't find them**:

```bash
python -m scripts.ac.install                          # pick from all built tracks (interactive)
python -m scripts.ac.install projects/sand-creek-raceway
python -m scripts.ac.install --list                   # show what's built
python -m scripts.ac.install --tracks-dir "D:/SteamLibrary" --yes   # explicit path, no prompts
```

Each built track is an optional item you choose from; the installer copies the folder and drops the
`.kn5` inside it (where `models_<layout>.ini` expects it). Building can install in one step with
`python -m scripts.ac.track_folder projects/<slug> --install`. Override detection with `AC_TRACKS_DIR`.

## Status

🚧 Early scaffold. Pipeline modules are stubbed (`NotImplementedError`) and tracked per skill.
