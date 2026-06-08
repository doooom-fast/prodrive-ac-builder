# ATS Colorado Sample — source notes

Template project for the SCS → Assetto Corsa pipeline. Copy this folder to start a real port and
edit `track.config.json`. See `docs/scs-to-ac-plan.md` and the `scs-extraction` skill.

## Fill these in

1. **`source.game_root`** — path to your licensed ATS install (the folder with `base.scs`,
   `def.scs`, `dlc_colorado.scs`, …). Never committed.
2. **`source.region.bbox`** — `[x0, z0, x1, z1]` in SCS world meters. Get real values by running
   `parse_map.py` once over the whole map and reading coordinates off `region.geojson`, or from the
   truckermudgeon web map. The committed values are placeholders.
3. **`layouts[]`** — a region is freeroam by default; add carved point-to-point / loop routes as
   entries over the one shared kn5.

## Conventions for this source

- **Native scale** (ATS 1:20) — distances are compressed and non-uniform; not real-world.
- **`location`** drives lighting only (sun position / timezone), not geometry. Colorado coords here
  so shadows feel right for the Colorado DLC region.
- **`asset_mode`**:
  - `extract` — convert SCS models/textures (personal/offline use only).
  - `substitute` — keep only the road network; ship your own / CC0 / Kunos-stock props
    (the path to a distributable track).

## Legal

SCS assets are copyrighted. Converting for your own rig is the safe zone; **do not publish or
share a track that contains extracted SCS assets.** Use `asset_mode: "substitute"` for anything
you intend to distribute.

## Build

Works today (code-only — once `data/region.geojson` exists):

```bash
# S3: region.geojson + road_looks → centerline.local.json (+ a quick road OBJ)
python -m scripts.scs.centerline projects/ats-colorado-sample
# S3→S4: full track mesh (1ROAD + GRASS + AC dummies), reusing the geometry back-half
python -m scripts.scs.build      projects/ats-colorado-sample
```

Still pending a licensed install + external binaries (see `scripts/scs/README.md`):

```bash
# S1–S2: extract + parse the region → data/region.geojson + data/items.json
python -m scripts.scs.extract    projects/ats-colorado-sample   # needs SCS_EXTRACTOR_BIN
python -m scripts.scs.parse_map  projects/ats-colorado-sample   # needs SCS_MAP_PARSER_BIN
# S5: headless Blender → kn5
blender --background --python scripts/ac/build_kn5.py -- projects/ats-colorado-sample
```
