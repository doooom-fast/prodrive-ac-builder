# Prodrive AC Builder

Convert real-world road loops into playable Assetto Corsa (AC) tracks. Given a Google Maps
screenshot, a location, and route notes, this project produces a complete, installable AC track
folder — proper geometry, real elevation, accurate lighting, and multiple layout variants.

First target: **Sand Creek Raceway** — a street loop in Commerce City, Colorado (US), with optional alternate routes.

> **Working on the Steam game (GALA), not an AC track?** This repo's pipeline is also the *seed* for
> a UE5 driving-as-art game. If your task is about that game, start at [`steam-game/README.md`](steam-game/README.md)
> — that plan is the source of truth for the game; this file governs the AC track pipeline it reuses.

---

## First principle

> **The screenshot is a selection aid, not data.**

Precise geometry derives from **OpenStreetMap via the Overpass API**. Hand-drawn **KML** is used
*only* where the intended route deliberately leaves the real road network (shortcuts, private land,
connectors). A map screenshot tells us *which* roads to grab — it is never traced for coordinates.

## Reproducibility

> **The whole pipeline is reproducible from `track.config.json`.**

Every track lives under `projects/<slug>/` and is fully described by its `track.config.json`.
No hardcoded coordinates, widths, or rotations in scripts — read them from config, and write
derived values (e.g. `true_north_rotation_deg`) back to it. A clean checkout plus the config plus
the source screenshot must be enough to rebuild the track end to end.

---

## Build environment split

| Platform | Role | Used for |
|----------|------|----------|
| **Mac** (headless) | Build engine | Data acquisition, geometry processing, Blender mesh building, kn5 export. Phases 1–5 are fully code-driven here. |
| **Windows** | Drive & QA | AC + Content Manager + Custom Shaders Patch. Manual driving, AI line recording, visual QA. Phase 6 is the manual loop. |

`ac-track-modding` documents what it **can't own**: AI recording and in-game testing require the
Windows GUI. Don't pretend those steps are scriptable on Mac.

## Coordinate & unit conventions

- **Units: meters.** Everything in the geometry/Blender/AC pipeline is metric.
- **Up axis: Y-up** (AC / kn5 convention). Projection and mesh code target Y-up; convert once,
  at the projection boundary, and stay consistent after.
- **Origin:** set by `origin` in config (default `"centroid"` of the centerline). Project
  `lat/lon/elev → local meters` relative to that origin.
- **True north:** orient the mesh to true north so computed sun shadows align. The resolved
  rotation is written back to `true_north_rotation_deg`.

## Surface naming (AC convention — enforced by `ac-track-modding`)

| Mesh prefix | Meaning |
|-------------|---------|
| `1ROAD_*` | Drivable physical surface, keyed to `surfaces.ini` |
| `1KERB_*` | Kerb geometry / material |
| *(no numeric prefix)* | Visual-only geometry (no physics) |

**Required dummy objects:**
- Start / pit: `AC_START_0..N`, `AC_PIT_0..N`
- Timing: `AC_TIME_0_L` / `AC_TIME_0_R` (start-finish), `AC_TIME_1_L/R…` (one pair per sector)
- Hotlap: `AC_HOTLAP_START_0`

**Materials:** `ksGrass` for grass, a road shader for `1ROAD_*`, assigned via the AC Blender Tools
addon's `settings.json`.

## Elevation source priority

1. **USGS 3DEP 1 m** — preferred for US locations (free, high resolution). Primary for Commerce City.
2. **OpenTopography** — fallback / non-US coverage.
3. **SRTM 30 m** — last-resort global fallback.

Smooth aggressively *along the racing line* to avoid stepping. Commerce City is gentle terrain —
expect mild grades, not big elevation.

---

## Build pipeline

| Phase | Task | Where | Skill |
|-------|------|-------|-------|
| 0 | Provide screenshot, location, route notes | Claude Code | — |
| 1 | Identify roads → Overpass/KML → resampled centerline | Mac | `gps-extraction` |
| 1-alt | **No GPS/OSM data** (private circuit)? Trace the asphalt off an aerial screenshot → georeferenced centerline | Mac | `aerial-tracing` |
| 2 | Sample USGS 3DEP elevation + margin grid, smooth | Mac | `elevation` |
| 3 | Project lat/lon/elev → local meters, set origin + true north | Mac | `geometry` / `lighting` |
| 4 | Road ribbon (`1ROAD`) + grass heightfield (`GRASS`) + dummies | Mac | `geometry` / `ac` |
| 5 | Material JSON → headless Blender → kn5 + track config | Mac | `ac` / `lighting` |
| 6 | Install (`scripts.ac.install` — optional, auto-finds AC tracks dir), drive, record AI lines, QA | **Windows** | `ac` |
| 7+ | Objects: barriers, kerbs, trees, buildings — iterative passes | Mac → Win | `ac` |

Phases 1–5 are fully code-driven. Phase 6 is the manual loop on Windows.

## Skills

Specialized capabilities live in `.claude/skills/`. Reach for them by name:

- **`gps-extraction`** — region + rough route → clean ordered centerline (Overpass, KML, resample, width tags).
- **`aerial-tracing`** — aerial/satellite screenshot of a circuit with no GPS/OSM data → asphalt traced + georeferenced to real lon/lat → the same `centerline.geojson` (so it stays elevation-correct).
- **`elevation`** — sample real terrain along the line, smooth, emit a heightfield.
- **`lighting`** — solar position, true-north orientation, CSP/Sol lighting config.
- **`ac-track-modding`** — AC conventions, surface naming, dummies, headless Blender build & kn5 export, track folder layout.

## Layouts

A `track.config.json` `layouts[]` entry is a route variant. All layouts **share one kn5 model**
and differ only in AC configuration (which connectors they use, which AI line, etc.). Express
variants as separate AC configs over a single mesh — never rebuild the mesh per layout.

---

## Repo layout

```
prodrive-ac-builder/
├── CLAUDE.md                  # this file — conventions & pipeline
├── README.md
├── pyproject.toml
├── .claude/skills/            # gps-extraction, aerial-tracing, elevation, lighting, ac-track-modding
├── scripts/
│   ├── gps/                   # overpass query, kml parse, resample, width tagging
│   ├── aerial/               # aerial-screenshot front-end: asphalt detect, skeleton, georef → centerline
│   ├── elevation/             # USGS 3DEP fetch, sample-along-path, heightfield, smooth
│   ├── geometry/              # projection, road ribbon mesh, grass heightfield, dummies
│   ├── lighting/              # solar position, true-north orient, CSP config emit
│   └── ac/                    # blender headless build, material json, track config gen
└── projects/
    └── sand-creek-raceway/
        ├── source/            # screenshot, any KML, route notes
        ├── data/              # centerline.geojson, dem.tif, heightfield.npy, splines
        ├── blender/           # working .blend
        ├── build/             # fbx, kn5, full installable track folder
        └── track.config.json  # source of truth
```

## Headless Blender export

```bash
blender --background --python scripts/ac/build_kn5.py -- projects/sand-creek-raceway
```

Requires **Blender 4.x** with the **AC Blender Tools** (kn5 export) addon installed.
