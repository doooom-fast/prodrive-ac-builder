"""Phase S3→S4 (geometry) — build the full SCS track mesh by reusing the existing geometry back-half.

Given a parsed region (``data/region.geojson``), this produces exactly the Phase-4 artifacts the
kn5 step (Phase 5) already consumes — ``track.obj`` (GRASS + 1ROAD groups), ``track.mtl``, and
``dummies.json`` — by calling the same primitives the GPS pipeline uses:
``geometry.ribbon`` (road + grass), ``geometry.dummies``, and ``geometry.build_mesh``'s OBJ writer.

Terrain note: SCS has no global heightmap, so for the MVP the ground is a flat plane about the
route's low point with the road lifted onto it (see docs/scs-to-ac-plan.md). Road-attached terrain
skirts are a later refinement.

Run:  python -m scripts.scs.build <project-dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

Vertex = tuple[float, float, float]


def flat_ground(points_xyz: list[Vertex], margin_m: float = 30.0, spacing_m: float = 10.0
                ) -> list[list[Vertex]]:
    """A flat ground grid (Y=0) covering the route's XZ extent + margin, as rows of (x,y,z)."""
    xs = [p[0] for p in points_xyz]
    zs = [p[2] for p in points_xyz]
    x0, x1 = min(xs) - margin_m, max(xs) + margin_m
    z0, z1 = min(zs) - margin_m, max(zs) + margin_m
    nx = max(2, int((x1 - x0) / spacing_m) + 1)
    nz = max(2, int((z1 - z0) / spacing_m) + 1)
    return [[(x0 + (x1 - x0) * i / (nx - 1), 0.0, z0 + (z1 - z0) * j / (nz - 1))
             for i in range(nx)] for j in range(nz)]


def build_track(project_dir: str | Path, *, ground_margin_m: float = 30.0,
                ground_spacing_m: float = 10.0, n_sectors: int = 3) -> dict:
    """Build track.obj (1ROAD + GRASS) + track.mtl + dummies.json from data/centerline.local.json."""
    from scripts.geometry import dummies as dummies_mod  # reused back-half
    from scripts.geometry import ribbon
    from scripts.geometry.build_mesh import ROAD_LIFT_M, write_mtl, write_obj

    project_dir = Path(project_dir)
    data = project_dir / "data"
    local_path = data / "centerline.local.json"
    if not local_path.exists():  # derive it from region.geojson if not built yet
        from scripts.scs.centerline import build_local
        build_local(project_dir, build_obj=False)
    local = json.loads(local_path.read_text(encoding="utf-8"))
    pts = [tuple(p) for p in local["points_xyz_m"]]
    widths = local["widths_m"]

    road = ribbon.road_ribbon(pts, widths)
    road["vertices"] = [(x, y + ROAD_LIFT_M, z) for x, y, z in road["vertices"]]
    grass = ribbon.grass_terrain(flat_ground(pts, ground_margin_m, ground_spacing_m))
    dums = dummies_mod.place_dummies(pts, widths, n_sectors=n_sectors)

    nv, nf = write_obj(data / "track.obj", "track.mtl",
                       [("GRASS", "grass", grass), ("1ROAD_main", "road", road)])
    write_mtl(data / "track.mtl")
    (data / "dummies.json").write_text(json.dumps(dums, indent=1), encoding="utf-8")

    return {"vertices": nv, "triangles": nf, "road_verts": len(road["vertices"]),
            "grass_quads": (len(grass["vertices"])), "dummies": len(dums)}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.scs.build <project-dir>")
    stats = build_track(sys.argv[1])
    print("wrote data/track.obj (+track.mtl), dummies.json")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
