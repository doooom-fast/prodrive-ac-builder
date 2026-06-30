"""Isolate ONE instance from a merged map-batch OBJ (e.g. a mined SRP gantry/pillar kn5 chunk that
holds every instance across the whole map in world space) and recenter it to the origin as a reusable prop.

Splits the mesh into connected components (instances are separate, unwelded sub-meshes), picks one near
the median triangle-count (a typical instance, not an outlier fragment), drops it to origin (XZ-centred,
base at Y=0) and writes a clean OBJ. Stdlib only.

    python -m scripts.modkit.isolate_instance <in.obj> <out.obj> [--pick median|largest]
"""

from __future__ import annotations

import sys
from pathlib import Path


def _load(path):
    V, F = [], []
    for ln in Path(path).read_text().splitlines():
        if ln.startswith("v "):
            _, x, y, z = ln.split()[:4]; V.append((float(x), float(y), float(z)))
        elif ln.startswith("f "):
            F.append([int(p.split("/")[0]) - 1 for p in ln.split()[1:]])
    return V, F


def _components(nv, F):
    """Union-find over vertices joined by shared faces -> connected components of faces."""
    parent = list(range(nv))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for f in F:
        for k in range(1, len(f)):
            union(f[0], f[k])
    comps = {}
    for fi, f in enumerate(F):
        comps.setdefault(find(f[0]), []).append(fi)
    return list(comps.values())


def isolate(in_obj, out_obj, pick="median"):
    V, F = _load(in_obj)
    comps = _components(len(V), F)
    comps.sort(key=len)
    if pick == "largest":
        chosen = comps[-1]
    else:
        chosen = comps[len(comps) // 2]      # median-size component = a typical instance
    used = sorted({v for fi in chosen for v in F[fi]})
    remap = {old: k for k, old in enumerate(used)}
    sub = [V[u] for u in used]
    xs = [p[0] for p in sub]; ys = [p[1] for p in sub]; zs = [p[2] for p in sub]
    cx = (min(xs) + max(xs)) / 2; cz = (min(zs) + max(zs)) / 2; y0 = min(ys)
    sub = [(x - cx, y - y0, z - cz) for x, y, z in sub]   # recenter XZ, base at Y=0
    lines = [f"# isolated 1 instance from {Path(in_obj).name} ({len(comps)} components)"]
    for x, y, z in sub:
        lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
    for fi in chosen:
        lines.append("f " + " ".join(str(remap[v] + 1) for v in F[fi]))
    Path(out_obj).write_text("\n".join(lines) + "\n")
    dx, dy, dz = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
    print(f"isolate: {len(comps)} components -> picked {len(chosen)} tris; "
          f"instance size {dx:.1f}x{dy:.1f}x{dz:.1f} m -> {out_obj}")
    return dx, dy, dz


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pick = "largest" if "--pick" in sys.argv and sys.argv[sys.argv.index("--pick") + 1] == "largest" else "median"
    isolate(args[0], args[1], pick)
