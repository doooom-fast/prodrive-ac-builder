"""Regression tests for the network CUT CARVE + VERGE GAP (the "grass sheeted over sunken decks"
defect, k10-san-diego freeway v0.16.x): terrain must never cross above a deck — not at the
vertices (audit B) and not on the triangle FACES between them (the chords the vertex gates missed),
and the physical grass shoulder must never hang over pavement or in mid-air over a carved cut."""

from scripts.geometry.build_network_mesh import (
    _carve_cut_corridor, _densify, _filter_verge_over_roads, _road_tri_hash,
)

SPACING = 27.5
CLEAR = 0.30


def _cut_setup(nat_y=15.0, deck_y=0.0, width=10.0):
    """A straight road along Z at x=0, deck at deck_y, natural terrain a flat sheet at nat_y (a cut),
    grid at SPACING. Returns (grid_xyz, edge_local)."""
    pts = [(0.0, deck_y, float(z)) for z in range(-200, 201, 4)]
    edge_local = [({"road_class": "motorway", "id": 1}, pts, width)]
    grid = []
    z0 = -220.0
    x0 = -220.0
    n = int(440 / SPACING) + 1
    for j in range(n):
        row = []
        for i in range(n):
            row.append((x0 + i * SPACING, nat_y, z0 + j * SPACING))
        grid.append(row)
    return grid, edge_local


def test_carve_pins_cut_bench_below_deck():
    grid, el = _cut_setup()
    _carve_cut_corridor(grid, el, clear=CLEAR, grid_spacing=SPACING)
    half = 5.0
    bench = 0.72 * SPACING + 4.0
    for row in grid:
        for x, y, z in row:
            if abs(z) > 150:
                continue                       # away from the edge ends
            d_past = abs(x) - half
            if d_past <= bench:
                assert y <= -CLEAR + 1e-6, f"bench node at x={x} still at {y}"
            else:
                # cone: allowed to recover at the slope, but never above natural
                assert y <= 15.0 + 1e-6


def test_carve_is_one_sided_never_fills():
    grid, el = _cut_setup(nat_y=-8.0)          # terrain already BELOW the deck (an underpass dip)
    before = [[v[1] for v in row] for row in grid]
    _carve_cut_corridor(grid, el, clear=CLEAR, grid_spacing=SPACING)
    after = [[v[1] for v in row] for row in grid]
    assert after == before, "carve raised terrain — underpasses must never be filled"


def test_carve_faces_never_cross_deck():
    """The defect B provably missed: legal VERTICES with the triangle between them chording over the
    cut. Sample the bilinear surface over the pavement — it must stay under the deck everywhere."""
    grid, el = _cut_setup(nat_y=20.0)
    _carve_cut_corridor(grid, el, clear=CLEAR, grid_spacing=SPACING)
    # bilinear sample of the grid over the footprint (same split-agnostic bound the carve guarantees)
    x0 = grid[0][0][0]; z0 = grid[0][0][2]
    n = len(grid)

    def surf(x, z):
        fi = (x - x0) / SPACING; fj = (z - z0) / SPACING
        i0 = int(fi); j0 = int(fj)
        ti = fi - i0; tj = fj - j0
        a = grid[j0][i0][1] * (1 - ti) + grid[j0][i0 + 1][1] * ti
        b = grid[j0 + 1][i0][1] * (1 - ti) + grid[j0 + 1][i0 + 1][1] * ti
        return a * (1 - tj) + b * tj
    bad = []
    for zi in range(-140, 141, 3):
        for xo in (-5.0, -2.5, 0.0, 2.5, 5.0):   # across the 10 m footprint
            s = surf(xo, float(zi))
            if s > 0.0:                          # deck_y = 0
                bad.append((xo, zi, s))
    assert not bad, f"terrain face crosses above the deck: {bad[:5]}"


def test_densify_fills_sparse_osm_spacing():
    pts = [(0.0, 0.0, 0.0), (0.0, 0.0, 50.0), (0.0, 0.0, 54.0)]
    out = list(_densify(pts, 6.0))
    assert len(out) > len(pts)
    for k in range(1, len(out)):
        d = ((out[k][0] - out[k - 1][0]) ** 2 + (out[k][2] - out[k - 1][2]) ** 2) ** 0.5
        assert d <= 6.0 + 1e-9


def _flat_road_mesh(y=10.0, half=6.0, z0=-20.0, z1=20.0):
    v = [(-half, y, z0), (half, y, z0), (half, y, z1), (-half, y, z1)]
    return [("e1", {"vertices": v, "uvs": [(0, 0)] * 4, "tris": [(0, 1, 2), (0, 2, 3)]})]


def test_verge_gap_drops_grass_over_pavement_keeps_under():
    road_th = _road_tri_hash(_flat_road_mesh(y=10.0))
    over = [(-2.0, 12.0, 0.0), (2.0, 12.0, 0.0), (0.0, 12.0, 4.0)]      # 2 m above the deck
    under = [(-2.0, 4.0, 0.0), (2.0, 4.0, 0.0), (0.0, 4.0, 4.0)]        # under the flyover
    beside = [(30.0, 10.0, 0.0), (34.0, 10.0, 0.0), (32.0, 10.0, 4.0)]  # off the pavement
    m = {"vertices": over + under + beside, "uvs": [(0, 0)] * 9,
         "tris": [(0, 1, 2), (3, 4, 5), (6, 7, 8)]}
    out = _filter_verge_over_roads([("v9", m)], road_th)
    assert len(out) == 1
    kept = out[0][1]
    assert len(kept["tris"]) == 2, "exactly the over-pavement triangle must be dropped"
    ys = sorted({round(v[1], 1) for v in kept["vertices"]})
    assert ys == [4.0, 10.0], f"orphan verts not pruned / wrong tri dropped: {ys}"


def test_verge_gap_drops_hanging_shoulder():
    road_th = _road_tri_hash(_flat_road_mesh(y=10.0))
    hang = [(40.0, 10.0, 0.0), (44.0, 10.0, 0.0), (42.0, 10.0, 4.0)]    # 10 m over the ground
    seated = [(60.0, 0.2, 0.0), (64.0, 0.2, 0.0), (62.0, 0.2, 4.0)]     # on the ground
    m = {"vertices": hang + seated, "uvs": [(0, 0)] * 6, "tris": [(0, 1, 2), (3, 4, 5)]}
    out = _filter_verge_over_roads([("v9", m)], road_th, ground_at=lambda x, z: 0.0)
    kept = out[0][1]
    assert len(kept["tris"]) == 1
    assert all(abs(v[1] - 0.2) < 1e-6 for v in kept["vertices"]), \
        "the hanging shoulder (a bridge edge) must be dropped, the seated one kept"
