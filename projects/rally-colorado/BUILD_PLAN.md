# Rally Colorado — Build Plan (handoff)

> **Deliverable:** each signature stage of **Rally Colorado** (Rangely, CO) built as an
> installable Assetto Corsa track, in **two surface variants** — a realistic **gravel/dirt**
> version and a fantasy **paved/tarmac** version — sharing one geometry per stage.
>
> **Status:** planning only. No geometry extracted yet. This doc is the handoff for the
> Mac build engine (phases 1–5) and Windows QA (phase 6). Pick it up on the desktop and go.

---

## 1. What these stages actually are

The user knew "rally stages in Rangely" but not the name. They are:

**Rally Colorado** — an **American Rally Association (ARA)** stage-rally event based in the town
of **Rangely, Rio Blanco County, northwest Colorado** (~40.087° N, 108.796° W), a few miles from
the Utah line and Dinosaur National Monument. Promoted to **National championship** status for
2026. The competition roads are **gravel/clay/hard-packed dirt** county roads on the mesas and in
the canyons west of town — fast sweeping sections mixed with extremely tight technical stuff,
5,000–7,000 ft elevation, big crests, and exposed drop-offs of hundreds of feet. ~137–140 stage
miles over ~13–14 stages across two days (most stages run twice).

**These are real, named County Roads** → their geometry lives in **OpenStreetMap**, so the
primary path is **`gps-extraction` (Overpass)**, not aerial tracing. (Exceptions and the OSM-gap
fallback are called out in §5.)

The **paved variant is deliberate fiction** — these roads are not tarmac in reality. There is no
data to hunt for: the paved version reuses the *identical* centerline + elevation and only swaps
the surface material and physics. Don't send anyone looking for a paved source.

### Signature stage roster (from 2024–2025 itineraries)

| Stage name            | Road            | Notes                                             |
|-----------------------|-----------------|---------------------------------------------------|
| Cathedral             | CR 100 West     | Signature stage                                   |
| Dragon Tail           | CR 116 / 133 NW | Twisty, technical                                 |
| Under the Dragon      | CR 109          | Pairs with Dragon Tail                            |
| Valley of the Gods    | CR 131 E        | Scenic, red-rock, exposed                         |
| Quest for Darwin      | CR 73 West      | Fast                                              |
| Earl's Revenge        | CR 96 West      | Fast                                              |
| *Douglas Creek*       | —               | Historical (2024); optional                       |
| *Dragon Trail*        | —               | Historical (2024); optional                       |
| *Presser*             | —               | Historical (2024); short (~1 mi), kinks + crests  |

Recommended first-pass scope: the **6 signature stages** (rows 1–6). Each → 2 variants =
**12 installable tracks**. The 3 historical stages are optional stretch goals.

> **Scope decision for the user (see §12):** all 6 stages now, or validate the full pipeline on
> **one** stage end-to-end first (recommended) then batch the rest?

Sources: [Herald Times — Rally Colorado returns to Rangely](https://www.theheraldtimes.com/rally-colorado-returns-to-rangely/rangely/) ·
[Grassroots Motorsports — Rally Colorado 2025 recap](https://grassrootsmotorsports.com/articles/rally-colorado-2025-recap/) ·
[ARA — National Champions Join the Field](https://www.americanrallyassociation.org/post/national-champions-join-the-field-for-rally-colorado) ·
[Rangely Chamber — Rally Colorado](https://www.rangelychamber.com/rally-colorado/) ·
[rally-maps.com — Rally Colorado 2026 stages (Google Maps/GPX)](https://www.rally-maps.com/Rally-Colorado-2026)

---

## 2. The paved-vs-dirt fork (the core architectural decision)

Per `CLAUDE.md`, layout variants "share one kn5 and differ only in AC configuration." **Paved vs
dirt is *not* just AC config** — it changes both the **road material/texture** (asphalt vs gravel)
and the **physics friction** (`surfaces.ini`). So the two variants are **not** two `layouts[]`
entries of one config. They are two builds that **share all upstream geometry** and **fork late**:

```
per stage:  centerline.geojson ─┐
            dem.tif / heightfield ├─► track.obj (1ROAD/GRASS/1KERB + dummies)   ← built ONCE
            projection/origin/N ─┘            │
                                              ├─►  variant: GRAVEL  → gravel material + dirt surfaces.ini → <stage>_gravel.kn5 + folder
                                              └─►  variant: TARMAC  → asphalt material + road surfaces.ini → <stage>_tarmac.kn5 + folder
```

The fork point is **between phase 4 (mesh) and phase 5 (material JSON → kn5)**. Everything before
it is identical and built exactly once per stage. This honors the "one geometry" principle while
being honest that a gravel road and a tarmac road do not look or behave the same.

### What has to change to make dirt real (the one pipeline addition)

`scripts/ac/track_folder.py::surfaces_ini()` currently **hardcodes tarmac**:

```python
("ROAD", dict(FRICTION=0.99, DAMPING=0, IS_VALID_TRACK=1, DIRT_ADDITIVE=0, IS_PITLANE=0), ...)
```

Add a **config-driven `road_surface`** knob (`"tarmac"` | `"gravel"`) read by both the surface
emitter and the material JSON. Proposed gravel profile:

| Param            | Tarmac (today) | Gravel (new)         | Why                                             |
|------------------|----------------|----------------------|-------------------------------------------------|
| `FRICTION`       | 0.99           | ~0.68–0.72           | Loose surface, far less grip                     |
| `DAMPING`        | 0              | ~0.03                | Soft, energy-absorbing surface                   |
| `DIRT_ADDITIVE`  | 0              | 1                    | Car picks up dust/dirt (visual + tyre)           |
| `WAV`            | road           | gravel/dirt          | Stock AC gravel roll sound (by name, not shipped)|
| `IS_VALID_TRACK` | 1              | 1                    | Still the racing surface                         |

Plus the **material JSON** (phase 5) selects a **gravel road shader/texture** for the gravel
variant vs an **asphalt** shader for tarmac. Same `1ROAD_*` mesh prefix in both — only the
material bound to it differs.

**Recommended config shape** — one `track.config.json` per stage carrying a variant list, so the
export stage loops it and the whole thing stays reproducible from config:

```jsonc
"surface_variants": [
  { "id": "gravel", "road_surface": "gravel", "ui_suffix": "Gravel" },
  { "id": "tarmac", "road_surface": "tarmac", "ui_suffix": "Tarmac" }
]
```

Slug convention: `rally_co_<stage>_gravel`, `rally_co_<stage>_tarmac`
(e.g. `rally_co_cathedral_gravel`).

---

## 3. Point-to-point, not a loop (pipeline note)

Rally stages are **point-to-point sprints**, not closed loops → `"loop": false`.
`scripts/geometry/build_mesh.py` is written for "one closed loop + connectors." Before building,
**confirm the ribbon builder accepts an open (non-closed) centerline**; if it hard-assumes loop
closure, that's a small addition (open the ribbon, don't weld the ends). Dummy placement changes too:

- `AC_START_0..N` — at the stage **start** (grid the spawns down the opening straight).
- `AC_TIME_0_L/R` — start line ~30 m **ahead** of `AC_START` (spawning *on* the line never arms
  the timer — see `ac-track-modding`).
- `AC_TIME_1_L/R … N` — sector splits; final pair at the **finish**.
- `AC_HOTLAP_START_0` — at the start.
- `AC_PIT_*` — a short service/pit area at the start is fine; a point-to-point has no pit loop.

---

## 4. Per-stage character → build knobs

These are **narrow high-desert gravel roads**, nothing like the Sand Creek urban loop. Set:

- **`default_width_m` ≈ 5.5–7 m** (single-track gravel county road), with `width_overrides` for
  widenings/junctions. *Not* 9 m urban.
- **`road_edge.profile` = default gravel/soft shoulder** — **no** curb/sidewalk profile. Rally
  roads have soft berms and steep drop-offs, not curbs.
- **Elevation is king here.** Use `elevation` skill → **USGS 3DEP 1 m** (US coverage, primary).
  Terrain is *not* gentle: big crests, canyon drop-offs of hundreds of feet. Smooth **along the
  racing line** to kill stepping, but **preserve real crests and the drop-off edges** — don't
  flatten them. Do **not** use `track-grading` (that invents banking for purpose-built circuits;
  public roads get real 3DEP elevation only, no fictional camber).
- **`road-grounding` skill is essential** — embankment fills where the road sits above grade,
  drape the shoulder/edge strips onto real terrain, and **bridge deep gaps** rather than paving a
  mesa. The exposed drop-offs must read as cliffs beside the road, not floating deck.
- **Scenery = sparse high desert:** low `tree_cap`, sparse sagebrush/scrub, pinyon-juniper on the
  mesas, red-rock. Mirror the "desert track wants sparser, lower scrub" note in the Sand Creek
  config. Generous `corridor_margin_m` so nothing scatters into the road.
- **Length:** stages run ~8–16 mi (13–26 km). These centerlines are **long** — mind resample
  spacing (~2–5 m) and mesh triangle budget; the audit/drive gates sweep the whole corridor.

---

## 5. Data source strategy (first principle)

> *The screenshot is a selection aid, not data. Geometry derives from OSM via Overpass; KML only
> where the route leaves the real network.*

1. **Primary — `gps-extraction` (Overpass):** the named County Roads are in OSM. Per stage,
   identify the CR way(s) from the rally map, pull them via Overpass, order + resample +
   width-tag → `data/centerline.geojson`.
2. **Selection aid:** grab a **Google Maps / satellite screenshot** per stage and the
   **rally-maps.com GPX/Google-Maps trace** to know *which* OSM ways to select and where the stage
   starts/ends. Use the GPX to pick roads — **not** to trace coordinates.
3. **OSM-gap fallback:** northwest CO has BLM two-tracks and ranch roads that OSM covers patchily.
   Where a stage segment is **missing or crude in OSM**, either (a) supply that segment as **KML**
   from the rally-maps GPX (`source.type: "kml"`, per-segment), or (b) if only imagery exists, use
   the **`aerial-tracing`** skill to trace the asphalt/gravel ribbon off a georeferenced satellite
   screenshot. Note per-stage in `source/route-notes.md` which path each segment used.

---

## 6. Repo layout for the rally

Each stage is an **independent standalone track** (they're geographically far apart across the
county — do **not** merge them into one kn5 the way `k10-colorado/_detailed/*` shares a frame).
Group them under one umbrella project for discoverability:

```
projects/rally-colorado/
├── BUILD_PLAN.md                 # this file
├── source/
│   ├── route-notes.md            # per-stage: CR ways, start/finish, OSM-gap notes, screenshots
│   └── <stage>_*.png / *.gpx     # selection-aid screenshots + rally-maps GPX per stage
└── <stage-slug>/                 # one per stage, e.g. cathedral/
    ├── source/                   # stage screenshot, any KML
    ├── data/                     # centerline.geojson, dem.tif, heightfield.npy
    ├── build/                    # <slug>_gravel.kn5, <slug>_tarmac.kn5, track folders
    └── track.config.json         # source of truth (incl. surface_variants[])
```

---

## 7. Phase-by-phase build (per stage)

Maps onto the `CLAUDE.md` pipeline. Phases 1–5 are code-driven on the **Mac** build engine;
phase 6 is the manual **Windows** loop.

| Phase | Task | Skill | Fork? |
|------:|------|-------|-------|
| 0 | Gather per-stage: Google Maps screenshot, CR name, start/finish, route notes | — | shared |
| 1 | Identify CR way(s) → Overpass (KML/aerial fallback for OSM gaps) → ordered, resampled, width-tagged `centerline.geojson` | `gps-extraction` (`aerial-tracing` fallback) | shared |
| 2 | Sample **USGS 3DEP 1 m** along the line + margin grid, smooth along racing line (keep crests/drop-offs) | `elevation` | shared |
| 3 | Project lon/lat/elev → local metres, set `origin` (centroid), resolve + write `true_north_rotation_deg` | `geometry` / `lighting` | shared |
| 4 | Road ribbon (`1ROAD`) + grass heightfield (`GRASS`) + **road-grounding** (embankments, edge drape, bridges) + dummies (point-to-point) | `geometry` / `road-grounding` / `ac` | shared |
| — | **Gates:** `mesh-audit` + `drive-test` (both exit-nonzero; must pass before export) | `mesh-audit` / `drive-test` | shared |
| 5a | **Gravel variant:** gravel material JSON + `road_surface: gravel` surfaces.ini → headless Blender → `<slug>_gravel.kn5` + track folder | `ac` / `lighting` | **gravel** |
| 5b | **Tarmac variant:** asphalt material JSON + `road_surface: tarmac` surfaces.ini → headless Blender → `<slug>_tarmac.kn5` + track folder | `ac` / `lighting` | **tarmac** |
| 6 | `scripts.ac.install` → drive both variants, record AI fast line, visual QA (**Windows**) | `ac` | per-variant |
| 7+ | Objects: guardrail/berm barriers, cattle guards, canyon-edge markers, sparse desert scatter, start banner — iterative | `ac` | shared mesh |

Headless export per variant:

```bash
blender --background --python scripts/ac/build_kn5.py -- projects/rally-colorado/<stage> --variant gravel
blender --background --python scripts/ac/build_kn5.py -- projects/rally-colorado/<stage> --variant tarmac
```

*(`--variant` is the phase-5 fork flag to add alongside the `road_surface` config knob.)*

---

## 8. Lighting

Rangely ≈ **40.087° N, 108.796° W**, `America/Denver`. Rally runs **mid-July** (2026: Jul 18–19).
Use the `lighting` skill to resolve `true_north_rotation_deg` (written back to config so in-game
shadows match the real sun) and emit presets. Suggested: **morning** (event start light),
**noon** (harsh high-desert overhead — the real look), **golden_hour** (long mesa shadows). AI
line + shadow QA on the first Windows drive.

---

## 9. Recommended build order

1. **Validate the fork on ONE stage first** — recommend **Cathedral (CR 100 West)**. Take it fully
   through phases 1–6 in **both** variants. This proves: the config-driven `road_surface` knob, the
   gravel `surfaces.ini` profile, the gravel-vs-asphalt material JSON, the point-to-point dummy/timing
   setup, and road-grounding over real drop-offs. Fix the pipeline gaps (§2 surfaces knob, §3 open
   ribbon) here, once.
2. **Batch the remaining 5 signature stages** through the now-proven pipeline. Geometry once each,
   two exports each.
3. **Optional:** the 3 historical stages (Douglas Creek, Dragon Trail, Presser).

Deliverable count for the first pass: **6 stages × 2 variants = 12 installable AC tracks.**

---

## 10. Windows QA checklist (phase 6, per variant)

- Track installs via `scripts.ac.install` and loads in CM/CSP.
- Car spawns behind the start line; **timer arms** (line is ~30 m ahead of `AC_START`).
- Gravel variant *feels* loose (FRICTION ~0.7, dust kicks up); tarmac variant grips.
- No mesh cruft: road doesn't float, drop-offs read as cliffs, no terrain poking through
  (`mesh-audit` + `drive-test` already gate this on Mac — confirm in-sim).
- Shadows align with time-of-day presets (true-north sanity).
- Record AI fast line per variant; sector splits trigger.

---

## 11. Source assets to gather (phase 0, before any code)

Drop into `projects/rally-colorado/source/` and per-stage `source/`:

- [ ] Google Maps / satellite **screenshot** per stage (selection aid).
- [ ] **rally-maps.com GPX** (or Google-Maps trace) per stage → identifies OSM ways + start/finish.
- [ ] County Road number + stage start/finish points noted in `source/route-notes.md`.
- [ ] Flag any segment that is **missing/crude in OSM** (→ KML or aerial-tracing fallback).

---

## 12. Open questions for the user (resolve before batching)

1. **Scope:** all 6 signature stages now, or Cathedral-first end-to-end (recommended) then the rest?
   Include the 3 historical stages?
2. **Variant packaging:** two separate installable tracks per stage (`_gravel`, `_tarmac`) —
   assumed — or one track with a surface toggle? (Two tracks is simpler and more robust in AC.)
3. **Stage direction:** run each stage in its real (single) rally direction, or also a reverse
   layout? (Reverse is cheap — same mesh, second AI line.)
4. **Fidelity ceiling:** is the paved variant purely "what-if fun," or should it get its own
   corner markers / tarmac furniture in phase 7? (Affects object-pass budget.)
```
