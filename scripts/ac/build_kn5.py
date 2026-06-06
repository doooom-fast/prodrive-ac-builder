"""Headless Blender entry point — build the mesh and export the kn5.

Run from Blender (bpy is provided by the Blender runtime, not pip):

    blender --background --python scripts/ac/build_kn5.py -- <track-dir>

Reads <track-dir>/track.config.json + data/, builds the scene (1ROAD ribbon, GRASS heightfield,
dummies), assigns materials via the AC Blender Tools addon, and exports build/<slug>.kn5.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _track_dir_from_argv(argv: list[str]) -> Path:
    """Blender passes script args after a literal ``--``."""
    if "--" not in argv:
        raise SystemExit("usage: blender --background --python build_kn5.py -- <track-dir>")
    rest = argv[argv.index("--") + 1:]
    if not rest:
        raise SystemExit("missing <track-dir> after '--'")
    return Path(rest[0])


def build(track_dir: Path) -> Path:
    """Build the Blender scene from the project data and export the kn5. Returns the kn5 path."""
    import bpy  # noqa: F401  — only available inside Blender

    raise NotImplementedError(
        "Reset scene; import centerline/heightfield; build 1ROAD ribbon + GRASS + dummies; "
        "apply materials.py assignments; invoke AC Blender Tools kn5 export to build/<slug>.kn5."
    )


def main() -> None:
    track_dir = _track_dir_from_argv(sys.argv)
    out = build(track_dir)
    print(f"[build_kn5] exported {out}")


if __name__ == "__main__":
    main()
