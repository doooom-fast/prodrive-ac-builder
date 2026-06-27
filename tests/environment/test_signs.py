"""Street-name blade signs (scripts/environment/signs): placement from OSM segments + panel geometry.

Plain ``test_*`` functions (no pytest fixtures) for tests/run_tests.py under the dependency-free
system python. Covers the re-enabled signs: the segment->placement filter (which fixed the stale
corner heuristic) and the panel UV/geometry layout (which fixed the flipped UVs).
"""

from __future__ import annotations

from scripts.environment import signs


def test_placements_skip_short_legs_and_repeats():
    segs = [
        {"name": "A AVE", "length_m": 300.0, "start_idx": 0},
        {"name": "B ST",  "length_m": 50.0,  "start_idx": 100},   # too short -> skip
        {"name": "C BLVD", "length_m": 300.0, "start_idx": 150},
        {"name": "C BLVD", "length_m": 300.0, "start_idx": 300},  # repeats previous -> skip
        {"name": "D DR",  "length_m": 300.0, "start_idx": 450},
    ]
    pl = signs.placements_from_segments(segs, min_leg_m=200.0)
    assert [nm for _i, nm in pl] == ["A AVE", "C BLVD", "D DR"]
    assert [i for i, _nm in pl] == [0, 150, 450]                  # sign sits at the leg ENTRY corner


def _straight_loop(n=20):
    return [(float(i), 0.0, 0.0) for i in range(n)], [8.0] * n     # along +X, 8 m wide


def test_panel_uv_orientation_and_geometry():
    loop, widths = _straight_loop()
    cells = {"A": (0.1, 0.2, 0.9, 0.8)}                            # (u0, v0=top, u1, v1=bottom)
    sg = signs.build_signs(loop, widths, [(10, "A")], cells)
    panel, post = sg["SIGNS"], sg["SIGNPOST"]
    assert len(panel["vertices"]) == 4 and len(panel["uvs"]) == 4 and len(panel["tris"]) == 4
    assert len(post["vertices"]) == 8                             # crossed double-sided post
    for m in (panel, post):                                       # all indices reference real verts
        n = len(m["vertices"])
        assert all(0 <= a < n and 0 <= b < n and 0 <= c < n for a, b, c in m["tris"])
    ys = [v[1] for v in panel["vertices"]]
    for v, (u, vv) in zip(panel["vertices"], panel["uvs"]):
        if v[1] == max(ys):                                       # panel TOP -> cell top (v0)
            assert abs(vv - 0.2) < 1e-9
        if v[1] == min(ys):                                       # panel BOTTOM -> cell bottom (v1)
            assert abs(vv - 0.8) < 1e-9
    us = [u for u, _v in panel["uvs"]]
    assert abs(min(us) - 0.1) < 1e-9 and abs(max(us) - 0.9) < 1e-9  # u spans the full cell


def test_flip_flags_mirror_axes():
    loop, widths = _straight_loop()
    cells = {"A": (0.1, 0.2, 0.9, 0.8)}
    base = signs.build_signs(loop, widths, [(10, "A")], cells)["SIGNS"]
    upf = signs.build_signs(loop, widths, [(10, "A")], cells, flip_up=True)["SIGNS"]
    # flip_up swaps which v a given vertex gets -> top vertex now carries v1 instead of v0
    yb = max(range(4), key=lambda i: base["vertices"][i][1])
    assert abs(base["uvs"][yb][1] - 0.2) < 1e-9
    yu = max(range(4), key=lambda i: upf["vertices"][i][1])
    assert abs(upf["uvs"][yu][1] - 0.8) < 1e-9
    # flip_read reverses the reading direction: at a fixed panel position the u flips (u0 <-> u1)
    rdf = signs.build_signs(loop, widths, [(10, "A")], cells, flip_read=True)["SIGNS"]

    def u_at_far_side(mesh):                                     # u of the vertex at the +reading end
        i = max(range(4), key=lambda i: mesh["vertices"][i][2])
        return mesh["uvs"][i][0]

    assert abs(u_at_far_side(base) - u_at_far_side(rdf)) > 1e-6
