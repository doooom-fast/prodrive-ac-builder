# Prodrive AC Builder — Project Plan

Convert real-world road loops into playable **Assetto Corsa** tracks. Given a Google Maps
screenshot, a location, and route notes, produce a complete, installable AC track — real geometry,
real elevation, accurate lighting, and multiple layout variants — reproducible end-to-end from a
single `track.config.json`.

**First target:** **Sand Creek Raceway** — a street loop in Commerce City, Colorado (`projects/sand-creek-raceway/`).
See [route-notes.md](../projects/sand-creek-raceway/source/route-notes.md) for the marked layout.

---

## 1. Architecture

**First principle — the screenshot is a selection aid, not data.** Precise geometry derives from
**OpenStreetMap via Overpass**; hand-drawn **KML** is used *only* where the route deliberately
leaves the real road network.

**Reproducibility — everything flows from `track.config.json`.** No hardcoded coordinates, widths,
or rotations in code; derived values (e.g. `true_north_rotation_deg`) are written back to config.

**Build environment split:**

| Platform | Role |
|----------|------|
| **Mac** (headless) | Data acquisition, geometry processing, Blender mesh build, kn5 export. Phases 1–5. |
| **Windows** | AC + Content Manager + CSP — driving, AI line recording, visual QA. Phase 6. |

## 2. The four skills

1. **`gps-extraction`** — Overpass + KML → ordered centerline, resampled ~2–5 m, width-tagged, looped, connectors named.
2. **`elevation`** — USGS 3DEP 1 m (→ OpenTopography → SRTM 30 m) sampled along the line + margin grid, smoothed.
3. **`lighting`** — solar position, true-north orientation, CSP/Sol presets (`morning`/`noon`/`golden_hour`).
4. **`ac-track-modding`** — surface naming (`1ROAD_`/`1KERB_`), AC dummies, materials, headless Blender → kn5, track folder.

## 3. Build pipeline

| Phase | Task | Where | Skill |
|-------|------|-------|-------|
| 0 | Provide screenshot, location, route notes | Claude Code | — |
| 1 | Identify roads → Overpass/KML → resampled centerline | Mac | `gps-extraction` |
| 2 | Sample USGS 3DEP elevation + margin grid, smooth | Mac | `elevation` |
| 3 | Project lat/lon/elev → local meters, set origin + true north | Mac | `geometry`/`lighting` |
| 4 | Road ribbon (`1ROAD`) + grass heightfield (`GRASS`) + dummies | Mac | `geometry`/`ac` |
| 5 | Material JSON → headless Blender → kn5 + track config | Mac | `ac`/`lighting` |
| 6 | Install, drive, record AI lines, QA | **Windows** | `ac` |
| 7+ | Objects: barriers, kerbs, trees, buildings — iterative passes | Mac→Win | `ac` |

## 4. `track.config.json`

The source of truth. Layouts are route variants that **share one kn5** and differ only in AC config
(connectors, AI line). Current Sand Creek Raceway values live in
[track.config.json](../projects/sand-creek-raceway/track.config.json).

---

# 5. Existing tools & asset sources (research)

> Where our code-driven pipeline fits: we **generate** road + terrain from OSM/USGS, so the biggest
> external needs are (a) **context buildings** (importable straight from OSM), and (b) **decoration
> assets** for phase 7+ (trees, barriers, signs, rocks, water). The whole-pipeline builders below
> (RTB, TreCorsa) are alternatives worth studying even though we don't depend on them.
>
> **Licensing matters.** CC0 (ambientCG, Poly Haven) is unrestricted. Fab/Megascans is free with an
> Epic account under the Fab license. Many Blender addons and AC community objects are paid or have
> per-mod terms — **do not redistribute Kunos/third-party assets** inside our track without checking.

## 5.1 End-to-end AC track builders (alternatives / reference)

| Tool | What it does | Cost | Link |
|------|--------------|------|------|
| **Race Track Builder (RTB)** | The classic. Pulls Google Maps terrain, edit track via splines, ships barriers/walls/kerbs, exports **FBX → ksEditor → kn5**. | Paid (Steam) | [Steam](https://steamcommunity.com/app/388980/positivereviews/) · [RTB→Blender](https://assettocorsamods.net/threads/race-track-builder-to-blender.2441/) · [RTB+Blender tutorial](https://www.overtake.gg/threads/tutorial-use-race-track-builder-and-blender-together.207713/) |
| **TreCorsa** | Browser-based AC track builder — barriers, kerbs, signs, trees, cliffs, rocks, water; exports a zip you drop into Content Manager (no Blender/ksEditor). | See site | [trecorsa.com](https://trecorsa.com/) |
| **Blender + AC Blender Tools** | Our approach — full mesh control in Blender, kn5 export via the addon. | Free | (used by this project) |
| **ksEditor + AC SDK** | Official Kunos editor: assign materials/settings to imported FBX (FBX2012), save as kn5. SDK is in **Steam → Library → Tools**. | Free w/ AC | [SDK (Steam Tools)](https://www.overtake.gg/threads/assetto-corsa-modding-tools-released.88524/) · [Modded ksEditor](https://ascobash.wordpress.com/2015/07/22/kseditor/) · [ksEditor guide](https://www.sim-garage.co.uk/working-with-kseditor-the-assetto-corsa-editor/) |
| **Content Manager** | Track install/management, packaging, showroom. The de-facto AC front-end. | Free | [acstuff.club](https://acstuff.club/) |
| **Custom Shaders Patch (CSP)** | Graphics extension — GrassFX, WaterFX, dynamic lighting, TreeFX. Track config via `ext_config`. | Free (Patreon previews) | [patch](https://acstuff.club/patch/) · [config repo](https://github.com/ac-custom-shaders-patch/acc-extension-config) |

## 5.2 Real geometry & terrain → Blender

| Tool | What it gives | Cost | Link |
|------|---------------|------|------|
| **Blosm** (ex *blender-osm*) | One-click import of **OSM buildings** (with heights + geometry-nodes "realistic" option), **terrain** (~30 m), **GPX tracks projected onto terrain** (great for racing lines), rivers/lakes/forests/roads-with-width projected on terrain, and **Google 3D cities** (premium). | Free base + paid premium | [Gumroad](https://prochitecture.gumroad.com/l/blender-osm) · [GitHub](https://github.com/vvoovv/blosm) |
| **BlenderGIS** | Bridge to GIS data — import **Shapefile**, **georef raster / GeoTIFF DEM**, **OSM**; Delaunay terrain meshing; georef camera setup. | Free (GPL) | [GitHub](https://github.com/domlysz/BlenderGIS) · [Import georef raster](https://github.com/domlysz/BlenderGIS/wiki/Import-georef-raster) |
| **OSM / Overpass** | Road centerlines, footprints, land use (our primary geometry source). | Free | [overpass-api.de](https://overpass-api.de/) |
| **USGS 3DEP** | 1 m DEM for US locations (our primary elevation). | Free | The National Map / 3DEP ImageServer |
| **OpenTopography / SRTM** | DEM fallbacks (wider/global coverage). | Free | opentopography.org |

> For Commerce City's industrial blocks, **Blosm/BlenderGIS importing OSM building footprints +
> simple extrusion + CC0 facade textures** is the pragmatic way to fill background context.

## 5.3 Trees & vegetation

| Tool | What it gives | Cost | Link |
|------|---------------|------|------|
| **Tree It** | Free **low-poly tree generator** built for games/sims; exports FBX/OBJ — well suited to AC trees. | Free | [evolved-software.com](http://www.evolved-software.com/treeit/treeit) · [Steam](https://store.steampowered.com/app/2386460/Tree_It/) |
| **Alpha Trees (Pro)** — Strike Digital | **Billboard / camera-facing** trees (4 verts/card, ~148 trees), procedural scatter by slope/height — high performance, ideal for sim view distances. | Paid | [Gumroad](https://strike-digital.gumroad.com/l/Alpha-Trees) · [Superhive](https://superhivemarket.com/products/alpha-trees/) · [ArtStation](https://strike_digital.artstation.com/projects/OoDXKw) |
| **The Grove 3D** | Realistic procedural trees + wind animation. | Paid | [thegrove3d.com](https://www.thegrove3d.com/) |
| **Sapling Tree Gen** | Built-in Blender tree generator. | Free (bundled) | Blender add-ons |
| **Geo-Scatter** | Scatter trees/rocks/grass over terrain; premade billboard-forest biomes. | Paid | [geoscatter.com](https://www.geoscatter.com/biomes.html) |
| **CSP GrassFX** | In-engine procedural grass for AC tracks (configure via `grass_fx.ini` mixin). | Free | [GrassFX wiki](https://github.com/ac-custom-shaders-patch/acc-extension-config/wiki/Tracks-%E2%80%93-Grass-FX) |
| **TreeFX / TreePlanter** | Community workflow to place/replace AC track trees with 3D ones (needs CSP). | Free (per-mod) | [TreePlanter](https://www.overtake.gg/downloads/3d-trees-in-2-minutes-with-treeplanter.59142/) · [3d-trees tag](https://www.overtake.gg/tags/3d-trees/) |

## 5.4 Buildings

| Source | What it gives | Cost | Link |
|--------|---------------|------|------|
| **Blosm / BlenderGIS** | OSM footprints extruded to massing; quickest path to real context buildings. | Free/freemium | (see 5.2) |
| **KitBash3D** | High-detail modular building/urban kits. | Paid | [kitbash3d.com](https://kitbash3d.com/) |
| **Fab / Sketchfab** | Individual building models (check license per asset). | Free + paid | [fab.com](https://www.fab.com/) |

## 5.5 Rock & terrain detail

| Source | What it gives | Cost | Link |
|--------|---------------|------|------|
| **Quixel Megascans (now on Fab)** | Photoreal **rocks**, cliffs, ground scans, vegetation; free with an Epic account. | Free (Fab license) | [fab.com](https://www.fab.com/) · [quixel.com](https://quixel.com/megascans/free) |
| **Poly Haven** | CC0 rocks, ground textures, HDRIs, some models. | CC0 | [polyhaven.com](https://polyhaven.com/) |
| **ambientCG** | 1,000+ CC0 PBR materials — rock, gravel, asphalt, grass, dirt (up to 8K). | CC0 | [ambientcg.com](https://ambientcg.com/) |
| **Blender Rock Generator** | Procedural rocks (Add Mesh: Extra Objects). | Free (bundled) | Blender add-ons |

## 5.6 Water

| Source | What it gives | Cost | Link |
|--------|---------------|------|------|
| **CSP WaterFX** | AC's in-engine water shader for ponds/streams around a track (configured via `ext_config`). | Free | [CSP](https://acstuff.club/patch/) · [config repo](https://github.com/ac-custom-shaders-patch/acc-extension-config) |
| **Example: Fonteny** | Reference track using CSP water shader + seasons + grass. | Free (per-mod) | [OverTake](https://www.overtake.gg/downloads/fonteny-rainfx-seasons-water-shader-more-lights-and-grass.41984/) |
| **Blender ocean/plane** | Author the water mesh; AC material/CSP does the look in-engine. | Free | Blender |

> Commerce City has **Sand Creek** nearby — a CSP WaterFX strip is the likely approach if the route
> crosses or borders it.

## 5.7 Highway / road furniture (barriers, signs, kerbs, poles)

| Source | What it gives | Cost | Link |
|--------|---------------|------|------|
| **RTB asset packs** | Ships guardrails, walls, kerbs, fences tuned for race tracks. | Paid | (see 5.1) |
| **TrackDecoration** | 48 objects — cones, poles, flags, markers, start/finish gate, lights, tyre stacks, trees. | Free (per-mod) | [OverTake](https://www.overtake.gg/downloads/trackdecoration.76979/) |
| **Fab / Sketchfab** | Guardrails, traffic signs, street lights, jersey barriers. | Free + paid | [fab.com](https://www.fab.com/) |
| **ambientCG / Poly Haven** | Road-marking + asphalt + concrete materials for `1ROAD`/walls. | CC0 | (see 5.5) |

## 5.8 Materials & textures (CC0 baseline)

[ambientCG](https://ambientcg.com/) · [Poly Haven](https://polyhaven.com/) — CC0, no attribution.
[Poliigon](https://www.poliigon.com/) — paid, higher-end. Grab CC0 asphalt/grass/concrete/gravel
starter sets first; reserve Fab/Megascans for hero rock and vegetation.

## 5.9 Community & reference

- **OverTake.gg** (formerly RaceDepartment) — downloads + track-building forums. [overtake.gg](https://www.overtake.gg/)
- **Assetto Corsa Mods** — tutorials incl. [GrassFX setup](https://assettocorsamods.net/threads/how-to-enable-grass-fx-on-my-track.1890/) and RTB→Blender.
- **Witt'z End** — [Advanced 3D roadway modeling for AC](https://wittzend.com/2024/11/18/crafting-custom-circuits-advanced-3d-roadway-modeling-techniques-for-assetto-corsa/).
- **GTPlanet** — [AC track reviews/threads](https://www.gtplanet.net/forum/threads/assetto-corsa-track-reviews.398544/).
- **CSP config repo** — canonical `ext_config` reference for GrassFX/WaterFX/lighting. [GitHub](https://github.com/ac-custom-shaders-patch/acc-extension-config)

---

## 6. Recommended adoption for this project

- **Buildings/context:** import OSM footprints via **Blosm** (or BlenderGIS) in the Blender step — fits our OSM-first principle.
- **Grass:** **CSP GrassFX** in-engine (cheap, great looking) over heavy meshes.
- **Trees:** **Tree It** for a few custom low-poly models + **Alpha Trees**-style billboards for distance; place with TreePlanter-style passes in phase 7+.
- **Rock/water/road materials:** CC0 from **ambientCG**/**Poly Haven**; **CSP WaterFX** for Sand Creek.
- **Study, don't depend on:** **RTB** and **TreCorsa** as whole-pipeline references.
