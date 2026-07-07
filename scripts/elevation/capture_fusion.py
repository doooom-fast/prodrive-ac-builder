"""Fuse phone-captured road elevations into the DEM profile (fixes road-vs-ground mismatch).

The DEM samples the *ground* (vegetation, cut/fill shoulders, lidar returns off walls), which is not
always where the *road surface* is — the recurring "road maps to the ground but not where the road
actually exists" problem. A Prodrive Scan drive measures the road itself, so where capture evidence
exists (``source/realworld_capture.json``, written by ``scripts.capture.ingest``) we bend the DEM
profile toward it.

The comparison is deliberately **relative**, not absolute:

  residual(s) = (capture alt − sensor height) − DEM(s)

A robust constant ("datum") is fitted to the residuals and removed before any correction is applied.
That constant absorbs the GPS vertical bias, the geoid/NAVD88 datum gap, *and* any error in the
configured sensor height — so ``sensor_height_m`` (the phone's height above the road: windshield
mount + car) only needs to be roughly right. What's left after the datum fit is the *shape*
disagreement, which is the real signal.

Bad samples are rejected by **continuity segmentation**, not by residual outlier-ness — because a
genuine DEM error and a phone fall both look like a local step *in the residual*, and a residual
gate would throw away exactly the disagreement we're here to harvest. The physical discriminator:
**a road can't step, but a dropped phone can.** A fall (or re-seated mount) makes the capture
altitude itself discontinuous; a DEM error leaves the capture smooth and shifts only the residual.
So:
  1. Split the capture into segments wherever consecutive stations step more than ``max_step_m``
     in measured altitude, or are separated by more than ``gap_split_m`` (continuity can't be
     vouched across a dropout).
  2. Reject segments with fewer than ``min_segment_stations`` (isolated garbage fixes), and
     segments whose median residual deviates from the all-station consensus by more than
     ``segment_offset_m`` (the fall: a locally-consistent-but-shifted run).
A DEM bump never splits a segment (the capture over it is smooth), so it survives to be corrected;
a fall is bounded by impossible altitude steps, lands in its own segment, and is discarded whole.

The correction curve is a kernel-weighted (triangular, ``kernel_m``) average of accepted residual
deviations, weighted by sample support (``n`` / horizontal accuracy), clamped to
``max_correction_m``, feathered to zero over ``feather_m`` beyond the last evidence, and finally
re-smoothed lightly so the fused profile stays launch-free. Uncovered spans keep the pure DEM
profile — no evidence, no change.

Writes ``z_fused_m`` + a ``fusion`` block back into ``data/centerline.elevation.json`` (consumed by
``scripts.geometry.projection``, which prefers ``z_fused_m``) and refreshes the profile SVG.
All knobs read from ``track.config.json`` → ``elevation.capture_fusion`` (defaults below).
Pure stdlib. Runs automatically at the end of ``scripts.elevation.heightfield`` when evidence
exists, or standalone:

Run:  python -m scripts.elevation.capture_fusion projects/<slug>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from scripts.config import load_config
from scripts.elevation.heightfield import smooth_closed, smooth_open, write_profile_svg

DEFAULTS = {
    "enabled": True,
    "sensor_height_m": 1.35,    # phone above road surface (windshield mount in a typical car)
    "max_hacc_m": 10.0,         # drop fixes with worse reported horizontal accuracy
    "min_n": 2,                 # drop stations supported by fewer pooled fixes
    "max_step_m": 0.8,          # capture-altitude step between adjacent stations → segment boundary
    "gap_split_m": 20.0,        # station gap beyond which continuity can't be vouched → boundary
    "min_segment_stations": 3,  # shorter segments are isolated garbage → rejected
    "segment_offset_m": 1.2,    # segment median residual vs consensus beyond this → rejected (fall)
    "kernel_m": 45.0,           # triangular-kernel bandwidth of the correction curve
    "feather_m": 60.0,          # correction tapers to zero this far beyond the last evidence
    "max_correction_m": 6.0,    # sanity clamp — bigger disagreement means something else is wrong
    "final_smooth_m": 15.0,     # light post-smooth so the fused profile stays launch-free
    "min_stations": 8,          # below this, evidence is too thin to trust — skip fusion
}


# --------------------------------------------------------------------------- small robust helpers

def _median(xs: list[float]) -> float:
    s = sorted(xs)
    m = len(s)
    return s[m // 2] if m % 2 else (s[m // 2 - 1] + s[m // 2]) / 2.0


def _ring_dist(a: float, b: float, lap: float, loop: bool) -> float:
    d = abs(a - b)
    return min(d, lap - d) if loop and lap > 0 else d


def _interp_profile(dist: list[float], z: list[float], s: float) -> float:
    """Linear interpolation of the DEM profile at station s (dist is monotonically increasing)."""
    if s <= dist[0]:
        return z[0]
    if s >= dist[-1]:
        return z[-1]
    lo, hi = 0, len(dist) - 1
    while hi - lo > 1:                       # bisect (dist can be thousands of points)
        mid = (lo + hi) // 2
        if dist[mid] <= s:
            lo = mid
        else:
            hi = mid
    span = dist[hi] - dist[lo]
    t = (s - dist[lo]) / span if span > 0 else 0.0
    return z[lo] + t * (z[hi] - z[lo])


# --------------------------------------------------------------------------- rejection gate

def reject_by_continuity(stations: list[dict], *, max_step_m: float, gap_split_m: float,
                         min_segment_stations: int, segment_offset_m: float) -> tuple[list[dict], dict]:
    """Continuity segmentation + consensus rejection. Stations carry ``s``, ``alt`` (measured road
    altitude) and ``r`` (residual vs the DEM profile); must not be empty.

    Roads can't step; dropped phones can. Split at capture-altitude discontinuities (and dropout
    gaps), then discard segments that are too short or whose median residual is offset from the
    all-station consensus — the phone-fall signature. A DEM error keeps the capture smooth, stays
    inside its big segment, and survives. Returns (accepted, reject_counts)."""
    ordered = sorted(stations, key=lambda st: st["s"])
    segments: list[list[dict]] = [[ordered[0]]]
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur["s"] - prev["s"] > gap_split_m
                or abs(cur["alt"] - prev["alt"]) > max_step_m):
            segments.append([])
        segments[-1].append(cur)

    consensus = _median([st["r"] for st in ordered])
    accepted: list[dict] = []
    n_short = n_offset = seg_rejected = 0
    for seg in segments:
        if len(seg) < min_segment_stations:
            n_short += len(seg)
            seg_rejected += 1
        elif abs(_median([st["r"] for st in seg]) - consensus) > segment_offset_m:
            n_offset += len(seg)
            seg_rejected += 1
        else:
            accepted.extend(seg)
    return accepted, {"rejected_short_segment": n_short, "rejected_offset_segment": n_offset,
                      "segments": len(segments), "segments_rejected": seg_rejected}


# --------------------------------------------------------------------------- correction curve

def correction_curve(dist: list[float], accepted: list[dict], lap: float, loop: bool, *,
                     kernel_m: float, feather_m: float, max_correction_m: float,
                     station_bin_m: float = 5.0) -> list[float]:
    """Per-vertex correction: kernel-weighted mean of accepted deviations, clamped + feathered."""
    out = []
    for d in dist:
        wsum = csum = 0.0
        dnear = float("inf")
        for st in accepted:
            dd = _ring_dist(st["s"], d, lap, loop)
            dnear = min(dnear, dd)
            k = 1.0 - dd / kernel_m
            if k > 0.0:
                w = k * st["w"]
                wsum += w
                csum += w * st["c"]
        c = csum / wsum if wsum > 0 else 0.0
        c = max(-max_correction_m, min(max_correction_m, c))
        # full strength while inside the evidence grid, tapering to zero feather_m past the edge
        if dnear > station_bin_m:
            c *= max(0.0, 1.0 - (dnear - station_bin_m) / max(1e-9, feather_m))
        out.append(c)
    return out


# --------------------------------------------------------------------------- orchestration

def build(project_dir: str | Path) -> dict:
    """Refine data/centerline.elevation.json with capture evidence. Returns stats (or a skip)."""
    project_dir = Path(project_dir)
    data = project_dir / "data"
    evidence_path = project_dir / "source" / "realworld_capture.json"
    elev_path = data / "centerline.elevation.json"

    if not evidence_path.exists():
        return {"skipped": "no source/realworld_capture.json — run scripts.capture.ingest first"}
    if not elev_path.exists():
        return {"skipped": "no data/centerline.elevation.json — run scripts.elevation.heightfield first"}

    cfg = load_config(project_dir)
    opts = {**DEFAULTS, **cfg.raw.get("elevation", {}).get("capture_fusion", {})}
    if not opts["enabled"]:
        return {"skipped": "elevation.capture_fusion.enabled is false"}
    loop = bool(cfg.raw.get("loop", True))

    doc = json.loads(evidence_path.read_text(encoding="utf-8"))
    elev = json.loads(elev_path.read_text(encoding="utf-8"))
    dist, z_smooth = elev["distance_m"], elev["z_smooth_m"]
    lap = dist[-1]
    origin_elev = doc.get("origin", {}).get("elev_m")
    if origin_elev is None:
        return {"skipped": "evidence has no origin.elev_m (re-run scripts.capture.ingest)"}

    # --- evidence stations → residuals vs the DEM profile (sensor height off, then datum fit) ---
    stations = []
    for st in doc.get("stations", []):
        if st.get("alt_m") is None or st.get("n", 0) < opts["min_n"]:
            continue
        hacc = st.get("gps_hacc_m")
        if hacc is not None and hacc > opts["max_hacc_m"]:
            continue
        capture_abs = st["alt_m"] + origin_elev - opts["sensor_height_m"]
        s = st["station_m"]
        stations.append({
            "s": s,
            "alt": capture_abs,
            "r": capture_abs - _interp_profile(dist, z_smooth, s),
            "w": st["n"] / (1.0 + (hacc if hacc is not None else opts["max_hacc_m"])),
        })
    if len(stations) < opts["min_stations"]:
        return {"skipped": f"only {len(stations)} usable evidence stations "
                           f"(< min_stations={opts['min_stations']})"}

    accepted, rejects = reject_by_continuity(
        stations, max_step_m=opts["max_step_m"], gap_split_m=opts["gap_split_m"],
        min_segment_stations=opts["min_segment_stations"],
        segment_offset_m=opts["segment_offset_m"])
    if len(accepted) < opts["min_stations"]:
        return {"skipped": f"only {len(accepted)} stations survived rejection ({rejects})"}

    datum = _median([st["r"] for st in accepted])   # absorbs GPS bias + geoid gap + sensor-height error
    for st in accepted:
        st["c"] = st["r"] - datum

    corr = correction_curve(dist, accepted, lap, loop, kernel_m=opts["kernel_m"],
                            feather_m=opts["feather_m"], max_correction_m=opts["max_correction_m"])
    spacing = elev.get("spacing_m", 3.0)
    sw = max(3, round(opts["final_smooth_m"] / spacing)) | 1
    z_fused = [zs + c for zs, c in zip(z_smooth, corr)]
    z_fused = (smooth_closed if loop else smooth_open)(z_fused, sw)

    covered = sum(1 for c in corr if abs(c) > 1e-9)
    stats = {
        "stations_used": len(accepted),
        **rejects,
        "datum_offset_m": round(datum, 2),
        "sensor_height_m": opts["sensor_height_m"],
        "max_abs_correction_m": round(max(abs(c) for c in corr), 2),
        "corrected_vertices_pct": round(100.0 * covered / max(1, len(corr)), 1),
    }
    elev["z_fused_m"] = [round(v, 2) for v in z_fused]
    elev["fusion"] = stats
    elev_path.write_text(json.dumps(elev), encoding="utf-8")

    write_profile_svg(dist, elev["z_raw_m"], z_smooth, data / "elevation_profile.svg",
                      z_fused=elev["z_fused_m"])
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.elevation.capture_fusion <project-dir>")
    stats = build(sys.argv[1])
    if stats.get("skipped"):
        print(f"skipped: {stats['skipped']}")
        return
    print("fused capture elevations into data/centerline.elevation.json (z_fused_m)")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
