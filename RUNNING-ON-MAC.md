# Running prodrive-ac-builder on a Mac

The whole loop — build a track from a KML, export the kn5, and drive it — runs natively on macOS.
No Windows box, and (since `scripts.ac.kn5_export` replaced the Blender-hosted exporter) no Blender.

The split to keep straight:

| Lives on macOS (native) | Lives inside a Wine **bottle** (Windows) |
|-------------------------|------------------------------------------|
| The Python pipeline: GPS/Overpass, elevation, geometry, environment, **kn5 export** | **Steam**, **Assetto Corsa**, **Content Manager**, **CSP** |
| Claude Code CLI (optional, to drive the agent) | **Your mods** (cars + tracks) |

AC is a Windows game, so Steam/AC/CM/CSP/mods all install **into the bottle's Windows filesystem**,
exactly as they would on a real Windows PC — not into macOS. That same bottle content folder is what
the (future) asset-indexer scans to build the kitbash parts-bin, so installing your mods there does
double duty.

---

## 1. One-time setup

### Prerequisites
- **Homebrew** — https://brew.sh
- **Python 3.11+** — `brew install python@3.12`
- **CrossOver** (recommended) or Whisky/Wine — for the in-AC preview bottle. CrossOver is the
  best-supported path for AC + CSP on macOS.
- *(optional)* **Claude Code CLI** — to drive the agent locally (see §4).

### Bootstrap the pipeline
```bash
git clone <repo> prodrive-ac-builder && cd prodrive-ac-builder
git fetch origin claude/ac-track-gen-plugin-7j2qme
git checkout claude/ac-track-gen-plugin-7j2qme

./scripts/bootstrap_mac.sh        # venv + deps + test-suite verify
source .venv/bin/activate
```

The script creates `.venv`, installs the package with all pipeline deps, and runs the tests. The one
dependency that can fight you on macOS is `rasterio` (GDAL), used only by **elevation sampling** —
modern wheels are self-contained, but if it fails the script prints the `brew install gdal` fallback.
The build → export → preview loop works even without rasterio.

---

## 2. The build → export → drive loop

```bash
source .venv/bin/activate

# Build the kn5 from a project's already-generated geometry — no Blender:
python -m scripts.ac.kn5_export projects/sand-creek-raceway

# Find the AC install inside your bottle:
python -m scripts.preview.bottle --list

# Install the built track into the bottle and drive it:
python -m scripts.preview.bottle sand-creek-raceway --drive
```

See `scripts/preview/README.md` for the bottle details and the staged validation plan (vanilla AC →
Content Manager → CSP).

---

## 3. The preview bottle (Steam / AC / CM / CSP / mods)

Do this once on the Mac (it's Windows software, so it goes inside the bottle):

1. Install **CrossOver**. Create a **Windows 10** bottle (call it e.g. `AC`).
2. Inside that bottle, install **Steam**, then **Assetto Corsa**.
3. Launch AC once so it creates `Documents/Assetto Corsa/` (the preview writes its quick-race cfg there).
4. *(For full-fidelity preview)* install **Content Manager** and **CSP** into the same bottle.
5. Install **your mods** the normal way — drop them into the bottle's
   `…/steamapps/common/assettocorsa/content/{cars,tracks}/`, or install via Content Manager.

Point the tooling at the bottle (auto-detected for CrossOver/Whisky/`~/.wine`, or set it explicitly):
```bash
export AC_BOTTLE="$HOME/Library/Application Support/CrossOver/Bottles/AC"   # dir containing drive_c
python -m scripts.preview.bottle --list
```

---

## 4. Driving Claude locally (optional)

This cloud session does **not** transfer to your Mac — only the git branch does. To run the agent
natively in your local clone:

1. Install the Claude Code CLI — see https://code.claude.com (e.g. `npm install -g @anthropic-ai/claude-code`).
2. From the repo root, run `claude`. It starts a fresh local session with this codebase.
3. Sign in as the same account (kev@alternate.org) to keep your usage/settings.

Local sessions and cloud (claude.ai/code) sessions are separate histories — the CLI won't show this
web conversation, but it operates on the same code once you've fetched the branch.

---

## 5. Building a brand-new track (full pipeline)

Needs the elevation deps (rasterio/GDAL) from §1. High level — drive it through the skills
(`gps-extraction` → `elevation` → `geometry` → `ac`) or the scripts under `scripts/`, then export and
preview as in §2. Each project is fully described by its `projects/<slug>/track.config.json`.
