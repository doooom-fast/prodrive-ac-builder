# Building Sand Creek Raceway on Windows

The Mac pipeline (Phases 1–5) generates the geometry and exports an **AC-standard FBX**, but the
Mac-native pure-Python kn5 exporter (experimental, bundled in an AI-line Blender addon) does **not**
produce valid Assetto Corsa track surfaces — the ground would not render or collide. Finishing the
kn5 with a real AC exporter on Windows fixes that. This is the Windows half of the pipeline
(`CLAUDE.md` Phase 6).

## What you have — `sand-creek-raceway-fbx-handoff.zip`

- **`sand_creek_raceway.fbx`** — AC-standard FBX (Y-up). Meshes named for AC:
  - Physical / drivable (leading digit): `1ROAD_main`, `1ROAD_connector`, `1KERB_corners`, `1GRASS`
  - Visual: `MARKINGS`, `BARRIER`, `BUILDINGS`, `ROOFS`, `TREES`, `WATER`, `HIGHWAY_visual`, `LIGHTS`
  - 12 `AC_*` null markers placed (`AC_START` sits on the start/finish; verified by re-import).
- **`sand_creek_raceway.fbm/`** — the textures the FBX references (asphalt, grass, buildings, roofs, kerb, trees).
- **`surfaces.ini`** — the physics surface definitions (grip, validity).

## Option A — ksEditor (Assetto Corsa SDK) — recommended

1. **ksEditor → File → Load →** `sand_creek_raceway.fbx`.
2. **Assign physics surfaces** (the leading-digit meshes are the drivable ones; keys match `surfaces.ini`):
   | Mesh | Surface |
   |------|---------|
   | `1ROAD_main`, `1ROAD_connector` | `ROAD` |
   | `1KERB_corners` | `KERB` |
   | `1GRASS` | `GRASS` |
3. **Assign shaders:** `ksPerPixelMultiMap` (+ the diffuse/normal maps from `.fbm`) for road / grass /
   buildings / roofs; `ksTree` for `TREES`; `ksPerPixel` for the rest.
4. Confirm the `AC_START` / `AC_PIT` / `AC_TIME` / `AC_HOTLAP` nulls look right.
5. **Save → Export `.kn5`.**

## Option B — Blender + "AC Blender Tools" (ksTools) addon, Blender 4.x

1. Install the AC Blender Tools addon.
2. Import `sand_creek_raceway.fbx` (Y-up). Textures are in `.fbm` next to it.
3. Assign the AC shaders per the table above (the addon's material panel).
4. Export `.kn5` via the addon.

> Rebuilding from source instead? `blender --background --python scripts/ac/build_kn5.py -- projects/sand-creek-raceway`
> auto-detects the addon's kn5 export operator. It needs the (gitignored) `data/` artifacts present —
> the FBX above already bakes them in, so Option A/B are the self-contained paths.

## Install the result

Drop the exported kn5 into your existing track folder, **replacing** the broken one:

```
…/steamapps/common/assettocorsa/content/tracks/sand_creek_raceway/sand_creek_raceway.kn5
```

Everything else in that folder (`surfaces.ini`, `ui/`, `models_full.ini`, `map.png`) is already
correct from release `v0.1.4`. Load **Sand Creek Raceway — full** and drive.
