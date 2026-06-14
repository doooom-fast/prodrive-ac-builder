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
| 2 | Sample USGS 3DEP elevation + margin grid, smooth | Mac | `elevation` |
| 3 | Project lat/lon/elev → local meters, set origin + true north | Mac | `geometry` / `lighting` |
| 4 | Road ribbon (`1ROAD`) + grass heightfield (`GRASS`) + dummies | Mac | `geometry` / `ac` |
| 5 | Material JSON → headless Blender → kn5 + track config | Mac | `ac` / `lighting` |
| 6 | Install (`scripts.ac.install`, optional), drive, record AI lines, QA | **Windows** | `ac` |
| 7+ | Objects: barriers, kerbs, trees, buildings — iterative | Mac → Win | `ac` |

Phases 1–5 run headless on macOS; phase 6 is the manual loop on Windows (AC + Content Manager + CSP).

## Tech stack

- **Python 3.9+ stdlib** — the geometry/environment pipeline is deliberately dependency-free
- **Blender 4.x/5.x** — texture generation (its bundled numpy) and the headless `.kn5` export
  (leBluem's GPL exporter, auto-cloned into `vendor/` and patched by `scripts/ac/kn5_native.py`)
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
P=projects/sand-creek-raceway
python3 -m scripts.ac.fetch_textures                         # pinned CC0 building scans (optional)
blender --background --python scripts/ac/texgen.py -- $P     # texture suite (seeded, composites scans)
python3 -m scripts.geometry.build_mesh $P                    # 1ROAD/1GRASS/1KERB + paint + wear
python3 -m scripts.environment.build_env $P                  # buildings/signs/trees/walls/freeways…
blender --background --python scripts/ac/kn5_native.py -- $P # kn5 with embedded textures
python3 -m scripts.ac.track_folder $P                        # installable folder + CSP ext_config
python3 -m scripts.ac.kn5_inspect $P                         # static QA of the kn5
```

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

✅ Phases 1–5 fully code-driven: centerline → elevation → mesh → **full scenery layer** (buildings
with facade variants, street signage with real road names, streetlights with CSP night lighting,
power lines, fences, collidable jersey walls, elevated freeways with piers + sign gantries,
storage tanks, railways, creek water, riparian trees, mountain horizon) → textured kn5 + track
folder. Phase 6 (drive, AI line, in-game QA) remains the manual Windows loop.
