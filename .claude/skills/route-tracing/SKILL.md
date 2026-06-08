---
name: route-tracing
description: Trace a hand-drawn route line off a map screenshot and find the exact OSM roads it follows — loop and interior alike. Use when a project has a marked-up screenshot (e.g. Google My Maps red line) and you need to convert that drawn intent into a precise road list for gps-extraction, instead of guessing road names by hand. Detects the drawn pixels, georeferences against the real road network, and map-matches to OSM ways.
---

# Route Tracing

Turns the **drawn line** on a map screenshot into the **exact roads** it runs along — so the route
comes from what the user actually drew, not from guessing arterial names. Feeds its road list to
`gps-extraction`, which builds the centerline.

## Pipeline

1. **Detect** — decode the screenshot (stdlib PNG reader, no deps) and isolate the drawn-line pixels
   by colour (default: saturated red, e.g. Google My Maps). → a pixel point cloud. (`detect.py`)
2. **Georeference** — solve the pixel → lon/lat transform (`georef.py`):
   - **Exact (preferred):** two control points → a north-up affine, no ambiguity.
   - **Auto (fallback):** anchor one point and refine scale by snapping pixels onto the road network.
     The uniform avenue grid makes this *slide a block onto parallel roads*, so it's approximate —
     prefer the two-point path.
3. **Map-match** — for every OSM way, measure how much of its length runs under the drawn line
   (within tolerance). Roads with enough covered length **are** the route. (`match.py`)
4. **Emit** — ranked road list + the solved georef → `data/traced_route.json`, and the matched roads
   drawn back onto the screenshot → `data/traced_overlay.svg` (verify the selection by eye).

## Control points (for the exact transform)

Both come from dropped Google Maps pins (`?q=lat,lon`), at opposite corners of the drawn loop:

- **SW corner** → `track.config.json` → `location` (the pin you already have).
- **NE corner** → `track.config.json` → `route.anchor_ne: [lon, lat]`.

The matching SW-most / NE-most drawn pixels are detected automatically and tied to these.

## Inputs / outputs

- **In:** `source/<screenshot>.png` (with the drawn line) + the two control points in config.
- **Out:** `data/traced_route.json` (`roads` ranked by covered metres + `georef`), `data/traced_overlay.svg`.
- **Then:** copy the confirmed roads into `route.roads` and run `gps-extraction`.

## Run

```bash
python -m scripts.trace.trace_route projects/<slug> [screenshot.png]
```

## Scripts

`scripts/trace/` — `detect.py` (PNG decode + colour detect), `osm.py` (Overpass drivable fetch),
`georef.py` (exact + auto georeference), `match.py` (per-road coverage), `trace_route.py` (orchestrator).

## Status & limits

Works end-to-end; **use two control points** for accuracy (single-anchor auto-fit is approximate on
uniform grids). Tune the colour test in `detect.is_red` per source. Unnamed `service` ways (parking
lots) under a thick line are noise — the orchestrator keeps named roads; review the overlay before
committing the road list.
