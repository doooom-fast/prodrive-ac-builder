"""Generate the procedural gravel-road texture pair used by ``road_surface: gravel``.

Rally stages run on graded dirt/gravel county roads, and the engine's road textures are all asphalt.
Rather than mine a gravel texture out of somebody's mod (personal-use-only, see SOURCES.txt), this
synthesises one — so the gravel variant of any track stays fully redistributable.

The look is a **graded high-desert county road**, not a river-rock gravel pit: a hard-packed
tan/clay base, a scatter of small embedded stones, faint wheel-track darkening, and the loose berm
grain that shows up between the tracks. Deterministic (fixed seed) so rebuilds are byte-stable.

Output (1024x1024 PNG, power-of-two — a non-PoT texture hard-crashes AC on load):
    assets/textures/gravel_road_diffuse.png
    assets/textures/gravel_road_normal.png     (OpenGL convention, matching the rest of the set)

Run:  python -m scripts.assets.make_gravel
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SIZE = 1024
SEED = 20260724


def _value_noise(rng: np.random.Generator, size: int, cells: int) -> np.ndarray:
    """Tiling value noise: random lattice + smoothstep interpolation, wrapped so the texture repeats
    seamlessly (a visible seam every 15 m of road is the tell of a generated surface)."""
    lat = rng.random((cells, cells))
    lat = np.vstack([lat, lat[:1]])           # wrap: last row/col repeat the first
    lat = np.hstack([lat, lat[:, :1]])
    t = np.linspace(0, cells, size, endpoint=False)
    i = t.astype(int)
    f = t - i
    f = f * f * (3 - 2 * f)                    # smoothstep
    a = lat[np.ix_(i, i)]
    b = lat[np.ix_(i + 1, i)]
    c = lat[np.ix_(i, i + 1)]
    d = lat[np.ix_(i + 1, i + 1)]
    fx = f[None, :]
    fy = f[:, None]
    return (a * (1 - fy) * (1 - fx) + b * fy * (1 - fx) + c * (1 - fy) * fx + d * fy * fx)


def _fbm(rng: np.random.Generator, size: int, octaves: int, base: int) -> np.ndarray:
    """Fractal sum of value noise — the grain that reads as compacted dirt at driving speed."""
    out = np.zeros((size, size))
    amp, total, cells = 1.0, 0.0, base
    for _ in range(octaves):
        out += amp * _value_noise(rng, size, cells)
        total += amp
        amp *= 0.5
        cells *= 2
    return out / total


def _stones(rng: np.random.Generator, size: int, count: int) -> np.ndarray:
    """Small embedded stones: bright elliptical blobs, radius in pixels. Wrapped at the edges so a
    stone straddling the border appears on both sides and the tile still repeats cleanly."""
    field = np.zeros((size, size))
    ys, xs = np.mgrid[0:size, 0:size]
    for _ in range(count):
        cx, cy = rng.integers(0, size, 2)
        r = rng.uniform(4.0, 13.0)
        # wrapped distance, so stones cross the seam instead of being clipped by it
        dx = np.minimum(np.abs(xs - cx), size - np.abs(xs - cx))
        dy = np.minimum(np.abs(ys - cy), size - np.abs(ys - cy))
        d = np.sqrt((dx / r) ** 2 + (dy / (r * rng.uniform(0.7, 1.3))) ** 2)
        field = np.maximum(field, np.clip(1.0 - d, 0, 1) ** 1.4 * rng.uniform(0.35, 0.8))
    return field


def _normal_from_height(h: np.ndarray, strength: float) -> np.ndarray:
    """Height field -> OpenGL-convention normal map (+Y up), wrapped like the diffuse."""
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * strength
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * strength
    nz = np.ones_like(h)
    ln = np.sqrt(dx * dx + dy * dy + nz * nz)
    n = np.stack([-dx / ln, dy / ln, nz / ln], axis=-1)   # OpenGL: +Y is up
    return ((n * 0.5 + 0.5) * 255).astype(np.uint8)


def generate(out_dir: Path) -> tuple:
    rng = np.random.default_rng(SEED)

    base = _fbm(rng, SIZE, octaves=5, base=4)             # broad clay mottling
    grain = _fbm(rng, SIZE, octaves=4, base=64)           # fine compacted grain
    stones = _stones(rng, SIZE, count=650)

    # Wheel tracks: two darker, smoother bands where traffic has polished the surface. Sinusoidal in
    # V so the tracks wander slightly instead of running as ruler-straight stripes.
    v = np.linspace(0, 2 * np.pi, SIZE, endpoint=False)[:, None]
    u = np.linspace(0, 1, SIZE, endpoint=False)[None, :]
    wander = 0.02 * np.sin(v * 2)
    track = np.zeros((SIZE, SIZE))
    for centre in (0.28, 0.72):
        track += np.exp(-(((u - centre - wander) / 0.10) ** 2))
    track = np.clip(track, 0, 1)

    height = 0.45 * base + 0.30 * grain + 0.55 * stones - 0.18 * track
    height = (height - height.min()) / (height.max() - height.min())

    # Dry high-desert tan/clay. Stones read paler and greyer; the wheel tracks a little darker and
    # duller than the loose berm between them.
    dirt = np.array([0.62, 0.53, 0.40])
    stone = np.array([0.66, 0.62, 0.55])
    shade = (0.72 + 0.38 * base - 0.16 * track)[..., None]
    rgb = dirt[None, None, :] * shade
    rgb = rgb * (1 - stones[..., None] * 0.55) + stone[None, None, :] * (stones[..., None] * 0.55)
    rgb *= (0.90 + 0.16 * grain)[..., None]
    diffuse = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)

    out_dir.mkdir(parents=True, exist_ok=True)
    dpath = out_dir / "gravel_road_diffuse.png"
    npath = out_dir / "gravel_road_normal.png"
    Image.fromarray(diffuse, "RGB").save(dpath)
    Image.fromarray(_normal_from_height(height, strength=2.6), "RGB").save(npath)
    return dpath, npath


def main() -> None:
    out = Path(__file__).resolve().parents[2] / "assets" / "textures"
    for p in generate(out):
        print(f"wrote {p}  ({Image.open(p).size[0]}x{Image.open(p).size[1]})")


if __name__ == "__main__":
    main()
