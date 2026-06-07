"""Phase S4 — convert referenced SCS models (.pmg/.ppd) to glTF, deduped and budget-capped.

Wraps ConverterPIX (``CONVERTERPIX_BIN``). A region references the same model many times (one tree
model, hundreds of placements), so we dedup by model path before converting and let the geometry
pass instance them. kn5 has no real instancing, so a region can blow up the file — ``budget`` caps
the number of unique converted models and we ``log`` what was dropped rather than silently truncating.

Only runs when ``source.asset_mode == "extract"``; ``"substitute"`` skips this entirely and the
track ships with the road network plus the user's own / CC0 / Kunos-stock props.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def dedup(model_paths: list[str]) -> list[str]:
    """Stable-dedup model references by path (case-insensitive, SCS paths are case-folding)."""
    seen: set[str] = set()
    unique: list[str] = []
    for p in model_paths:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def convert_models(
    model_paths: list[str],
    asset_tree: Path,
    dest: Path,
    *,
    budget: int | None = None,
) -> dict[str, Path]:
    """Convert unique models to glTF under ``dest``; return ``{scs_model_path: gltf_path}``."""
    unique = dedup(model_paths)
    if budget is not None and len(unique) > budget:
        dropped = len(unique) - budget
        print(f"[scs] model budget {budget} exceeded — converting {budget}, dropping {dropped}")
        unique = unique[:budget]
    dest.mkdir(parents=True, exist_ok=True)

    binary = os.environ.get("CONVERTERPIX_BIN")
    if not binary:
        raise RuntimeError("set CONVERTERPIX_BIN to the ConverterPIX binary (see scripts/scs/README.md)")

    out: dict[str, Path] = {}
    for model in unique:
        gltf = dest / (Path(model).stem + ".gltf")
        cmd = [binary, "-b", str(asset_tree), "-m", model, "-e", str(gltf)]
        # TODO(scs): ConverterPIX emits its middle format / OBJ; confirm the flag set and the
        # glTF path (may need the Blender 3.6 ConverterPIXWrapper step instead of a direct CLI export).
        raise NotImplementedError(f"wire up ConverterPIX: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)  # noqa: F841
        out[model] = gltf
    return out
