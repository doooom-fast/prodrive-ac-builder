---
name: ac-track-modding
description: Enforce Assetto Corsa conventions and run the headless Blender build to a kn5 + installable track folder. Use for AC surface naming (1ROAD_/1KERB_), required dummy objects (AC_START/AC_PIT/AC_TIME/AC_HOTLAP_START), material assignment via the AC Blender Tools addon, the headless kn5 export, and generating the track folder (models/surfaces/ui/map/ai). Documents the Windows-only steps it cannot own (AI recording + in-game QA).
---

# AC Track Modding

The build engine and the enforcer of Assetto Corsa–specific conventions.

## Surface naming (mesh object prefixes)

| Prefix | Meaning |
|--------|---------|
| `1ROAD_*` | Drivable **physical** surface, keyed to `surfaces.ini` |
| `1KERB_*` | Kerb geometry / material |
| *(no numeric prefix)* | **Visual-only** geometry (no physics) |

## Required dummy objects

- **Start / pit:** `AC_START_0..N`, `AC_PIT_0..N`
- **Timing:** `AC_TIME_0_L` / `AC_TIME_0_R` (start-finish), then `AC_TIME_1_L/R…` incremented per sector
- **Hotlap:** `AC_HOTLAP_START_0`

## Materials

`ksGrass` for grass; a road shader for `1ROAD_*` surfaces. Assigned via the **AC Blender Tools**
addon's `settings.json` (a material JSON drives the assignment).

## Headless export

```bash
blender --background --python scripts/ac/build_kn5.py -- <track-dir>
```

Requires Blender 4.x with the AC Blender Tools (kn5 export) addon.

## Track folder output

- `models_<layout>.ini` — references the shared kn5 (one model, many layouts)
- `data/surfaces.ini` — physical surface definitions (keyed to `1ROAD_*`)
- `ui/<layout>/ui_track.json` — track metadata per layout
- `map.png` + `data/map.ini` — minimap
- `ai/` — AI fast line per layout (recorded on Windows)
- `outline.png`, `preview.png` — UI imagery

## Scope boundary

Documents what it **can't own**: **AI line recording and in-game testing require the Windows GUI**
(AC + Content Manager + CSP). Phases 1–5 are code-driven here; phase 6 is the manual loop.

## Scripts

`scripts/ac/` — `build_kn5.py` (headless Blender entry), `materials.py` (material JSON / addon settings),
`track_folder.py` (emit models/surfaces/ui/map/ai layout files).
