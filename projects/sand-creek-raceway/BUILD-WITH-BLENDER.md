# Build the kn5 with Blender (no ksEditor) — Windows

This skips ksEditor entirely. You install Blender + one add-on, open the provided file, and click
Export. The file (`sand_creek_raceway.blend`) already has everything set up — geometry, textures
packed inside it, materials, and the `AC_START` / pit / timing markers — so there's no per-material
work and nothing to assign.

## 1. Install Blender (free)

Download and install the latest Blender from <https://www.blender.org/download/>.

## 2. Install the Assetto Corsa add-on

1. Open <https://github.com/jwl-7/blender-assetto-corsa-tools/releases>.
2. Download `blender_assetto_corsa_tools.zip` from the latest release (don't unzip it).
3. In Blender: **Edit → Preferences → Add-ons**, click **Install…** (on newer Blender it's the
   ▾ menu → **Install from Disk**), and pick that zip.
4. Tick the checkbox next to **"Assetto Corsa (.kn5)"** to turn it on.

## 3. Open the track file

**File → Open** → select `sand_creek_raceway.blend` (from this zip). You'll see the track in the
3D view.

## 4. Export the kn5

**File → Export → Assetto Corsa 3D (.kn5)** → save it as `sand_creek_raceway.kn5`.

## 5. Install it

Copy that kn5 into your existing track folder, **replacing** the broken one:

```
…\steamapps\common\assettocorsa\content\tracks\sand_creek_raceway\sand_creek_raceway.kn5
```

Load **Sand Creek Raceway — full** and drive. Everything else in that folder (`surfaces.ini`, `ui/`,
`models_full.ini`, `map.png`) is already correct.

## If something's off

I can't run this add-on from my side (it's Windows-only), so if the **Assetto Corsa 3D (.kn5)**
option isn't in the Export menu, or it throws an error, **send me the exact message**. The file is
already arranged the way the add-on expects — physical meshes named `1ROAD_main` / `1GRASS` /
`1KERB_corners`, textures packed in, AC markers placed — so most snags will be add-on version quirks
I can adjust for quickly.
