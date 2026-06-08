"""Phase S1 — unpack the needed ``.scs`` archives (HashFS v1/v2) into a working asset tree.

Wraps the cross-platform extractor (sk-zk/Extractor); point at the binary with ``SCS_EXTRACTOR_BIN``.
We only unpack the archives a region actually needs — ``base``/``def`` plus the selected DLC — to
keep the tree small. Nothing here is hardcoded: the game root and DLC list come from
``track.config.json`` ``source``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

# Archives every map port needs regardless of region.
CORE_ARCHIVES = ("base.scs", "def.scs")


def archives_for(source: dict[str, Any]) -> list[str]:
    """Resolve the ``.scs`` filenames to unpack from a config ``source`` block.

    Core archives plus one ``dlc_<name>.scs`` per entry in ``source.dlc``. Map/terrain content for
    a DLC region lives in its DLC archive, so the region's DLC list drives what we extract.
    """
    dlc = source.get("dlc", []) or []
    return [*CORE_ARCHIVES, *(f"dlc_{name.removeprefix('dlc_')}.scs" for name in dlc)]


def extract(source: dict[str, Any], dest: Path) -> Path:
    """Unpack the region's archives from ``source.game_root`` into ``dest``; return the asset tree.

    The resulting tree holds ``def/``, ``map/``, ``model/``, ``material/``, ``prefab/`` etc., merged
    across archives (later archives override earlier ones, matching the game's mod load order).
    """
    game_root = Path(source["game_root"]).expanduser()
    if not game_root.is_dir():
        raise FileNotFoundError(f"source.game_root does not exist: {game_root}")
    dest.mkdir(parents=True, exist_ok=True)

    binary = os.environ.get("SCS_EXTRACTOR_BIN")
    if not binary:
        raise RuntimeError("set SCS_EXTRACTOR_BIN to the sk-zk/Extractor binary (see scripts/scs/README.md)")

    for archive in archives_for(source):
        src = game_root / archive
        if not src.exists():
            continue  # DLC the user doesn't own — skip rather than fail the whole region
        cmd = [binary, str(src), "-d", str(dest)]
        # TODO(scs): verify Extractor's CLI flags against the installed release before enabling.
        raise NotImplementedError(f"wire up the extractor subprocess: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)  # noqa: F841  (reachable once the line above is removed)

    return dest


def main() -> None:
    import sys

    from scripts.config import load_config

    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.scs.extract <project-dir>")
    cfg = load_config(sys.argv[1])
    out = extract(cfg.source, Path(sys.argv[1]) / "data" / "extracted")
    print(f"extracted asset tree -> {out}")


if __name__ == "__main__":
    main()
