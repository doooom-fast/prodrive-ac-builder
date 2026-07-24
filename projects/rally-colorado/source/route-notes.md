# Rally Colorado — route notes (phase 0)

Fill this in on the desktop before running `gps-extraction`. One block per stage.
See `../BUILD_PLAN.md` for the full plan. Geometry derives from **OSM/Overpass**; the
screenshot/GPX is only a **selection aid** for picking the right ways.

Event: **Rally Colorado** (ARA), Rangely, Rio Blanco County, CO. Gravel county roads.
Town ref ≈ 40.087° N, 108.796° W · `America/Denver` · event mid-July.

Both surface variants (`_gravel`, `_tarmac`) share everything below — the fork is late
(material + `surfaces.ini` only). Fill each stage once.

---

## Template (copy per stage)

### <Stage name> — CR <number>
- **Slug:** `rally_co_<stage>` → variants `rally_co_<stage>_gravel`, `rally_co_<stage>_tarmac`
- **County Road(s) / OSM ways:** <CR number; OSM way ids once identified>
- **Start point (lon,lat):** <…>
- **Finish point (lon,lat):** <…>
- **Direction:** <as-raced>  | reverse layout? <y/n>
- **Approx length:** <mi / km>
- **bbox:** <minlat, minlon, maxlat, maxlon>
- **default_width_m:** <5.5–7>  | width_overrides: <junctions/widenings>
- **Source path:** Overpass ☐  |  KML segment (OSM gap) ☐  |  aerial-tracing (imagery only) ☐
- **Selection-aid assets:** <screenshot filename, gpx filename>
- **Character / hazards:** <crests, drop-offs, tight sections — informs road-grounding + elevation>

---

## Stages to fill in

### Cathedral — CR 100 West   ← recommended first stage (validate the fork end-to-end)
### Dragon Tail — CR 116 / 133 NW
### Under the Dragon — CR 109
### Valley of the Gods — CR 131 E
### Quest for Darwin — CR 73 West
### Earl's Revenge — CR 96 West

### (optional / historical)
### Douglas Creek
### Dragon Trail
### Presser   — short (~1 mi), kinks + crests
