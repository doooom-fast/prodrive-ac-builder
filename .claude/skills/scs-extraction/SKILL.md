---
name: scs-extraction
description: Port a region of American Truck Simulator (ATS) or Euro Truck Simulator 2 (ETS2) into an Assetto Corsa track. Use when the source is an SCS game archive rather than OpenStreetMap — extract .scs (HashFS), parse the .mbd map and clip to a region, emit the same data/centerline.geojson the geometry pipeline consumes, and convert referenced models/materials to AC. Status — scaffold; external-tool integrations not yet implemented.
---

# SCS Extraction (ATS / ETS2 → Assetto Corsa)

Turns a region of an SCS truck-sim map into the **same intermediate artifacts** the GPS
pipeline produces, so the existing geometry → Blender → kn5 back-half is reused unchanged.

> First principle, restated for this source: **the game is the data; the screenshot/map view is
> only a selection aid.** A map view tells you *which* region and roads to grab — geometry comes
> from the parsed `.mbd` map graph, not from tracing pixels.

> **Scaffold status.** The steps below describe the intended process. `scripts/scs/` currently
> defines interfaces and orchestration only; `extract`, `parse_map`, and `convert_models` raise
> `NotImplementedError` until the external tools are wired in. See `docs/scs-to-ac-plan.md`.

## Decisions this skill assumes

- **Native scale.** ATS 1:20 / ETS2 1:19, non-uniform per region — never rescaled to 1:1
  (`source.scale_mode = "native"`).
- **Freeroam + layouts.** A region is an open network: one shared kn5, routes expressed as
  `layouts[]` (`loop: false`).
- **Personal use.** SCS assets are copyrighted; do not redistribute a track containing them.
  `source.asset_mode = "substitute"` keeps only the layout for distributable builds.

## Inputs

- `track.config.json` `source` block: `game` (ats/ets2), `dlc[]`, `map`, `region` (bbox in SCS
  world coords or city list), `scale_mode`, `asset_mode`, `game_root` (the user's licensed install).
- The user's installed game `.scs` archives (base + selected DLC). Not committed — referenced by path.

## Process

1. **Extract** (`extract.py`) — unpack the needed `.scs` archives (HashFS v1/v2) via
   [sk-zk/Extractor] into a working asset tree (`def/`, `map/`, `model/`, `material/`, `prefab/`).
2. **Parse map** (`parse_map.py`) — read the `.mbd` map graph, clip to `region`, and emit
   `data/region.geojson` (road centerlines + `road_look` tags) and `data/items.json` (prefabs,
   model placements, terrain). Backed by [truckermudgeon/maps] and/or [TruckLib].
3. **Road looks** (`road_looks.py`) — parse `def/world/road_look.sii` → per-template cross-sections
   (lane count/width, shoulder) for the ribbon sweep.
4. **Centerline** — resample `region.geojson` to ~2–5 m spacing and width-tag from road looks,
   reusing `scripts/gps/centerline.py`. Output is the standard `data/centerline.geojson`.
5. **Convert assets** (`convert_models.py`, `materials.py`) — [ConverterPIX] the referenced
   `.pmg/.ppd` → glTF (dedup by model hash, budget-capped); map `.mat`/`.tobj`/`.dds` → AC
   material JSON (SCS shader → `ks*`). Skipped when `asset_mode = "substitute"`.

Hand off to `geometry` (S3), then `ac-track-modding` + `lighting` (S5) unchanged.

## Output

- `data/centerline.geojson` — drop-in for the geometry pipeline (same shape as the GPS path).
- `data/region.geojson`, `data/items.json` — full parsed region for prefab/asset placement.
- `data/models/*.gltf` + `data/materials.json` — converted, deduped assets (extract mode only).

## Reference

HashFS v1/v2 layout · `.mbd` item/node graph · `road_look.sii` cross-sections · `.ppd` prefab nav
curves · SCS `.mat`/`.tobj` → AC shader mapping. Tool details and the full rationale live in
`docs/scs-to-ac-plan.md`.

## Scripts

`scripts/scs/` — `extract.py` (HashFS unpack), `parse_map.py` (map → geojson + items),
`road_looks.py` (cross-sections), `convert_models.py` (ConverterPIX → glTF), `materials.py`
(SCS → AC materials). See `scripts/scs/README.md` for the external-tool install steps.

[sk-zk/Extractor]: https://github.com/sk-zk/Extractor
[truckermudgeon/maps]: https://github.com/truckermudgeon/maps
[TruckLib]: https://github.com/sk-zk/TruckLib
[ConverterPIX]: https://github.com/mwl4/ConverterPIX
