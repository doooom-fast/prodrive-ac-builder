"""Generate the installable AC track folder from the shared kn5 + config.

All layouts share one kn5 model and differ only in AC config. Emits:
  models_<layout>.ini, data/surfaces.ini, ui/<layout>/ui_track.json,
  map.png + data/map.ini, ai/ per layout, outline.png, preview.png.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.config import TrackConfig


def generate(config: TrackConfig, kn5_path: str | Path, out_dir: str | Path) -> Path:
    """Assemble the full installable track folder for every layout in ``config.layouts``."""
    raise NotImplementedError(
        "For each layout: models_<id>.ini -> shared kn5; ui/<id>/ui_track.json; ai/<id>/. "
        "Plus data/surfaces.ini, map.png + data/map.ini, outline.png, preview.png."
    )


def surfaces_ini(config: TrackConfig) -> str:
    """Render data/surfaces.ini for the physical 1ROAD/1KERB surfaces."""
    raise NotImplementedError("Emit [SURFACE_n] blocks keyed to 1ROAD_*/1KERB_* with grip/wav.")
