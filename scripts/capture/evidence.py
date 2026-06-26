"""Apply real-world Prodrive Scan evidence to the built geometry.

The bare-earth USGS heightfield is accurate on open ground but wrong where the *road deck* differs from
the ground it sampled — bridges/overpasses, embankments, cuts. The capture measured the actual road
surface the car drove, so where it CONFIDENTLY diverges from the heightfield we trust the capture; where
they agree (the common case) we keep the cleaner, denser heightfield. The result: real elevation at the
spots the heightfield can't know about, without injecting GPS noise into the 80%+ that's already right.

Consumed by build_mesh (the driven kn5 road) and build_env (so terrain conforms to the corrected road),
both guarded: no ``source/realworld_capture.json`` → the input is returned unchanged (reproducibility).
Pure stdlib. See [[companion-app-plan]].
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

CAPTURE_NAME = "realworld_capture.json"

Vertex = tuple[float, float, float]


def load_capture(project_dir: str | Path) -> dict[str, Any] | None:
    """Return the committed capture evidence if it exists and carries stations, else None."""
    p = Path(project_dir) / "source" / CAPTURE_NAME
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    return doc if doc.get("stations") else None


def corrected_elevation(
    points_xyz: list[Vertex],
    capture: dict[str, Any],
    *,
    min_n: int = 8,            # only trust stations driven on enough passes (rejects 1-pass GPS spikes)
    blend_lo: float = 1.0,     # |diff| below this → keep heightfield (within its accuracy + GPS noise)
    blend_hi: float = 3.0,     # |diff| above this → fully trust the captured road surface
    max_correction_m: float = 12.0,
    max_gap_m: float = 30.0,   # don't interpolate captured elevation across an uncovered stretch
    smooth_passes: int = 12,
) -> tuple[list[Vertex], dict[str, Any]]:
    """Centerline with road-surface elevation corrected from the capture (Y only; X/Z untouched).

    Confidence blend on |captured − heightfield| (after removing a constant car-height/GPS offset):
    keep heightfield where they agree, apply the capture where they diverge, linear between. The
    correction is capped, smoothed, and — because it's 0 outside coverage — ramps cleanly to nothing at
    the edges of the driven sections. Returns (new_points, stats).
    """
    pts = [tuple(p) for p in points_xyz]
    n = len(pts)
    none_stats = {"n_corrected": 0, "max_corr_m": 0.0, "coverage_pts": 0, "offset_m": 0.0}
    if n < 2:
        return pts, none_stats

    ev = sorted((s["station_m"], s["alt_m"]) for s in capture["stations"]
                if s.get("alt_m") is not None and s.get("n", 0) >= min_n)
    if len(ev) < 2:
        return pts, none_stats
    ev_st = [e[0] for e in ev]
    ev_al = [e[1] for e in ev]

    # arc length along the centerline (the same station convention the capture is keyed on)
    S = [0.0]
    for i in range(1, n):
        S.append(S[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][2] - pts[i - 1][2]))

    def cap_alt_at(st: float) -> float | None:
        if st < ev_st[0] or st > ev_st[-1]:
            return None
        lo, hi = 0, len(ev_st) - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            if ev_st[m] <= st:
                lo = m
            else:
                hi = m
        if ev_st[hi] - ev_st[lo] > max_gap_m:   # bracketing stations too far apart → uncovered gap
            return None
        t = (st - ev_st[lo]) / max(1e-9, ev_st[hi] - ev_st[lo])
        return ev_al[lo] + t * (ev_al[hi] - ev_al[lo])

    cap_y = [cap_alt_at(S[i]) for i in range(n)]
    hf_y = [pts[i][1] for i in range(n)]
    deltas = sorted(cap_y[i] - hf_y[i] for i in range(n) if cap_y[i] is not None)
    if not deltas:
        return pts, none_stats
    offset = deltas[len(deltas) // 2]   # median car-height/GPS-bias offset → keep heightfield baseline

    corr = [0.0] * n
    for i in range(n):
        if cap_y[i] is None:
            continue
        d = (cap_y[i] - offset) - hf_y[i]
        ad = abs(d)
        w = 0.0 if ad <= blend_lo else 1.0 if ad >= blend_hi else (ad - blend_lo) / (blend_hi - blend_lo)
        corr[i] = max(-max_correction_m, min(max_correction_m, w * d))

    for _ in range(smooth_passes):     # smooth + auto-ramp to 0 at the coverage edges
        nc = corr[:]
        for i in range(1, n - 1):
            nc[i] = 0.25 * corr[i - 1] + 0.5 * corr[i] + 0.25 * corr[i + 1]
        corr = nc

    new_pts = [(pts[i][0], pts[i][1] + corr[i], pts[i][2]) for i in range(n)]
    stats = {
        "n_corrected": sum(1 for c in corr if abs(c) > 0.05),
        "max_corr_m": round(max((abs(c) for c in corr), default=0.0), 2),
        "coverage_pts": len(deltas),
        "offset_m": round(offset, 2),
    }
    return new_pts, stats
