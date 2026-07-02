"""Build the real-world seed for *1978*: road network + spine + elevation + landmarks, ENU meters.

Sources (per ``track.config.json``):
- The owner's Google My Maps KML exports, merged into one deduped road network
  (``scripts/gps/network.py``) — extensive but imperfect; smoothing knobs live in ``network.*``.
- An OSM augment (``network.osm_augment``) guaranteeing the streets the game must have even if
  the KML never traced them: the residential grid around home, plus named roads.
- OSM landmark areas (sanctum golf course, Lake Murray, school) + the home point.

Every edge gets an OSM road class/name/width (``classify``) and real USGS 3DEP elevation
(``network_elev``). The home->school *spine* is Dijkstra'd over the built network. Everything is
projected into one ENU frame (X=east, Y=up, Z=north) and written to ``data/seed.local.json``.

Run:  python -m scripts.game.build_seed projects/gala-seed
Then: python -m scripts.game.export_seed projects/gala-seed <game-repo>/seed
"""

from __future__ import annotations

import heapq
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from scripts.config import load_config
from scripts.elevation import network_elev
from scripts.geometry.projection import centroid, project_to_local
from scripts.gps.classify import classify
from scripts.gps.network import build_network
from scripts.trace.osm import OVERPASS_URL, USER_AGENT

Vertex = tuple[float, float]


def _fetch_osm_elements(ids: list[str]) -> dict[str, list[Vertex]]:
    """Fetch OSM ways/relations by id ('way/123') -> closed outline (lon, lat) vertices."""
    parts = []
    for ref in ids:
        kind, num = ref.split("/")
        parts.append(f"{kind}({num});")
    query = f"[out:json][timeout:60];({''.join(parts)});out geom;"
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(4):  # Overpass 504s routinely under load
        req = urllib.request.Request(OVERPASS_URL, data=body,
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(4 * (attempt + 1))
    out: dict[str, list[Vertex]] = {}
    for el in payload.get("elements", []):
        ref = f"{el['type']}/{el['id']}"
        if el["type"] == "way":
            out[ref] = [(g["lon"], g["lat"]) for g in el.get("geometry") or []]
        elif el["type"] == "relation":  # outer ring(s) concatenated
            ring: list[Vertex] = []
            for m in el.get("members", []):
                if m.get("role") == "outer":
                    ring += [(g["lon"], g["lat"]) for g in m.get("geometry") or []]
            out[ref] = ring
    return out


def _hav(a: Vertex, b: Vertex) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = math.radians(b[1] - a[1]), math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _spine(features: list[dict], src: Vertex, dst: Vertex, *,
           ref: Vertex, snap_m: float) -> list[tuple[int, bool]]:
    """Dijkstra over the network's edge graph -> ordered list of edge traversals.

    Edge endpoints drift a few meters through per-edge smoothing/resampling, so exact-coordinate
    keying fragments the graph — cluster endpoints with the same ``_NodeGrid`` snap the network
    build itself used. Returns [(edge_id, forward)] from nearest-``src`` to nearest-``dst`` node.
    """
    from scripts.gps.network import _NodeGrid, _projector
    to_m, _to_ll = _projector(ref[1], ref[0])
    grid = _NodeGrid(snap_m)

    def key(p) -> int:
        return grid.assign(*to_m(p[0], p[1]))

    node_ll: dict[int, Vertex] = {}
    adj: dict[int, list[tuple[int, int, bool, float]]] = defaultdict(list)
    for f in features:
        cs = f["geometry"]["coordinates"]
        a, b = key(cs[0]), key(cs[-1])
        node_ll.setdefault(a, tuple(cs[0]))
        node_ll.setdefault(b, tuple(cs[-1]))
        eid = f["properties"]["id"]
        L = f["properties"]["length_m"]
        adj[a].append((b, eid, True, L))
        adj[b].append((a, eid, False, L))

    nodes = list(adj)
    s = min(nodes, key=lambda n: _hav(node_ll[n], src))
    t = min(nodes, key=lambda n: _hav(node_ll[n], dst))
    dist = {s: 0.0}
    prev: dict[Vertex, tuple[Vertex, int, bool]] = {}
    pq = [(0.0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == t:
            break
        if d > dist.get(u, 9e18):
            continue
        for v, eid, fwd, w in adj[u]:
            nd = d + w
            if nd < dist.get(v, 9e18):
                dist[v] = nd
                prev[v] = (u, eid, fwd)
                heapq.heappush(pq, (nd, v))
    if t not in dist:
        raise SystemExit("[seed] spine: home and school are not connected in the network")
    hops = []
    cur = t
    while cur != s:
        u, eid, fwd = prev[cur]
        hops.append((eid, fwd))
        cur = u
    hops.reverse()
    return hops


def _landmarks_from_config(cfg, cached: dict[str, list[Vertex]]) -> dict[str, dict]:
    """Config landmarks -> {name: {label, kind, outline_lonlat|point_lonlat}}.

    OSM-id outlines come from ``cached`` (existing landmarks.geojson) when available, so point-only
    edits (a new family pin) don't need Overpass at all.
    """
    lm_cfg = cfg.raw["landmarks"]
    need = [v["osm"] for k, v in lm_cfg.items()
            if isinstance(v, dict) and "osm" in v and k not in cached]
    fetched = _fetch_osm_elements(need) if need else {}
    landmarks: dict[str, dict] = {}
    for name, spec in lm_cfg.items():
        if not isinstance(spec, dict) or ("osm" not in spec and "point" not in spec):
            continue
        if "osm" in spec:
            verts = cached.get(name) or fetched.get(spec["osm"], [])
            if not verts:
                raise SystemExit(f"[seed] landmark '{name}': no geometry for {spec['osm']}")
            landmarks[name] = {"label": spec.get("label", name), "osm": spec["osm"],
                               "kind": "region", "outline_lonlat": verts}
        else:
            landmarks[name] = {"label": spec.get("label", name), "kind": "point",
                               "point_lonlat": list(spec["point"])}
    return landmarks


def _write_landmarks_geojson(data: Path, landmarks: dict[str, dict]) -> None:
    (data / "landmarks.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"name": n, "label": lm["label"], "kind": lm["kind"]},
             "geometry": ({"type": "Polygon", "coordinates": [[[lo, la] for lo, la in lm["outline_lonlat"]]]}
                          if lm["kind"] == "region" else
                          {"type": "Point", "coordinates": lm["point_lonlat"]})}
            for n, lm in landmarks.items()],
    }), encoding="utf-8")


def _project_landmarks(landmarks: dict[str, dict], origin: Vertex, elev0: float) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, lm in landmarks.items():
        pts = lm.get("outline_lonlat") or [tuple(lm["point_lonlat"])]
        # Landmarks are 2D regions/points; Y comes from the heightfield in-engine (drape on import).
        loc = project_to_local(pts, [elev0] * len(pts), origin, elev0)
        out[name] = {"label": lm["label"], "kind": lm["kind"],
                     "points_xz_m": [[round(x, 2), round(z, 2)] for x, _y, z in loc]}
    return out


def _cached_outlines(data: Path) -> dict[str, list[Vertex]]:
    lmp = data / "landmarks.geojson"
    if not lmp.exists():
        return {}
    gj = json.loads(lmp.read_text(encoding="utf-8"))
    return {f["properties"]["name"]: [tuple(c) for c in f["geometry"]["coordinates"][0]]
            for f in gj["features"] if f["geometry"]["type"] == "Polygon"}


def refresh_landmarks(project_dir: str | Path) -> None:
    """Re-derive landmarks from config without touching roads/elevation (new family pins)."""
    project_dir = Path(project_dir)
    data = project_dir / "data"
    cfg = load_config(project_dir)
    landmarks = _landmarks_from_config(cfg, _cached_outlines(data))
    _write_landmarks_geojson(data, landmarks)
    localp = data / "seed.local.json"
    if localp.exists():
        local = json.loads(localp.read_text(encoding="utf-8"))
        origin = (local["origin"]["lon"], local["origin"]["lat"])
        local["landmarks"] = _project_landmarks(landmarks, origin, local["origin"]["elev_m"])
        localp.write_text(json.dumps(local), encoding="utf-8")
    print(f"[seed] landmarks refreshed: {', '.join(landmarks)}")


def build(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    data = project_dir / "data"
    data.mkdir(exist_ok=True)
    cfg = load_config(project_dir)

    # stale single-route artifacts from an earlier build shape would shadow the network
    for stale in ("centerline.geojson", "centerline.elevation.json", "centerline.local.json"):
        (data / stale).unlink(missing_ok=True)

    # --- 1. KML network + OSM augment -> deduped, smoothed, classified edges --------------------
    build_network(project_dir)
    classify(project_dir)

    # --- 2. landmarks ---------------------------------------------------------------------------
    landmarks = _landmarks_from_config(cfg, _cached_outlines(data))
    _write_landmarks_geojson(data, landmarks)
    print(f"[seed] landmarks: {', '.join(landmarks)}")

    # --- 3. elevation: every edge + terrain grid over the network bbox --------------------------
    network_elev.build(project_dir)
    meta = json.loads((data / "heightfield.meta.json").read_text(encoding="utf-8"))
    s, w, n, e = meta["bbox_swne"]
    for name, lm in landmarks.items():
        pts = lm.get("outline_lonlat") or [tuple(lm["point_lonlat"])]
        if not all(s <= la <= n and w <= lo <= e for lo, la in pts):
            raise SystemExit(f"[seed] landmark '{name}' falls outside the heightfield bbox — "
                             f"extend the network or sample a wider grid")

    # --- 4. spine: home -> school along the built network ---------------------------------------
    net = json.loads((data / "network.geojson").read_text(encoding="utf-8"))
    feats = [f for f in net["features"] if f["properties"].get("kind") == "edge"]
    anchors = {a["name"]: (a["lon"], a["lat"]) for a in cfg.raw["route"]["anchors"]}
    hops = _spine(feats, anchors["home"], anchors["school"],
                  ref=(net["properties"]["ref_lon"], net["properties"]["ref_lat"]),
                  snap_m=float(cfg.raw.get("network", {}).get("snap_grid_m", 11.0)))
    by_id = {f["properties"]["id"]: f for f in feats}
    elev = {ed["id"]: ed for ed in
            json.loads((data / "network.elevation.json").read_text(encoding="utf-8"))["edges"]}
    spine_ll: list[Vertex] = []
    spine_z: list[float] = []
    for eid, fwd in hops:
        cs = [tuple(c) for c in by_id[eid]["geometry"]["coordinates"]]
        zs = list(elev[eid]["z_smooth_m"])
        if not fwd:
            cs, zs = cs[::-1], zs[::-1]
        if spine_ll:
            cs, zs = cs[1:], zs[1:]
        spine_ll += cs
        spine_z += zs
    spine_len = sum(_hav(a, b) for a, b in zip(spine_ll, spine_ll[1:]))
    (data / "spine.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"name": "spine", "kind": "spine", "length_m": round(spine_len, 1),
                           "edges": [eid for eid, _ in hops]},
            "geometry": {"type": "LineString", "coordinates": [[lo, la] for lo, la in spine_ll]},
        }],
    }), encoding="utf-8")
    print(f"[seed] spine: {spine_len/1000:.2f} km over {len(hops)} network edges")

    # --- 5. one ENU frame for everything ---------------------------------------------------------
    all_ll = [tuple(c) for f in feats for c in f["geometry"]["coordinates"]]
    origin = centroid(all_ll)
    elev0 = min(min(elev[f["properties"]["id"]]["z_smooth_m"]) for f in feats)

    roads = []
    total_km = 0.0
    for f in feats:
        p = f["properties"]
        cs = [tuple(c) for c in f["geometry"]["coordinates"]]
        zs = elev[p["id"]]["z_smooth_m"]
        loc = project_to_local(cs, zs, origin, elev0)
        roads.append({"id": p["id"], "name": p.get("name"), "road_class": p.get("road_class"),
                      "width_m": p.get("width_m"), "length_m": p["length_m"],
                      "points_xyz_m": [[round(x, 2), round(y, 2), round(z, 2)] for x, y, z in loc]})
        total_km += p["length_m"] / 1000.0

    spine_loc = project_to_local(spine_ll, spine_z, origin, elev0)
    lm_local = _project_landmarks(landmarks, origin, elev0)

    (data / "seed.local.json").write_text(json.dumps({
        "frame": "ENU local meters (X=east, Y=up, Z=north)",
        "origin": {"lon": origin[0], "lat": origin[1], "elev_m": round(elev0, 2)},
        "true_north_rotation_deg": 0.0,
        "roads": roads,
        "spine": {"length_m": round(spine_len, 1),
                  "points_xyz_m": [[round(x, 2), round(y, 2), round(z, 2)] for x, y, z in spine_loc]},
        "landmarks": lm_local,
        "landmarks_y": "drape on heightfield",
    }), encoding="utf-8")
    print(f"[seed] projected: {len(roads)} edges ({total_km:.1f} km), spine {spine_len/1000:.2f} km, "
          f"{len(lm_local)} landmarks -> data/seed.local.json")
    return {"edges": len(roads), "network_km": round(total_km, 1), "spine_km": round(spine_len / 1000, 2)}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m scripts.game.build_seed projects/<slug> [--landmarks-only]")
    if "--landmarks-only" in sys.argv[2:]:
        refresh_landmarks(sys.argv[1])
    else:
        build(sys.argv[1])


if __name__ == "__main__":
    main()
