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

## Build (once the adapter is implemented)

```bash
# S1–S2: extract + parse the region → data/centerline.geojson + data/items.json
python -m scripts.scs.extract    projects/ats-colorado-sample
python -m scripts.scs.parse_map  projects/ats-colorado-sample
# S3–S5: reuse the existing geometry → Blender → kn5 back-half
blender --background --python scripts/ac/build_kn5.py -- projects/ats-colorado-sample
```
