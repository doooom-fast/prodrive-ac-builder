#!/usr/bin/env bash
# Bootstrap the prodrive-ac-builder pipeline to run natively on a Mac.
#
# Sets up a Python venv with the full pipeline (geometry, elevation, env, kn5 export) so you can
# build a track end to end and preview it in a Wine bottle — no Windows box, and (thanks to the
# bpy-free scripts.ac.kn5_export) no Blender. Idempotent: re-running only fills what's missing.
#
#   ./scripts/bootstrap_mac.sh            # set up .venv, install deps, run the test suite
#   source .venv/bin/activate             # then use the pipeline (see RUNNING-ON-MAC.md)
#
# What it does NOT install (Windows apps / paid / your account): Steam, Assetto Corsa, Content
# Manager, CSP, and your mods all live inside a CrossOver/Wine *bottle* — see RUNNING-ON-MAC.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m !!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m ✗\033[0m %s\n' "$*" >&2; exit 1; }

# --- 0. platform sanity -------------------------------------------------------
[[ "$(uname -s)" == "Darwin" ]] || warn "This script targets macOS; on $(uname -s) it may still work but is untested."

# --- 1. Python 3.11+ ----------------------------------------------------------
PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)'; then
      PY="$cand"; break
    fi
  fi
done
[[ -n "$PY" ]] || die "Need Python >= 3.11. Install it with:  brew install python@3.12"
say "Using $("$PY" --version) at $(command -v "$PY")"

# --- 2. virtual environment ---------------------------------------------------
if [[ ! -d .venv ]]; then
  say "Creating virtualenv at .venv"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
say "Upgrading pip"
python -m pip install --upgrade pip >/dev/null

# --- 3. install the package (full pipeline + dev tools) -----------------------
say "Installing prodrive-ac-builder (editable, with dev extras) — this pulls rasterio/GDAL wheels"
if ! python -m pip install -e ".[dev]"; then
  warn "pip install failed. The usual culprit is rasterio/GDAL."
  warn "On Apple Silicon, modern rasterio wheels are self-contained; if it still fails, try:"
  warn "    brew install gdal && pip install --no-binary rasterio rasterio"
  die  "Dependency install failed — see hints above."
fi

# --- 4. verify the native deps actually import --------------------------------
say "Verifying core imports"
if ! python - <<'PY'
import importlib, sys
mods = ["numpy", "shapely", "pyproj", "scipy", "trimesh", "astral", "requests"]
optional = ["rasterio"]  # elevation only; the build/export/preview loop works without it
missing = [m for m in mods if importlib.util.find_spec(m) is None]
if missing:
    print("missing required:", ", ".join(missing)); sys.exit(1)
for m in optional:
    if importlib.util.find_spec(m) is None:
        print(f"WARN: {m} not importable — elevation sampling disabled (build/export/preview still work).")
print("core imports OK")
PY
then
  warn "rasterio (GDAL) is the likely gap. The build->export->preview loop still works without it;"
  warn "to enable USGS elevation sampling:  brew install gdal && pip install --force-reinstall rasterio"
fi

# --- 5. smoke-test the suite --------------------------------------------------
say "Running the test suite"
python tests/run_tests.py | tail -3

# --- 6. optional tooling presence (advice only, never auto-installed) ---------
command -v claude  >/dev/null 2>&1 || warn "Claude Code CLI not found — to drive the agent locally: see RUNNING-ON-MAC.md (§ Local Claude)."
[[ -d "/Applications/CrossOver.app" ]] || warn "CrossOver not found — needed for the in-AC preview bottle (§ Preview bottle in RUNNING-ON-MAC.md)."

cat >&2 <<'NEXT'

✓ Mac setup complete.

Next:
  source .venv/bin/activate
  python -m scripts.ac.kn5_export projects/sand-creek-raceway   # build the kn5 (no Blender)
  python -m scripts.preview.bottle --list                       # find your AC-in-a-bottle
  python -m scripts.preview.bottle sand-creek-raceway --drive    # install + drive

Full guide (Steam/AC/CSP/mods in the bottle, building a new track, local Claude): RUNNING-ON-MAC.md
NEXT
