# Installable tracks (git-pullable)

Each subfolder here is a **ready-to-run Assetto Corsa track**, exactly as it appears in Content
Manager — the same thing the GitHub Release `.zip` contains, but kept in the repo so you can pull
updates instead of re-downloading a zip each time.

```
tracks/sand_creek_raceway/
├── sand_creek_raceway.kn5      # the model (all textures embedded)
├── models_full.ini · models_interior.ini
├── extension/ext_config.ini    # CSP: GrassFX, water, RainFX, lights
├── data/ (surfaces.ini, map.ini) · ui/ (per layout) · ai/ · map.png · CREDITS/LICENSES/README
```

Each build refreshes these via `scripts/build.sh` (the `pack` stage rsyncs the built folder here).

## Point Assetto Corsa at it — one-time setup

Clone this repo somewhere (e.g. `D:\dev\prodrive-ac-builder`), then link the track folder into your
AC `content\tracks`. A **junction** makes AC see the repo folder as if it were a real track, so a
later `git pull` updates the track in place — no copying, no re-install.

**Windows** (Command Prompt — junctions need no admin; adjust both paths):

```bat
mklink /J "C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\content\tracks\sand_creek_raceway" "D:\dev\prodrive-ac-builder\tracks\sand_creek_raceway"
```

**macOS / Linux:**

```sh
ln -s "/path/to/prodrive-ac-builder/tracks/sand_creek_raceway" "/path/to/assettocorsa/content/tracks/sand_creek_raceway"
```

## Getting updates

```sh
cd /path/to/prodrive-ac-builder
git pull          # the linked track in content/tracks updates automatically
```

(The repo is **private** because the builds embed mod-derived assets — keep them out of any public
share.) The kn5 is ~32 MB and changes every release; if the clone history ever gets heavy we can move
`*.kn5` to Git LFS.
