# `scripts/scs/` — ATS / ETS2 → Assetto Corsa source adapter

Front-end that turns a region of an SCS truck-sim map into the same intermediate artifacts the
GPS pipeline produces (`data/centerline.geojson` + a region/item manifest + converted assets),
so the geometry → Blender → kn5 back-half is reused unchanged. See `docs/scs-to-ac-plan.md` for
the full design and `.claude/skills/scs-extraction/` for the workflow.

> **Scaffold.** These modules define interfaces and orchestration; the external-tool calls raise
> `NotImplementedError` until wired in.

## External tools (not vendored — install separately)

The toolchain is polyglot. Each tool is wrapped as a subprocess that emits a neutral artifact
(GeoJSON / glTF / JSON); Python ingests those. Point the modules at the binaries via env vars.

| Module | Wraps | Install | Env var |
|--------|-------|---------|---------|
| `extract.py` | [sk-zk/Extractor](https://github.com/sk-zk/Extractor) — HashFS v1/v2 unpack | download release binary | `SCS_EXTRACTOR_BIN` |
| `parse_map.py` | [truckermudgeon/maps](https://github.com/truckermudgeon/maps) parser → GeoJSON, and/or [TruckLib](https://github.com/sk-zk/TruckLib) (C#/.NET) | `pnpm i` / `dotnet` | `SCS_MAP_PARSER_BIN` |
| `convert_models.py` | [ConverterPIX](https://github.com/mwl4/ConverterPIX) — `.pmg/.ppd` → mesh | build or download binary | `CONVERTERPIX_BIN` |

`materials.py` and `road_looks.py` parse text/binary SCS formats directly (no external binary).

## Blender version note

ConverterPIXWrapper targets Blender **3.6**; AC Blender Tools (the kn5 export in `scripts/ac/`)
needs **4.x**. Run asset conversion in a 3.6 step that exports glTF, then assemble + export kn5 in
the existing 4.x step. Re-check whether the current Wrapper supports 4.x — if so, unify them.

## Pipeline order

```
extract.py  →  parse_map.py  →  road_looks.py  →  (scripts/gps/centerline.py resample)
                    ↓
            convert_models.py + materials.py   (extract mode only)
                    ↓
   scripts/geometry/  →  scripts/ac/ (headless Blender → kn5)
```

Everything reads from `track.config.json` via `scripts/config.py` — no hardcoded paths, regions,
or scales in these modules.
