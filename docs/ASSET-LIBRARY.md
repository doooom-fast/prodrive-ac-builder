# Owned 3D Asset Library — Dropbox `/Blender`

Inventoried **2026-08-10** from Kevin's Dropbox (all items downloaded 2026-07-21 → 07-24).
This library is the **primary asset source** for v2 builds (CLAUDE.md rule 8) and the exit path
from the v1 licensing landmine (`V1-AUTOPSY.md` §6). Per-location mapping happens in each
dossier §8; this file is the master list.

**License status: ⚠ UNRECORDED for every item.** First use of any asset requires identifying
its source store + license and adding it to `assets/licenses.json`. Kevin: if you remember where
each came from (Sketchfab/CGTrader/TurboSquid/Poly Haven/etc.), note it — free downloads often
allow personal use but not redistribution, which caps a track at DoD T4 until cleared or
replaced by a purchased/CC0 equivalent.

## Barriers & road furniture
| Asset | Files | Notes |
|---|---|---|
| Concrete Barrier 4 MTS + Transition | `Concrete Barrier and Transition Barrier - Models and Textures/`, ` … OBJ/` (OBJ+MTL + full PBR sets) | Jersey-style, 4 m modules — exactly Sand Creek's v1 barrier need; **top pick for the in-game proof** |
| Barrier set | `Barrier02.obj`, `Barrier_end01/02.obj`, `Barrier_circle.obj`, `barriers_MA.rar`, `Road_Barrier.blend` (+`Road_Barrier_Texture2.png`), `RoadBlockade_02.blend` | Duplicates present (`Barrier02 2.obj`) |
| Stop-sign barriers | `barrier_stopSign01/02.obj` | |
| US traffic signs pack | `obj/traffic signs-01.obj` + `.mtl` + 57 numbered sign JPGs + `galvanized.jpg` | Street blades/regulatory set — big realism lever for street loops; **proof candidate** |
| Overhead highway sign | `Highway_OverheadSign.obj` | For freeway backdrop stretches |
| Fences | `Fence.FBX`, `FENCE.rar`, `wooden_fence_mt1.zip` (216 MB), `Wooden_Fence_Geo_Piskas_new_obj.rar` | Chain-link need may still be procedural (`make_chainlink`) |

## Lighting & utility
| Asset | Files | Notes |
|---|---|---|
| Street lamps | `Street_Lamp.zip` (19 MB), `Street_light_obj.rar`, `black_lamp_spotII_01.blend` | **Proof candidate** (day geometry + CSP night light later) |
| Utility pylon | `Pylone.blend` | Pairs with v1's procedural power-line cables |

## Buildings & industrial
| Asset | Files | Notes |
|---|---|---|
| Modular buildings | `ModularBuildings.blend1` (**1.23 GB — a Blender backup file**; open & re-save as `.blend`, or re-download), `building_1.blend`, `building_05_blend.rar` (84 MB) | Replaces mined Hamburg building textures |
| Highway modular set | `Highway_modular_set.blend` (14.6 MB) | Decks/ramps for backdrop freeways |
| Cargo container | `Cargo_Container.obj` + `Textures/Cargo Container_*` (BaseColor/Normal/Roughness/Metallic/Height) | Commerce City container yards — direct fit |
| Racetrack scene | `Racetrack_1.blend` (617 MB) | Reference/kit-bash source; too heavy to import wholesale |

## Vegetation & terrain
| Asset | Files | Notes |
|---|---|---|
| Poplar trees | `tree_topol.rar` (229 MB) | "Topol" = poplar — right family for Commerce City creek rows |
| Pine trees | `pine_tree.zip` (93 MB) | For IMI/mountain locations later |
| Cliff | `cliff.obj` (303 MB) | Heavy; decimate before any use |

## Surface textures & sky (Poly Haven naming → CC0, confirm)
`textures-2/`: `concrete_wall_008` 4K set, `grass_path_2` 4K set, `rusty_painted_metal` 4K set,
`bloem_hill_02_4k.exr` (HDRI sky), `door.png`; plus `Textures.rar` (104 MB), `textures.zip`,
`Cargo Container` set above.

## Conversion pipeline (applies to every import)
1. Extract archives (`.rar` needs `unrar`/`7z` — re-store as zip in the project).
2. Verify scale in meters & Y-up at the projection boundary; fix on import, once.
3. Textures: power-of-two (build preflight enforces), EXR → PNG/JPG (AC has no EXR), normal-map
   G-channel convention checked (OpenGL vs DirectX), sensible resolution (≤2K for props).
4. Materials: bind via `scripts/ac/pbr.py` table (name-prefix → texture set → shader).
5. License entry in `assets/licenses.json` **before** the asset enters a build.
6. Poly budget: props ≤10k tris preferred; decimate heavy models; AC's 65,535 verts/mesh cap
   is enforced by `verify_kn5`.

## Related Dropbox holdings (dossier inputs, not assets)
- `/simracing/` — Kevin's drive/session recordings (2026-06-23, 07-09 ×4, 07-11 ×3; multi-GB
  each) + `mods archive/`, `projects/`, `K10/`.
- Root — `Untitled_Scan_13_05_26.las` (LiDAR, 2026-08-02, 235 MB), `route map.pdf` (2026-07-24).
