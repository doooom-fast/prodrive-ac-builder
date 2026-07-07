---
name: elevation
description: Sample real-world terrain elevation along the track centerline and emit a smoothed heightfield. Use after the centerline exists to add z-values to the racing line plus a surrounding terrain grid. Source priority is USGS 3DEP 1 m (US) → OpenTopography → SRTM 30 m, smoothed aggressively along the racing line to avoid stepping.
---

# Elevation

Samples and integrates real terrain data along the racing line.

## Source priority

1. **USGS 3DEP 1 m** — preferred for US locations (free, high resolution). **Primary for Commerce City.**
2. **OpenTopography** — fallback / wider coverage.
3. **SRTM 30 m** — last-resort global fallback.

## Inputs

- `data/centerline.geojson` (from `gps-extraction`).
- `track.config.json` (`location` for the region, `origin`).

## Process

1. Sample elevation **along the centerline** plus a **margin grid** for the surrounding terrain.
2. **Smooth aggressively along the racing line** to avoid stepping (the road must feel continuous).
   Keep the margin grid coarser/natural for grass.

> Commerce City is gentle terrain — expect mild grades, not big elevation.

## Capture fusion (phone-measured road altitude)

The DEM samples the *ground*, not always the *road* (vegetation, cut/fill, walls). If a Prodrive
Scan drive has been ingested (`source/realworld_capture.json`), the heightfield stage automatically
bends the profile toward the phone's measured road altitude where evidence exists — writing
`z_fused_m`, which `projection` prefers over `z_smooth_m`. The comparison is relative: a robust
constant datum fit absorbs GPS vertical bias, the geoid gap, and the configured
`sensor_height_m` (phone height above the road — windshield mount + car) being only roughly right.
Bad runs (the phone falling off its mount, GPS dropouts) are rejected by **continuity
segmentation**: roads can't step, dropped phones can. Knobs live in `track.config.json` →
`elevation.capture_fusion` (see `scripts/elevation/capture_fusion.py` DEFAULTS); uncovered spans
keep the pure DEM profile.

## Output

- Centerline **z-values** (added to the centerline) — `z_smooth_m`, plus `z_fused_m` when capture
  evidence exists.
- `data/heightfield.npy` — the terrain grid used to build the grass mesh.

## Scripts

`scripts/elevation/` — `usgs_3dep.py` (DEM fetch), `heightfield.py` (sample-along-path + grid + smooth),
`capture_fusion.py` (bend the profile toward ingested Prodrive Scan road altitudes).
