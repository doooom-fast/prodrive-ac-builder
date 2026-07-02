# PIPELINE_BRIDGE — this repo → Unreal

How the existing Python pipeline in this repo becomes the **real seed** the game blooms from. The
decision (owner-confirmed): **reuse this pipeline** to produce the georeferenced starting geometry,
export it to Unreal as the authored anchor, and let procedural generation grow outward.

We are **not** rebuilding the AC pipeline in Unreal. We run it as-is to emit data, and add one thin
export step. The realness of the seed is the whole point of the vision — don't fake it in-engine.

---

## What already exists here (proven for this exact neighborhood)

- `projects/san-diego-loop/` — **Lake Murray Loop**, the childhood neighborhood, built through the
  proven Sand Creek pipeline. Anchored at `lat 32.782, lon -117.042`.
- `projects/san-diego-cruise/` — **freeroam** of Del Cerro / San Carlos / Allied Gardens / La Mesa,
  anchored at the childhood home (`5602 Dartford Way`, Del Cerro). Keeps Lake Murray as water.
- The pipeline stages we consume (see repo `CLAUDE.md` and `.claude/skills/`):
  - `gps-extraction` → `data/centerline.geojson` (ordered, resampled ~2–5 m, width-tagged).
  - `elevation` → smoothed elevation along the line + a surrounding terrain grid (heightfield).
  - `scripts/geometry/projection.py` → projects `lon/lat/elev → local meters` in an **ENU tangent
    plane**: **X = east, Y = up, Z = north (meters)**, true-north aligned by construction, origin at
    the centerline centroid, written to `data/`.

That ENU projection is the clean hand-off frame. It's metric, true-north, and origin-locked — ideal
for a game engine.

---

## The seed for GALA

Create a dedicated project (don't mutate the AC ones):

```
projects/gala-seed/
├── source/           # the My Maps route: 5591 Gala Ave → Benchley-Weinberger Elementary
├── data/             # centerline.geojson, elevation, projection origin  (pipeline output)
└── track.config.json # location + bbox + roads + landmark tags
```

**Region must include** (owner requirements):
- **5591 Gala Ave** (start anchor) → **Benchley-Weinberger Elementary** (the route spine).
- **The Del Cerro golf-course area** — tagged as the **sanctum** landmark (special / spiritual /
  mysterious; see [`VISION.md`](./VISION.md#the-golf-course-sanctum-special--spiritual--mysterious)).
  Extend the bbox to cover it and mark it as a named landmark region, not just road.
- Lake Murray edge (water landmark), as in the existing loop.

Use the existing skills to build it: `gps-extraction` for the road spine, `elevation` for terrain,
`projection` for the local-meters frame. This is the same path the Lake Murray loop already used.

---

## Data contract: Python → Unreal (`GalaSeedImport`)

The Unreal side (`Plugins/GalaSeedImport`) imports **exactly these artifacts** from `projects/gala-seed/data/`:

| Artifact | Format | Meaning in Unreal |
|----------|--------|-------------------|
| **Centerline** | GeoJSON LineString(s), projected to ENU meters (X=east, Y=up, Z=north) + per-vertex width | The road **spline** — the spine PCG grows from and the car starts on. Import as a spline component; widths → road mesh ribbon. |
| **Elevation heightfield** | grid (e.g. `.npy`/`.png16`/`.r16`) + extent + cell size in meters, same ENU origin | Landscape / heightfield for the seed terrain around the route. |
| **Projection origin** | JSON: `lon0, lat0, elev0`, meters-per-degree | Ties the local frame back to the real world (for provenance + optional real-sky/sun via the `lighting` philosophy). |
| **Landmarks** | JSON: named regions/points (sanctum = golf course, Lake Murray water, school, home) in ENU meters | Placement anchors: the **sanctum** hand-authored zone, water, points of interest. |

**Axis note:** the pipeline is Y-up ENU meters. UE5 is **Z-up, left-handed, centimeters**. Do the
conversion **once, at import** (ENU `X,Y,Z` meters → UE `X=north*100, Y=east*100, Z=up*100` cm, or
your chosen mapping) and stay consistent after — mirror the discipline the repo already applies at
its own projection boundary. Pick the mapping, document it in `GalaSeedImport`, never re-flip
downstream.

**Recommended export step:** add a small `scripts/` exporter (e.g. `scripts/game/export_seed.py`)
that reads `projects/gala-seed/data/` + `track.config.json` and writes a single self-describing
`gala_seed.json` (+ `heightfield.r16`) into a known folder the UE importer watches. Keep Unreal
ignorant of the Python toolchain internals — it consumes the emitted bundle, nothing more. That
loose coupling is the owner-confirmed model.

---

## Boundary rules

1. **Python owns "real."** Anything georeferenced (route, terrain, real landmark positions) comes
   from the pipeline. Don't hand-place the real neighborhood in-engine — that throws away the
   reproducibility and the realness the vision depends on.
2. **Unreal owns "unreal."** Procedural bloom, biomes, sky, paint, and the *authored* sanctum
   dressing live in-engine. The pipeline provides the sanctum's *location and extent*; UE provides
   its *soul*.
3. **One conversion boundary.** ENU-meters → UE-cm happens once in `GalaSeedImport`. Downstream code
   assumes UE coordinates.
4. **Reproducible seed.** Like the rest of this repo: a clean checkout + `gala-seed/track.config.json`
   + the source route must regenerate the seed bundle end to end. No hardcoded coordinates in game
   code — they come from the imported bundle.
