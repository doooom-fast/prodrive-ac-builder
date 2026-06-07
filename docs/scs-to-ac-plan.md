# SCS (ATS / ETS2) region → Assetto Corsa track

> **Status: scaffold / design.** The `scs-extraction` skill and `scripts/scs/` modules are
> stubs that define the interfaces and orchestration shape. The external-tool integrations
> (extract, parse, convert) are not yet implemented. See "Build order" for the MVP path.

## The core idea

This is **the existing pipeline with a new front-end.** The GPS pipeline is:

```
region + route → data/centerline.geojson → geometry → Blender → kn5
```

An SCS port is:

```
game archive → region road-graph → data/centerline.geojson → (same geometry / Blender / kn5 back-half)
```

The back half — projection, road-ribbon sweep, dummies, surface naming, lighting, headless
kn5 export — is **reused as-is**. The new work is a *source adapter* that produces the same
intermediate artifacts (`centerline.geojson`, item manifest, converted meshes + materials)
from game files instead of OpenStreetMap. New code lives in `scripts/scs/` and the
`scs-extraction` skill parallels `gps-extraction`.

## Three decisions baked into this design

**1. Native game scale — do not rescale to 1:1.**
ETS2 is **1:19**, ATS is **1:20**, and the scale is *non-uniform* (SCS adjusts it per-region;
cities are compressed differently than highways). No single multiplier recovers real-world
distance, and SCS themselves call a manual 1:1 rebuild infeasible. We port at native scale:
content density (junction spacing, town layout) was authored for it, so rescaling would leave
gaps. `track.config.json → source.scale_mode = "native"`.

**2. Freeroam open map + carved routes as layouts.**
An SCS region is an open road network, not a loop. This maps onto the existing `layouts[]`
concept: build one shared kn5 of the region, then express specific point-to-point / loop
**routes as separate AC configs** over that single mesh (`loop: false`, routes in `layouts[]`).

**3. Personal use only; SCS asset redistribution infringes.**
SCS's modding license covers mods *for their own games*. Extracting their proprietary
`.pmg`/`.dds` assets into Assetto Corsa is a derivative work outside that license (and Kunos
has its own rules). Converting for your own offline rig is the safe zone; **publishing a track
containing SCS assets is not.** For a distributable output, use `source.asset_mode = "substitute"`
— keep the road network/layout as reference geometry and swap in your own / CC0 / Kunos-stock
props. The asset stage is built with that seam in mind.

## Toolchain (orchestrated, not reinvented)

| Need | Tool | Notes |
|------|------|-------|
| Extract `.scs` archives | [sk-zk/Extractor](https://github.com/sk-zk/Extractor) | Cross-platform, HashFS v1 + v2 + ZIP. Standalone binary → runs on the Mac/Linux build engine. |
| Parse map → road graph | [truckermudgeon/maps](https://github.com/truckermudgeon/maps) `parser` + `generator` | Emits **GeoJSON** road/prefab network — same format the pipeline ingests. Junction geometry is imperfect. |
| Parse map (programmatic) | [TruckLib](https://github.com/sk-zk/TruckLib) (C#) | Reads `.mbd` map, `.sii`/`.mat`, `.ppd` prefab descriptors, HashFS. Tracks game version. Prefabs may break. |
| Models → mesh | [ConverterPIX](https://github.com/mwl4/ConverterPIX) (+ [Wrapper](https://forum.scssoft.com/viewtopic.php?t=245065)) | `.pmg/.pmd/.ppd/.tobj/.mat` → middle format → Blender. Linux binary exists. |
| Prefab nav curves | [ETS2LA/data](https://github.com/ETS2LA/data) (ts-map fork) | Extracts drivable spline data from prefabs — reusable for AC AI lines + junction surfaces. |

**Polyglot reality:** extraction/parsing is C#/TypeScript, model conversion is C++, the pipeline
is Python + Blender. Each external tool is wrapped as a **subprocess adapter that emits a neutral
artifact** (GeoJSON, glTF, JSON manifest); Python ingests those. Keeps "reproducible from config" intact.

**Blender version split:** ConverterPIXWrapper targets Blender 3.6; AC Blender Tools needs 4.x.
Convert assets in a 3.6 step → export glTF, then assemble + kn5-export in the existing 4.x step.
(Verify whether the current Wrapper supports 4.x; if so this collapses to one Blender.)

## Pipeline phases (mirrors CLAUDE.md's table)

| Phase | Task | Reuse vs new | Skill |
|-------|------|--------------|-------|
| 0 | Pick game (ATS/ETS2 + DLC), select region (bbox/city), route notes | new (config) | — |
| S1 | Extract `.scs` → asset tree | **new** | `scs-extraction` |
| S2 | Parse map, clip to region → `region.geojson` + `items.json` (prefabs, models, terrain) | **new** | `scs-extraction` |
| S3 | Bake geometry: centerline re-sweep + prefab surfaces; project world→local m→Y-up; true north | **~80% reuse** of `geometry` | `geometry` |
| S4 | Convert assets: ConverterPIX→glTF, `.mat`/`.tobj`/`.dds`→AC material JSON, dedup+instance+budget | **new** | `scs-extraction` (assets) |
| S5 | Assemble in Blender, surface naming, dummies, layouts, lighting → kn5 + track folder | **reuse** | `ac-track-modding` + `lighting` |
| 6 | Windows: install, drive, AI lines, QA | reuse | `ac-track-modding` |

New code is really only S1, S2, S4 plus an adapter into S3. S5/S6 are untouched.

## The three hard sub-problems

**Roads — re-sweep, don't bake.** The parsed graph gives each road's centerline *and* its
`road_look` template name. Parse `def/world/road_look.sii` → lane count / width / shoulder →
feed the existing resample + cross-section ribbon sweep → clean `1ROAD_` mesh that's physics-ready.
(Baking the game's visual road meshes via ConverterPIX gives better looks but messy physics —
reserve for fidelity passes.)

**Prefabs / junctions — the universally-flagged weak point** (TruckLib "may break,"
truckermudgeon "intersections look incorrect"). Hybrid: convert the prefab's **visual model**
via ConverterPIX for looks, and generate the **drivable `1ROAD_` surface from the prefab's
`.ppd` nav curves** (which ETS2LA already extracts). Accept imperfection in MVP; leave a
manual-fixup hook in Blender.

**Terrain — there is no heightmap.** SCS does not use mesh-terrain heightmaps; terrain is
per-road vertex profiles (offset + falloff from road edge) plus standalone terrain/map-area
items. The `elevation`/USGS skill is mostly N/A here — terrain comes from the game. Plan:
ground "skirts" from per-road terrain profiles + a low-relief background ground plane; refine by
converting the game's terrain meshes where they exist. (Draping real USGS elevation would fight
the compressed scale — skip it.)

## Config additions

`track.config.json` `source` block (the existing loader already treats `source` as freeform):

```jsonc
"source": {
  "type": "scs",
  "game": "ats",                            // or "ets2"
  "dlc": ["dlc_colorado", "dlc_utah"],
  "map": "usa",
  "region": { "bbox": [x0, z0, x1, z1] },   // SCS world coords; or { "cities": [...] }
  "scale_mode": "native",                   // native | (future) rescale
  "asset_mode": "extract",                  // extract | substitute (distributable builds)
  "game_root": "/path/to/American Truck Simulator"  // user's licensed install (not committed)
}
```

`location` stays present but is used **only for lighting** (sun position / timezone), not geometry.

**Reproducibility note:** full reproducibility needs the user's *licensed* game files, which can't
be redistributed. The analog of "clean checkout + config + screenshot" is **clean checkout +
config + the user's game install**.

## Build order (MVP-first)

1. **Prove the seam.** One small region (e.g. an ATS town + a highway stretch), **roads +
   prefab-visuals + ground skirt only — no props/vegetation**, single freeroam layout. Goal: a
   kn5 that loads and is drivable in AC. Validates S1→S2→S3→S5 with mostly-reused code.
2. **Assets pass (S4).** ConverterPIX models, material mapping, dedup + a hard prop budget
   (kn5 has no real instancing — scope to sub-regions, cap counts, `log` what's dropped).
3. **Junction fidelity.** Improve prefab drivable surfaces from nav curves; carve named routes
   into `layouts[]`.
4. **Polish.** Vegetation, signs, time-of-day via `lighting`, AI lines (Windows).

## Risks / limitations

- Imperfect junction geometry (multiple sources confirm).
- No real-world distances (non-uniform scale); native scale only.
- Approximated terrain (no global heightmap).
- File size / FPS on big regions → scope to sub-regions, budget props.
- Polyglot toolchain (C# / TS / C++ / Python) + Blender version split (3.6 vs 4.x).
- Map parser breaks on new game versions until the libs update.
- Legal: personal use; redistribution of SCS assets infringes.

## Sources

- [sk-zk/Extractor](https://github.com/sk-zk/Extractor) · [TruckLib](https://github.com/sk-zk/TruckLib) ·
  [truckermudgeon/maps](https://github.com/truckermudgeon/maps) · [ConverterPIX](https://github.com/mwl4/ConverterPIX) ·
  [ConverterPIXWrapper](https://forum.scssoft.com/viewtopic.php?t=245065) · [ETS2LA/data](https://github.com/ETS2LA/data)
- [Map scale: ETS2 1:19 / ATS 1:20](https://trucksimulator.wiki.gg/wiki/User_blog:Wuiwedjksfsfdjsd/Map_Scale_in_ETS2_and_ATS) ·
  [SCS "The Rescale"](https://blog.scssoft.com/2016/06/the-rescale.html)
