#!/usr/bin/env bash
# End-to-end Mac build for a Blender-FIRST loop track — the alternate front-end ported from
# k10-san-diego. The project's loop.blend is the source of truth (shaped by hand in Blender);
# this wrapper preps it to AC convention, exports the kn5, gates it, and packs the track folder.
#
#   ./scripts/build_loop.sh <project-dir>            # full run (blend -> pack)
#   ./scripts/build_loop.sh <project-dir> verify     # resume from the verify stage
#   ./scripts/build_loop.sh <project-dir> --list     # list stages and exit
#
# Stages: blend (prep loop.blend -> AC-ready .blend, Blender 4.2) -> kn5 (vendored-addon export)
#         -> verify (drivability gate) -> fidelity (kn5_ground_check; runs KN5-INTERNAL — a
#         Blender-first project has no generated OBJs, so the OBJ-fidelity half auto-skips and the
#         physical kn5 checks still gate) -> pack (track folder + installable zip).
#
# NOTE: this is the LOOP pipeline (scripts/ac/build_kn5_loop.py — preps an EXISTING .blend). The
# generated-OBJ circuits ship via scripts/build.sh and networks via scripts/build_network.sh; the
# two build_kn5 programs are deliberately separate and must never be merged.
set -euo pipefail

PROJ="${1:?usage: build_loop.sh <project-dir> [from-stage|--list]}"
FROM="${2:-blend}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
STAGES=(blend kn5 verify fidelity pack)

# Pre-flight: AC/CSP can hard-CRASH THE GPU on load when a kn5 carries a non-power-of-two texture
# (mipmap/DXT upload hangs the driver). Fail loudly before building. (Same gate as build.sh.)
"$PY" - <<'POT' || exit 1
import sys
from pathlib import Path
try:
    from PIL import Image
except Exception:
    print("  [pot-check skipped: Pillow not available]"); sys.exit(0)
pot = lambda n: (n & (n - 1)) == 0
bad = []
for f in Path("assets/textures").glob("*"):
    if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
        w, h = Image.open(f).size
        if not (pot(w) and pot(h)):
            bad.append(f"{f.name} {w}x{h}")
if bad:
    print("NON-PoT textures (resize to power-of-two or AC hard-crashes on load):")
    for b in bad: print("   ", b)
    sys.exit(1)
print("  pot-check: all textures power-of-two")
POT

if [[ "$FROM" == "--list" ]]; then printf '%s\n' "${STAGES[@]}"; exit 0; fi
START=-1; for i in "${!STAGES[@]}"; do [[ "${STAGES[$i]}" == "$FROM" ]] && START=$i; done
[[ $START -lt 0 ]] && { echo "unknown stage '$FROM' (one of: ${STAGES[*]})" >&2; exit 1; }

run() { echo; echo "━━━━ [$1] ${*:2}"; "${@:2}"; }
active() { local s; for s in "${STAGES[@]:$START}"; do [[ "$s" == "$1" ]] && return 0; done; return 1; }

SLUG="$($PY -c "import json,sys;print(json.load(open('$PROJ/track.config.json'))['slug'])")"
VER="$($PY -c "import json,sys;print(json.load(open('$PROJ/track.config.json'))['version'])")"

if active blend || active kn5; then
  BLENDER="${BLENDER:-$("$ROOT/scripts/bootstrap_blender.sh")}"   # pin/download Blender 4.2 if needed
  active blend && run blend "$BLENDER" --background --python scripts/ac/build_kn5_loop.py   -- "$PROJ"
  active kn5   && run kn5   "$BLENDER" --background --python scripts/ac/export_kn5_addon.py -- "$PROJ"
fi
# Gate: the exported kn5 must be drivable (no dup meshes, drivable surfaces face-up, spawns on the
# road, no terrain poking through the deck) — aborts BEFORE packaging.
active verify   && run verify   "$PY" -m scripts.ac.verify_kn5 "$PROJ"
# Gate: physical coherence of the SHIPPED binary (double-sheet terrain, prop/wall base seating,
# lamp integrity, road-over-ground). Runs kn5-internal on loop projects (no source OBJs).
active fidelity && run fidelity "$PY" -m scripts.ac.kn5_ground_check "$PROJ"

if active pack; then
  run pack "$PY" -m scripts.ac.track_folder "$PROJ"
  cp -f "$PROJ/build/$SLUG.kn5" "$PROJ/build/$SLUG/$SLUG.kn5"
  run pack "$PY" - "$PROJ" "$SLUG" "$VER" <<'PY'
import sys, zipfile
from pathlib import Path
proj, slug, ver = sys.argv[1], sys.argv[2], sys.argv[3]
root = Path(proj) / "build"; folder = root / slug
zp = root / f"{slug}_v{ver}.zip"
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, 6) as z:
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.suffix != ".svg":
            z.write(f, f.relative_to(root))
print(f"  -> {zp}  ({zp.stat().st_size/1e6:.1f} MB)")
PY
  echo "  installable: $PROJ/build/${SLUG}_v${VER}.zip  (+ folder $PROJ/build/$SLUG/)"
fi
echo; echo "✓ loop build complete: $PROJ ($SLUG v$VER)"
