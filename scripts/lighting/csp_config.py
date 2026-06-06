"""Resolve true-north rotation and emit CSP/Sol lighting config + time-of-day presets.

Writes ``true_north_rotation_deg`` back to track.config.json so in-game shadows match reality.
"""

from __future__ import annotations

from pathlib import Path

from scripts.config import TrackConfig


def resolve_true_north(config: TrackConfig) -> float:
    """Compute the mesh rotation (degrees) that aligns local north with AC's world north."""
    raise NotImplementedError("Derive from projection meridian convergence at the origin; write back.")


def emit_lighting(config: TrackConfig, track_dir: str | Path) -> list[Path]:
    """Emit CSP/Sol/Pure config templates and the configured time-of-day presets."""
    raise NotImplementedError(
        "For each preset in config.lighting['presets'] (morning/noon/golden_hour) emit a CSP config."
    )
