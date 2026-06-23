"""Street-name signs at the loop's junctions — the orientation aid that makes the track readable
("oh, this is the Quebec turn"). Two products:

  1. a texture ATLAS (one green street-name panel per junction name), rendered from an SVG via the
     macOS qlmanage rasteriser — the font is only a BUILD-TIME tool; nothing but the PNG ships, so
     it stays CC0-clean.
  2. sign GEOMETRY — a post + a double-sided panel at each major corner, the panel UV-mapped to its
     name's cell in the atlas and turned to face the approaching driver.

Emitted as two OBJ groups: ``SIGNS`` (panels, textured from the atlas) and ``SIGNPOST`` (grey posts).
Pure stdlib + qlmanage (same rasteriser scripts/ac/track_folder.py already uses).
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from scripts.geometry.kerbs import _smooth, _turn_rate

Vertex = tuple[float, float, float]

# Street the driver turns onto, in loop order (start on Colorado, clockwise). Tune per route.
STREET_NAMES = ["52ND AVE", "DAHLIA ST", "56TH AVE", "SAND CREEK DR",
                "QUEBEC ST", "45TH AVE", "46TH AVE", "COLORADO BLVD"]

_ATLAS = 1024  # square atlas px — qlmanage pads to square, so author it square to avoid dead margins


def render_atlas(names: list[str], out_png: Path) -> dict[str, tuple[float, float, float, float]]:
    """Render a SQUARE atlas of green street-name panels to ``out_png`` (via qlmanage). Returns
    ``{name: (u0, v0, u1, v1)}`` UV cells (v measured top-down, 0 at the top row)."""
    n = len(names)
    w = h = _ATLAS
    ch = h / n  # row height
    rows = []
    for i, nm in enumerate(names):
        y = i * ch
        fs = min(int(ch * 0.5), int(w * 1.7 / max(len(nm), 1)))  # shrink to fit long names
        rows.append(
            f'<g>'
            f'<rect x="6" y="{y + 6:.1f}" width="{w - 12}" height="{ch - 12:.1f}" rx="14" '
            f'fill="#15642a" stroke="#ffffff" stroke-width="5"/>'
            f'<text x="{w / 2}" y="{y + ch / 2:.1f}" fill="#ffffff" '
            f'font-family="Helvetica,Arial,sans-serif" font-weight="bold" font-size="{fs}" '
            f'text-anchor="middle" dominant-baseline="central" '
            f'letter-spacing="1">{nm}</text></g>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="#0a3318"/>'
           + "".join(rows) + "</svg>")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg)
        tmp = f.name
    try:
        subprocess.run(["qlmanage", "-t", "-s", str(h), "-o", str(out_png.parent), tmp],
                       capture_output=True, timeout=60)
        made = out_png.parent / (Path(tmp).name + ".png")
        if made.exists():
            made.replace(out_png)
    except Exception:
        pass
    cells = {}
    for i, nm in enumerate(names):
        cells[nm] = (0.0, i / n, 1.0, (i + 1) / n)
    return cells


def _corner_indices(loop: list[Vertex], limit: int, thr: float = 0.012, min_run: int = 5) -> list[int]:
    """Centre indices of the ``limit`` most significant corner runs, returned in LOOP ORDER — so
    they line up one-to-one with the ordered street-name list (first turn = first name)."""
    rate = _smooth(_turn_rate(loop))
    n = len(loop)
    runs, i = [], 0
    while i < n:
        if abs(rate[i]) <= thr:
            i += 1
            continue
        j = i
        while j < n and abs(rate[j]) > thr:
            j += 1
        if j - i >= min_run:
            peak = max(abs(rate[k]) for k in range(i, j))
            runs.append(((i + j) // 2, peak))
        i = j
    runs.sort(key=lambda r: -r[1])          # by sharpness
    top = sorted(c for c, _ in runs[:limit])  # keep the sharpest `limit`, back into loop order
    return top


def build_signs(loop: list[Vertex], widths_m: list[float], names: list[str],
                cells: dict[str, tuple[float, float, float, float]], *,
                panel_w: float = 2.6, panel_h: float = 0.55, post_h: float = 2.6,
                panel_top: float = 3.0) -> dict[str, dict]:
    """Place a post + name panel at each major corner, panel facing the approaching driver.
    Returns ``{"SIGNS": panel_mesh(uv->atlas), "SIGNPOST": post_mesh}``."""
    corners = _corner_indices(loop, len(names))
    pv: list[Vertex] = []
    puv: list[tuple[float, float]] = []
    pt: list[tuple[int, int, int]] = []
    sv: list[Vertex] = []
    st: list[tuple[int, int, int]] = []
    n = len(loop)
    for k, ci in enumerate(corners):
        nm = names[k] if k < len(names) else (names[-1] if names else "")  # loop-order = turn order
        u0, v0, u1, v1 = cells.get(nm, (0.0, 0.0, 1.0, 1.0))
        x, y, z = loop[ci]
        a, b = loop[max(0, ci - 1)], loop[min(n - 1, ci + 1)]
        tx, tz = b[0] - a[0], b[2] - a[2]
        tl = math.hypot(tx, tz) or 1e-6
        tx, tz = tx / tl, tz / tl
        nx, nz = -tz, tx                      # left normal -> outside verge offset
        off = widths_m[ci] / 2.0 + 1.5
        bx, bz = x + nx * off, z + nz * off    # post base on the verge

        # post (thin vertical quad facing the driver)
        r = len(sv)
        hw = 0.06
        sv += [(bx - tx * hw, y, bz - tz * hw), (bx + tx * hw, y, bz + tz * hw),
               (bx + tx * hw, y + post_h + panel_h, bz + tz * hw),
               (bx - tx * hw, y + post_h + panel_h, bz - tz * hw)]
        st += [(r, r + 1, r + 2), (r, r + 2, r + 3), (r, r + 2, r + 1), (r, r + 3, r + 2)]

        # panel: centred on the post, spanning panel_w across the road-tangent, facing -travel dir.
        cy = y + panel_top
        lx, lz = tx, tz                        # panel spans along travel tangent (reads across approach)
        p0 = (bx - lx * panel_w / 2, cy - panel_h / 2, bz - lz * panel_w / 2)
        p1 = (bx + lx * panel_w / 2, cy - panel_h / 2, bz + lz * panel_w / 2)
        p2 = (bx + lx * panel_w / 2, cy + panel_h / 2, bz + lz * panel_w / 2)
        p3 = (bx - lx * panel_w / 2, cy + panel_h / 2, bz - lz * panel_w / 2)
        base = len(pv)
        pv += [p0, p1, p2, p3]
        puv += [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]   # bottom-left..top-left, v0=top row
        pt += [(base, base + 1, base + 2), (base, base + 2, base + 3),   # front
               (base, base + 2, base + 1), (base, base + 3, base + 2)]   # back (double-sided)
    return {"SIGNS": {"vertices": pv, "uvs": puv, "tris": pt},
            "SIGNPOST": {"vertices": sv, "tris": st}}
