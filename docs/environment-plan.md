# Sand Creek Raceway — environment & immersion plan

> **Status (June 2026): implemented.** The texture & objects pass landed: procedural texture suite
> (`scripts/ac/texgen.py`, ~30 textures incl. sign/tree/ad atlases), scenery geometry
> (`scripts/environment/scenery.py` — signs, signals, cobra-head streetlights, power lines, fences,
> **1WALL jersey barriers (real collision)**, guardrails, freeway decks+piers+gantries, tanks, rail,
> crosswalks, billboards, start gantry, horizon ring, multi-variant tree/bush billboards), building
> facade variants with parapets, double-yellow + edge-line paint, tire-wear overlay, and a fixed kn5
> export that actually embeds textures (see `kn5_native.py` patches). `zones.py` backfills the
> environment.geojson fetch; `scenery_fetch.py` pulls the detail features. Static QA:
> `kn5_inspect.py`; visual QA: `preview.py` / `qa_shots.py` / `flythrough.py`.

How to dress the track accurately: trees/bushes, water (Sand Creek), raised freeways, streetlights,
corner kerbs, and industrial detail. **Placement is data-driven** — it keys off real OSM features
(`data/environment.geojson`, regenerable via `scripts/environment/zones.py`), not guesswork. Asset
*sources* are catalogued in [PLAN.md §5](PLAN.md); this doc is the **where + how**, tied to the real map.

> See `data/environment.geojson` + the zone render. Counts pulled for the bbox around the loop:
> **304** highway segments, **143** green + **13** wetland, **86** water, **24** industrial,
> **14** commercial, **9** residential.

## The real zones (what the map actually is)

| Zone | Where (relative to the loop) | What goes there |
|------|------------------------------|-----------------|
| **Sand Creek corridor** | winds W→E straight **through the infield**, riparian green/wetland along it (esp. centre + SE) | flowing **water** mesh, dense **trees/bushes/scrub**, reeds, **GrassFX** |
| **Wilderness / wetland** | SE + E (Commerce City Wetland Park), bottom strips | trees, scrub, tall grass, a few water basins |
| **Raised freeways** | **I‑70 raised along the south edge**, **I‑70/I‑270/Vasquez cloverleaf on the west**, I‑270 diagonal NW | **elevated visual-only** road decks, pillars, guardrails, overhead signs |
| **Industrial lots** | **north / inside-top** of the loop, and **west** | warehouses (extruded OSM footprints), chain-link fences, light poles, containers, sparse weeds |
| **The track itself** | the 9.62 km ribbon | **kerbs** at corners, **streetlights** the whole way, barriers |

This matches your read: industrial up top/west, wilderness + creek through the middle/SE, raised
highways wrapping the south and west.

---

## 1. Trees, bushes & scrub  → green/wetland zones + Sand Creek banks

- **Density by zone:** dense along the creek + wetland park (SE/E), medium in green strips, ~none in
  industrial lots (a few weeds/volunteer trees only — keep it honest to an industrial edge).
- **Sources** (detail in PLAN.md §5): **Tree It** (free, low‑poly/billboard — ideal for sim view
  distance), **Alpha Trees** (camera‑facing cards), Quixel/Fab + Poly Haven scans for hero trees;
  scrub/reeds from ambientCG alpha cards. Cottonwood/willow/Russian‑olive fit Sand Creek riparian.
- **How to add:** scatter in Blender with **Geometry Nodes** or **Geo‑Scatter**, masked to the
  `green`/`wetland` polygons from `environment.geojson`; bake to billboards beyond ~80 m. In‑engine
  ground cover via **CSP GrassFX** (`[GRASS_FX]` mixin) over the `GRASS` mesh — cheap and great looking.

## 2. Water — Sand Creek (flowing) + basins  → the blue lines/polys

- Sand Creek is the signature feature: it runs *through* the circuit, so it'll be visible from most of
  the lap. Build it as a **water mesh** following the OSM `waterway` lines (banks from the riparian
  polygons), gently below terrain grade.
- **How to add:** assign the CSP water shader (**`smWaterSurface`**) and configure **WaterFX** in
  `ext_config` (flow direction along the creek, ripple, reflection). Still basins (E/SE) = flat water
  plane, same shader. Reference: the **Fonteny** track (water shader + seasons) and the
  [CSP config repo](https://github.com/ac-custom-shaders-patch/acc-extension-config).

## 3. Raised freeways (visual-only)  → I‑70 / I‑270 / Vasquez + the west cloverleaf

- These dominate the surroundings (304 segments) and wrap the south + west — modelling them is the
  single biggest immersion win. **Non‑drivable**, so cheap: extrude the OSM `motorway/trunk` lines
  into **elevated road decks** (raise to bridge height where they overpass), add **pillars** under the
  raised sections, **jersey/guardrail** along edges, and a few **overhead gantry signs**.
- **How to add:** a pipeline step ribbons the highway lines (like `1ROAD` but un‑prefixed = visual),
  lifts deck Y where OSM tags `bridge=yes`/`layer>0`, drops pillar instances on an interval. Assets:
  guardrail/pillar/sign from Fab/Sketchfab (CC) or kitbash; asphalt/concrete from ambientCG.

## 4. Streetlights — the whole lap  → along the centerline

- Place lamp standards at a fixed interval (≈ 40–50 m) down both verges of the ribbon (offset from the
  per‑vertex width, same math as the kerb/dummy placement). ~**200 lamps** over 9.6 km.
- **Night lighting (this is the important part):** give the lamp head an **emissive** material, then in
  `ext_config` add a **`[LIGHT_SERIES_N]`** so each actually casts light at night (CSP). The CSP
  **"Light Maker"** app generates these from placed dummies. Emissive glow via `MATERIAL_ADJUSTMENT`
  (`KEY_0=ksEmissive`, `ksAlphaRef=-193`). Refs:
  [lighting_fx.ini](https://github.com/ac-custom-shaders-patch/acc-extension-config/blob/master/config/lighting_fx.ini),
  [AC street-light how-to](https://assettocorsamods.net/threads/lighting.3677/),
  [track config docs](https://github.com/ac-custom-shaders-patch/acc-extension-config/blob/master/_doc_config_tracks.ini).
- **Pole/lamp models:** Fab/Sketchfab CC street lights, or a simple parametric pole we generate.

## 5. Corner kerbs (curbing)  → 1KERB at the corners

- Detect **high‑curvature** stretches of the centerline (corners) and lay a **kerb strip** on the inside
  (and optionally outside) edge: a short flat-topped ramp offset at `width/2`, named **`1KERB_*`** so
  AC treats it as a kerb (rumble already wired in `surfaces.ini` → `KEY=KERB`, vibration on).
- **Texture:** classic **red/white** alternating kerb (ambientCG / a generated stripe). Mild raised
  profile (~6–10 cm) so it rumbles without launching cars.
- **How to add:** new geometry step `kerbs.py` — curvature from the centerline, emit `1KERB_<corner>`
  ribbons; the kn5 export already assigns the kerb material via `materials.py`.

## 6. Industrial detail  → grey lots (N/W)

- Extrude OSM **building footprints** to massing (BlenderGIS/Blosm), low‑res facade textures
  (ambientCG), **chain‑link fences** along lot lines, light poles, **shipping containers**, power lines.
  Keep it low‑effort/background — it sells the "racing through an industrial park" feel.

---

## Pipeline: a new `environment` phase (7+)

Proposed `scripts/environment/` + an `environment` skill, all data‑driven off `environment.geojson`:

1. **`zones.py`** — already have the fetch/classify (this commit); load zones as masks.
2. **`scatter.py`** — trees/bushes/grass instanced onto `green`/`wetland` masks (Blender Geometry Nodes).
3. **`water.py`** — Sand Creek + basins → water mesh + WaterFX `ext_config`.
4. **`highways.py`** — `motorway/trunk` lines → elevated visual decks + pillars/guardrails.
5. **`streetlights.py`** — lamps along the centerline + `[LIGHT_SERIES]` `ext_config` (CSP Light Maker schema).
6. **`kerbs.py`** — curvature‑based `1KERB_*` at corners.
7. **`ext_config.py`** — assemble GrassFX + WaterFX + lighting into the track's `ext_config.ini`.

Everything keys off real geometry, so it stays **accurate to the map** and reproducible from
`track.config.json` + `environment.geojson` — same principle as the rest of the build.

## Priority order (most immersion per effort)

1. **GrassFX + kerbs** (cheap, on every lap) → 2. **Sand Creek water** (signature, central) →
3. **Streetlights + night lighting** → 4. **Raised I‑70/I‑270 decks** (big backdrop) →
5. **Trees/scrub scatter** → 6. **Industrial massing**.
