"""Procedural texture suite — every texture the track uses, generated deterministically.

Kunos-grade dressing needs ~25 coordinated textures (road, kerb, grass, facades, signage, trees,
fences, tanks, horizon…). Rather than depending on downloaded assets, this generates the whole set
from seeded numpy noise + a bitmap sign font, so a clean checkout rebuilds the exact same look from
``track.config.json`` (street names end up on the actual street-blade signs).

Needs numpy — run under Blender's bundled Python (the build host already has Blender):
    blender --background --python scripts/ac/texgen.py -- projects/<slug>
or any Python with numpy:
    python3 -m scripts.ac.texgen projects/<slug>

Writes PNGs + ``manifest.json`` (sign-atlas UV rects, OBJ V-convention: v=0 bottom) into
``assets/textures/generated/``. The kn5 export stages them into ``build/texture/``.
"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- core helpers

def write_png(path: Path, arr: np.ndarray) -> None:
    """Minimal PNG writer (8-bit RGB/RGBA), stdlib only."""
    arr = np.ascontiguousarray(arr.astype(np.uint8))
    h, w = arr.shape[:2]
    ctype = 6 if (arr.ndim == 3 and arr.shape[2] == 4) else 2
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + \
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n"
                           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _rng(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng((seed * 1_000_003 + zlib.crc32(name.encode())) & 0x7FFFFFFF)


def _grid_noise(rng: np.random.Generator, res: int, size: int) -> np.ndarray:
    """One octave of seamlessly tiling value noise (periodic bilinear upsample, smoothstep)."""
    res = max(2, min(res, size))
    g = rng.random((res, res)).astype(np.float32)
    xs = np.linspace(0, res, size, endpoint=False)
    i0 = np.floor(xs).astype(np.int64) % res
    i1 = (i0 + 1) % res
    t = (xs - np.floor(xs)).astype(np.float32)
    t = t * t * (3.0 - 2.0 * t)
    row = g[:, i0] * (1 - t) + g[:, i1] * t                       # (res, size)
    out = row[i0, :] * (1 - t)[:, None] + row[i1, :] * t[:, None]  # (size, size)
    return out


def fbm(rng: np.random.Generator, size: int, *, base: int = 4, octaves: int = 5,
        gain: float = 0.5, lac: float = 2.0) -> np.ndarray:
    """Tiling fractal noise in [0,1]."""
    total = np.zeros((size, size), np.float32)
    amp, norm, res = 1.0, 0.0, float(base)
    for _ in range(octaves):
        total += amp * _grid_noise(rng, int(res), size)
        norm += amp
        amp *= gain
        res *= lac
    return total / norm


def normal_map(height: np.ndarray, strength: float = 2.0) -> np.ndarray:
    """Tangent-space normal map from a [0,1] height field (DirectX-style green)."""
    gx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength
    gy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength
    nz = np.ones_like(height)
    ln = np.sqrt(gx * gx + gy * gy + nz * nz)
    n = np.stack([-gx / ln, gy / ln, nz / ln], axis=-1)
    return ((n * 0.5 + 0.5) * 255.0).clip(0, 255)


def to_u8(rgb: np.ndarray) -> np.ndarray:
    return (np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)


def tint(lum: np.ndarray, color: tuple[float, float, float]) -> np.ndarray:
    return np.stack([lum * c for c in color], axis=-1)


# ---------------------------------------------------------------- bitmap font (5x7)

_F = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 11110 10001 10001 10001 11110",
    "C": "01111 10000 10000 10000 10000 10000 01111", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 11110 10000 10000 10000 11111", "F": "11111 10000 11110 10000 10000 10000 10000",
    "G": "01111 10000 10000 10111 10001 10001 01110", "H": "10001 10001 11111 10001 10001 10001 10001",
    "I": "11111 00100 00100 00100 00100 00100 11111", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 11100 10010 10001 10001 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10010 10001 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001", "X": "10001 01010 00100 00100 01010 10001 10001",
    "Y": "10001 01010 00100 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00110 01000 10000 11111", "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "01110 10000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00001 01110",
    "-": "00000 00000 00000 11111 00000 00000 00000", ".": "00000 00000 00000 00000 00000 00110 00110",
    "/": "00001 00010 00010 00100 01000 01000 10000", " ": "00000 00000 00000 00000 00000 00000 00000",
    "'": "00100 00100 00000 00000 00000 00000 00000", "&": "01100 10010 10100 01000 10101 10010 01101",
}


def text_w(text: str, scale: int) -> int:
    return len(text) * 6 * scale - scale


def draw_text(img: np.ndarray, x: int, y: int, text: str, scale: int,
              color: tuple[float, float, float], alpha: np.ndarray | None = None) -> None:
    """Blit 5x7 glyphs (top-left anchor); writes ``color`` into img, 1.0 into ``alpha`` if given."""
    H, W = img.shape[:2]
    cx = x
    for ch in text.upper():
        rows = _F.get(ch, _F[" "]).split()
        for r, bits in enumerate(rows):
            for c, b in enumerate(bits):
                if b == "1":
                    y0, y1 = y + r * scale, y + (r + 1) * scale
                    x0, x1 = cx + c * scale, cx + (c + 1) * scale
                    if 0 <= y0 and y1 <= H and 0 <= x0 and x1 <= W:
                        img[y0:y1, x0:x1] = color
                        if alpha is not None:
                            alpha[y0:y1, x0:x1] = 1.0
        cx += 6 * scale


def draw_text_centered(img, cy_px, text, scale, color, alpha=None, cx_px=None):
    w = text_w(text, scale)
    x = (img.shape[1] - w) // 2 if cx_px is None else cx_px - w // 2
    draw_text(img, x, cy_px - (7 * scale) // 2, text, scale, color, alpha)


# ---------------------------------------------------------------- texture builders

def tex_road(seed: int, size: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Worn urban asphalt: mottled repaving, fine aggregate, cracks + tar snakes, faded patches.
    Tiles every 4 m. Returns (diffuse RGB, normal RGB)."""
    r = _rng(seed, "road")
    macro = fbm(r, size, base=3, octaves=3)            # repave mottling
    agg = fbm(r, size, base=192, octaves=3, gain=0.6)  # aggregate sparkle
    mid = fbm(r, size, base=24, octaves=3)
    lum = 0.295 + (macro - 0.5) * 0.085 + (mid - 0.5) * 0.05 + (agg - 0.5) * 0.11
    height = agg * 0.55 + mid * 0.45

    # faded rectangular patches (older repaves) with sealed edges
    for _ in range(5):
        x0, y0 = r.integers(0, size, 2)
        w, h = int(r.integers(size // 8, size // 3)), int(r.integers(size // 10, size // 4))
        xs = (np.arange(x0, x0 + w)) % size
        ys = (np.arange(y0, y0 + h)) % size
        lum[np.ix_(ys, xs)] += float(r.uniform(-0.045, 0.045))
        edge = 4
        lum[np.ix_(ys[:edge], xs)] -= 0.10
        lum[np.ix_(ys[-edge:], xs)] -= 0.10
        lum[np.ix_(ys, xs[:edge])] -= 0.10
        lum[np.ix_(ys, xs[-edge:])] -= 0.10

    # cracks (random walks) — half left open, half filled as dark tar snakes
    for k in range(26):
        x, y = float(r.integers(0, size)), float(r.integers(0, size))
        ang = float(r.uniform(0, 2 * np.pi))
        snake = k % 2 == 0
        for _ in range(int(r.integers(140, 540))):
            ang += float(r.uniform(-0.45, 0.45))
            x = (x + np.cos(ang) * 2.4) % size
            y = (y + np.sin(ang) * 2.4) % size
            xi, yi = int(x), int(y)
            wpx = 3 if snake else 2
            xs = np.arange(xi, xi + wpx) % size
            ys = np.arange(yi, yi + wpx) % size
            lum[np.ix_(ys, xs)] = 0.16 if snake else 0.13
            height[np.ix_(ys, xs)] -= 0.08 if snake else 0.30

    rgb = np.stack([lum * 1.00, lum * 1.00, lum * 1.06], axis=-1)  # cold asphalt
    rgb += (fbm(r, size, base=8, octaves=2)[..., None] - 0.5) * np.array([0.02, 0.015, -0.01])
    return to_u8(rgb), normal_map(np.clip(height, 0, 1), 2.4).astype(np.uint8)


def tex_wear(seed: int, w: int = 512, h: int = 1024) -> np.ndarray:
    """RGBA racing-line/lane grime overlay strip: dark tire polish, streaky along V (the lap)."""
    r = _rng(seed, "wear")
    streak = fbm(r, h, base=6, octaves=4)[:, :w] if h >= w else fbm(r, w, base=6, octaves=4)[:h, :w]
    u = np.linspace(-1, 1, w)[None, :]
    bell = np.exp(-(u ** 2) * 3.2)
    alpha = np.clip(bell * (0.28 + 0.42 * streak), 0, 0.62)
    rgb = np.zeros((h, w, 3), np.float32) + np.array([0.045, 0.045, 0.05])
    return np.dstack([to_u8(rgb), (alpha * 255).astype(np.uint8)])


def tex_kerb(seed: int, size: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Painted concrete kerb: red/white blocks along V (1.2 m each at 0.6 m tile), paint worn
    through to concrete on the ridge crests, grime in the valleys."""
    r = _rng(seed, "kerb")
    conc = 0.60 + (fbm(r, size, base=48, octaves=4) - 0.5) * 0.18
    wear = fbm(r, size, base=12, octaves=4)
    v = np.linspace(0, 4, size, endpoint=False)[:, None]  # 4 paint blocks per texture tile
    is_red = (np.floor(v) % 2 == 0) * np.ones((size, size), bool)
    paint_red = np.stack([conc * 1.18, conc * 0.22, conc * 0.20], axis=-1)
    paint_wht = np.stack([conc * 1.12, conc * 1.10, conc * 1.04], axis=-1)
    rgb = np.where(is_red[..., None], paint_red, paint_wht)
    bare = np.stack([conc, conc, conc * 0.97], axis=-1)
    worn = (wear > 0.62)[..., None]                       # chipped to bare concrete
    rgb = np.where(worn, bare, rgb)
    # grime band toward the track-side ramp (right edge of profile, U near 1)
    uu = np.linspace(0, 1, size)[None, :, None]
    rgb *= 1.0 - 0.28 * np.clip((uu - 0.62) / 0.38, 0, 1)
    height = conc * 0.5 + wear * 0.2
    return to_u8(rgb), normal_map(height, 1.8).astype(np.uint8)


def tex_grass(seed: int, size: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Semi-arid front-range turf: green/dry patch mix, dirt show-through, fine blade noise."""
    r = _rng(seed, "grass")
    patch = fbm(r, size, base=5, octaves=4)
    blade = fbm(r, size, base=160, octaves=3, gain=0.55)
    dirt = fbm(r, size, base=7, octaves=3)
    green = np.array([0.30, 0.38, 0.16])
    dry = np.array([0.52, 0.47, 0.27])
    soil = np.array([0.40, 0.33, 0.24])
    t = np.clip((patch - 0.35) * 2.4, 0, 1)[..., None]
    rgb = green * (1 - t) + dry * t
    sd = np.clip((dirt - 0.62) * 5.0, 0, 1)[..., None]
    rgb = rgb * (1 - sd) + soil * sd
    rgb *= 0.78 + blade[..., None] * 0.46
    return to_u8(rgb), normal_map(blade * 0.6 + patch * 0.4, 1.2).astype(np.uint8)


def tex_dirt(seed: int, size: int = 512) -> np.ndarray:
    """Gravel/ballast — rail beds and bare verges."""
    r = _rng(seed, "dirt")
    g = fbm(r, size, base=96, octaves=4, gain=0.62)
    base = 0.36 + (g - 0.5) * 0.30 + (fbm(r, size, base=6, octaves=2) - 0.5) * 0.10
    return to_u8(np.stack([base * 1.05, base * 0.97, base * 0.88], axis=-1))


def tex_concrete(seed: int, size: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Form-lined structural concrete (jersey walls, piers, decks): seams + water streaks."""
    r = _rng(seed, "conc")
    base = 0.585 + (fbm(r, size, base=24, octaves=4) - 0.5) * 0.10
    # vertical form seams every quarter tile
    x = np.arange(size)
    for sx in range(0, size, size // 4):
        base[:, (sx + x[:2]) % size] -= 0.07
    # water streaks descending (darker columns fading downward)
    streak_cols = r.integers(0, size, 26)
    vv = np.linspace(0, 1, size)[:, None]
    for c in streak_cols:
        wpx = int(r.integers(4, 18))
        fall = np.clip(vv - r.uniform(0.0, 0.4), 0, 1)
        base[:, c:c + wpx] -= (0.10 * fall * r.uniform(0.4, 1.0))[:, : max(0, min(wpx, size - c))]
    base -= np.clip(vv - 0.75, 0, 1) * 0.18  # ground grime at the bottom
    rgb = np.stack([base * 1.02, base, base * 0.95], axis=-1)
    return to_u8(rgb), normal_map(fbm(r, size, base=48, octaves=3) * 0.5, 1.0).astype(np.uint8)


# ------------------------------------------------------- facade factory
# Composites real CC0 scan bases (scripts/ac/fetch_textures.py → assets/textures/downloads/)
# with procedural fittings — docks, man doors, storefronts, sign bands, skirts, parapets — into
# a per-zone building variant library. Falls back to procedural bases when downloads are absent.

INDUSTRIAL_BASES = ["CorrugatedSteel007A", "CorrugatedSteel006A", "CorrugatedSteel005",
                    "CorrugatedSteel002", "Concrete034", "Concrete046"]
COMMERCIAL_BASES = ["Bricks051", "Bricks097", "Bricks060", "PaintedPlaster006", "PaintedPlaster017"]
OFFICE_BASES = ["Facade001", "Facade018A", "Facade006"]

INDUSTRIAL_SIGNS = ["SHIPPING", "RECEIVING", "K10 LOGISTICS", "SAND CREEK SUPPLY CO",
                    "COMMERCE COLD STORAGE", "PRODRIVE PARTS DEPOT"]
COMMERCIAL_SIGNS = ["QUALITY RESTAURANT EQUIPMENT", "AUTO PARTS", "TIRE & WHEEL",
                    "CREEKSIDE DINER", "LIQUOR - ICE", "DISCOUNT MUFFLER"]
AWNING_COLORS = [(0.55, 0.12, 0.10), (0.10, 0.28, 0.16), (0.12, 0.18, 0.38),
                 (0.55, 0.38, 0.08), (0.30, 0.10, 0.30)]


def _load_base(stem: str) -> tuple[np.ndarray, np.ndarray] | None:
    """(color, normalDX) float arrays (H,W,3) top-down from the downloads cache — raw file values
    (no colour management), needs bpy (texgen runs under Blender). None when missing/offline."""
    dl = Path(__file__).resolve().parents[2] / "assets" / "textures" / "downloads"
    cpath, npath = dl / f"{stem}_Color.jpg", dl / f"{stem}_NormalDX.jpg"
    if not (cpath.exists() and npath.exists()):
        return None
    try:
        import bpy
    except ImportError:
        return None
    out = []
    for p in (cpath, npath):
        img = bpy.data.images.load(str(p), check_existing=True)
        img.colorspace_settings.name = "Non-Color"   # raw values — exactly the file's bytes
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1, :, :3]
        out.append(px)
    return out[0], out[1]


def _fit(img: np.ndarray, size: int, tiles_x: float, tiles_y: float) -> np.ndarray:
    """Wrap-resample a base so it covers the canvas ``tiles`` times (integer tiles_x = seamless U)."""
    H, W = img.shape[:2]
    ys = (np.linspace(0, tiles_y * H, size, endpoint=False).astype(np.int64)) % H
    xs = (np.linspace(0, tiles_x * W, size, endpoint=False).astype(np.int64)) % W
    return img[ys][:, xs]


_FLAT_N = np.array([0.5, 0.5, 1.0], np.float32)


def _base_corrugated(seed: int, idx: int, size: int) -> tuple[np.ndarray, np.ndarray]:
    r = _rng(seed, f"bcorr{idx}")
    rib = 0.5 + 0.5 * np.sin(np.arange(size) * (2 * np.pi / 26.0))
    shade = np.repeat(0.62 + rib[None, :] * 0.10, size, axis=0)
    tone = [(0.66, 0.64, 0.60), (0.62, 0.63, 0.64), (0.48, 0.55, 0.60), (0.58, 0.54, 0.46),
            (0.60, 0.59, 0.56), (0.63, 0.62, 0.58)][idx % 6]
    rgb = np.stack([shade * t / 0.67 for t in tone], axis=-1)
    rgb *= 0.93 + fbm(r, size, base=64, octaves=2)[..., None] * 0.14
    nrm = normal_map(np.repeat((rib * 0.8)[None, :], size, axis=0), 2.2).astype(np.float32) / 255.0
    return rgb, nrm


def _base_brick(seed: int, idx: int, size: int) -> tuple[np.ndarray, np.ndarray]:
    r = _rng(seed, f"bbrick{idx}")
    course_h, brick_w = 12, 36
    yy, xx = np.mgrid[0:size, 0:size]
    row = yy // course_h
    offset = (row % 2) * (brick_w // 2)
    mortar = ((yy % course_h) < 2) | (((xx + offset) % brick_w) < 2)
    bval = 0.42 + (fbm(r, size, base=80, octaves=2) - 0.5) * 0.16
    per_brick = _rng(seed, f"bbrick2{idx}").random((size // course_h + 2, size // brick_w + 2)).astype(np.float32)
    bv = per_brick[row, ((xx + offset) // brick_w)] * 0.14
    tint = [(1.35, 0.78, 0.62), (1.20, 0.95, 0.80), (1.05, 1.0, 0.92), (1.3, 1.22, 1.05),
            (1.28, 1.18, 1.0)][idx % 5]
    rgb = np.stack([(bval + bv) * t for t in tint], axis=-1)
    rgb[mortar] = np.array([0.62, 0.60, 0.56])
    nrm = normal_map((~mortar).astype(np.float32) * 0.6, 1.6).astype(np.float32) / 255.0
    return rgb, nrm


def _base_glassgrid(seed: int, idx: int, size: int) -> tuple[np.ndarray, np.ndarray]:
    r = _rng(seed, f"bglass{idx}")
    rgb = np.zeros((size, size, 3), np.float32) + np.array([0.56, 0.56, 0.54])
    floors = 3
    fh = size // floors
    for f in range(floors):
        g0, g1 = f * fh + int(fh * 0.22), f * fh + int(fh * 0.78)
        sky_v = np.linspace(0.14, -0.06, g1 - g0)[:, None, None]
        rgb[g0:g1] = np.array([0.30, 0.38, 0.46]) + sky_v
        for mx in range(0, size, size // 6):
            rgb[g0:g1, mx:mx + 4] = np.array([0.23, 0.24, 0.25])
    rgb *= 0.95 + (fbm(r, size, base=10, octaves=2) - 0.5)[..., None] * 0.10
    return rgb, np.broadcast_to(_FLAT_N, (size, size, 3)).copy()


def _facade_base(family: str, idx: int, seed: int, size: int) -> tuple[np.ndarray, np.ndarray, str]:
    """(color, normal, base_stem) canvas for a variant — downloaded scan if cached, else procedural.
    Canvas spans 8 m of wall run; tiles_x stays integer so the facade tiles seamlessly along walls."""
    if family == "ind":
        stem = INDUSTRIAL_BASES[idx % len(INDUSTRIAL_BASES)]
        loaded = _load_base(stem)
        if loaded:
            tiles = 8.0 if "Corrugated" in stem else 4.0
            return _fit(loaded[0], size, tiles, tiles * 1.06), _fit(loaded[1], size, tiles, tiles * 1.06), stem
        return (*_base_corrugated(seed, idx, size), "procedural")
    if family == "com":
        stem = COMMERCIAL_BASES[idx % len(COMMERCIAL_BASES)]
        loaded = _load_base(stem)
        if loaded:
            tiles = 4.0
            return _fit(loaded[0], size, tiles, tiles * 0.81), _fit(loaded[1], size, tiles, tiles * 0.81), stem
        return (*_base_brick(seed, idx, size), "procedural")
    stem = OFFICE_BASES[idx % len(OFFICE_BASES)]
    loaded = _load_base(stem)
    if loaded:
        return _fit(loaded[0], size, 1.0, 1.0), _fit(loaded[1], size, 1.0, 1.0), stem
    return (*_base_glassgrid(seed, idx, size), "procedural")


def _flatten_n(nrm: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> None:
    nrm[y0:y1, x0:x1] = _FLAT_N


def _dock_door(rgb, nrm, x0: int, w: int, h: int) -> None:
    size = rgb.shape[0]
    slat = (0.92 + 0.08 * np.sin(np.arange(h) * (2 * np.pi / 14)))[:, None, None]
    rgb[size - h:, x0:x0 + w] = np.array([0.50, 0.51, 0.53]) * slat
    rgb[size - h:size - h + 3, x0:x0 + w] *= 0.55
    rgb[size - h:, x0:x0 + 2] *= 0.55
    rgb[size - h:, x0 + w - 2:x0 + w] *= 0.55
    _flatten_n(nrm, size - h, size, x0, x0 + w)


def _man_door(rgb, nrm, x0: int, w: int, h: int, color=(0.30, 0.31, 0.33)) -> None:
    size = rgb.shape[0]
    rgb[size - h:, x0:x0 + w] = np.array(color)
    rgb[size - h:size - h + 3, x0:x0 + w] = 0.8
    _flatten_n(nrm, size - h, size, x0, x0 + w)


def _window_band(rgb, nrm, y0: int, y1: int, xs: int, w: int, gap: int) -> None:
    for wx in range(xs, rgb.shape[1] - w, gap):
        rgb[y0:y1, wx:wx + w] = np.array([0.25, 0.30, 0.36])
        rgb[y0:y0 + 3, wx:wx + w] = 0.75
        _flatten_n(nrm, y0, y1, wx, wx + w)


def _skirt_parapet(rgb, nrm, r) -> None:
    size = rgb.shape[0]
    vv = np.linspace(1, 0, size)
    conc = 0.55 + (fbm(r, size, base=48, octaves=2) - 0.5) * 0.08
    rows = np.where(vv < 0.08)[0]                              # concrete skirt at grade
    rgb[rows] = np.stack([conc[rows]] * 3, axis=-1)
    nrm[rows] = _FLAT_N
    cap = np.where(vv > 0.96)[0]                               # parapet cap
    rgb[cap] = rgb[cap] * 0.55 + 0.12


def _rust(rgb, r, n: int, strength: float) -> None:
    size = rgb.shape[0]
    for c in r.integers(0, size, n):
        wpx = int(r.integers(3, 9))
        top = int(r.integers(0, size // 2))
        fall = np.clip((np.arange(size) - top) / (size * 0.5), 0, 1)[:, None, None] * strength
        rgb[:, c:c + wpx] = rgb[:, c:c + wpx] * (1 - fall) + np.array([0.38, 0.22, 0.12]) * fall


def tex_facade_industrial_v(seed: int, idx: int, size: int = 1024):
    """Industrial variant ``idx``: scan/procedural wall + docks, man door, window strip, sign."""
    r = _rng(seed, f"find{idx}")
    rgb, nrm, stem = _facade_base("ind", idx, seed, size)
    for jy in range(0, size, size // 8):                       # horizontal panel joints
        rgb[jy:jy + 2] *= 0.88
    layouts = [((0.08, 0.26), (0.62, 0.24)), ((0.12, 0.30),), ((0.06, 0.20), (0.40, 0.20), (0.72, 0.20))]
    for dx0, dw in layouts[idx % len(layouts)]:
        _dock_door(rgb, nrm, int(size * dx0), int(size * dw), int(size * 0.40))
    _man_door(rgb, nrm, int(size * 0.50), int(size * 0.05), int(size * 0.27))
    _window_band(rgb, nrm, int(size * 0.32), int(size * 0.38), int(size * 0.04), int(size * 0.09),
                 int(size * 0.24))
    sign = INDUSTRIAL_SIGNS[idx % len(INDUSTRIAL_SIGNS)]
    sw = text_w(sign, 3) + 24
    sx = int(size * 0.50) - sw // 2 + int(size * 0.025)
    rgb[int(size * 0.60):int(size * 0.66), sx:sx + sw] = np.array([0.88, 0.88, 0.84])
    draw_text_centered(rgb, int(size * 0.63), sign, 3, (0.15, 0.15, 0.18), cx_px=sx + sw // 2)
    _rust(rgb, r, 10 if "Corrugated" in stem else 4, 0.45)
    _skirt_parapet(rgb, nrm, r)
    return to_u8(rgb), to_u8(nrm)


def tex_facade_commercial_v(seed: int, idx: int, size: int = 1024):
    """Commercial variant ``idx``: brick/stucco + storefront glazing, awning, name sign band."""
    r = _rng(seed, f"fcom{idx}")
    rgb, nrm, _stem = _facade_base("com", idx, seed, size)
    # storefront band (bottom 38%): two glass bays + glass double door
    s0 = size - int(size * 0.38)
    rgb[s0:, :] = np.array([0.52, 0.51, 0.48])                 # storefront frame field
    _flatten_n(nrm, s0, size, 0, size)
    for bx0, bw in ((0.05, 0.32), (0.63, 0.32)):
        x0, w = int(size * bx0), int(size * bw)
        glass = np.array([0.24, 0.30, 0.37])
        sub = rgb[s0 + 8:size - 8, x0:x0 + w]
        grad = np.linspace(0.10, -0.04, sub.shape[0])[:, None, None]
        rgb[s0 + 8:size - 8, x0:x0 + w] = glass + grad
        rgb[s0 + 8:size - 8, x0 + w // 2 - 2:x0 + w // 2 + 2] = 0.2
    dx0 = int(size * 0.44)
    rgb[s0 + 8:, dx0:dx0 + int(size * 0.12)] = np.array([0.22, 0.27, 0.33])  # glass door
    rgb[s0 + 8:, dx0 + int(size * 0.058):dx0 + int(size * 0.062)] = 0.6
    # awning strip over the glass
    aw = AWNING_COLORS[idx % len(AWNING_COLORS)]
    stripes = (np.arange(size) // 24 % 2)[None, :, None]
    rgb[s0 - int(size * 0.045):s0, :] = np.array(aw) * (0.8 + 0.4 * stripes)
    # sign band above the awning with the business name
    sign = COMMERCIAL_SIGNS[idx % len(COMMERCIAL_SIGNS)]
    b0, b1 = s0 - int(size * 0.16), s0 - int(size * 0.055)
    rgb[b0:b1] = np.array([0.16, 0.15, 0.17])
    _flatten_n(nrm, b0, b1, 0, size)
    scale = max(2, min(5, (size - 60) // (6 * max(1, len(sign)))))
    draw_text_centered(rgb, (b0 + b1) // 2, sign, scale, (0.95, 0.92, 0.70))
    rgb[:int(size * 0.04)] = rgb[:int(size * 0.04)] * 0.55 + 0.12   # parapet cap
    rgb[size - 6:] *= 0.8                                            # grade grime
    return to_u8(rgb), to_u8(nrm)


def tex_facade_office_v(seed: int, idx: int, size: int = 1024):
    """Office variant ``idx``: multi-storey scan facade + glass lobby band at grade."""
    r = _rng(seed, f"foff{idx}")
    rgb, nrm, _stem = _facade_base("off", idx, seed, size)
    lob0 = size - int(size * 0.13)
    grad = np.linspace(0.08, -0.03, size - lob0)[:, None, None]
    rgb[lob0:] = np.array([0.20, 0.25, 0.31]) + grad
    _flatten_n(nrm, lob0, size, 0, size)
    for mx in range(0, size, size // 8):
        rgb[lob0:, mx:mx + 4] = np.array([0.30, 0.32, 0.34])
    dx = int(size * 0.47)
    rgb[lob0 + 4:, dx:dx + int(size * 0.06)] = np.array([0.55, 0.58, 0.60])
    rgb[:int(size * 0.025)] = rgb[:int(size * 0.025)] * 0.6 + 0.10
    return to_u8(rgb), to_u8(nrm)


def tex_facade_residential_v(seed: int, idx: int = 0, size: int = 1024):
    """Small-lot residential: horizontal lap siding, porch door, window pair, eave shadow."""
    r = _rng(seed, f"fres{idx}")
    course = size // 28
    yy = np.mgrid[0:size, 0:size][0]
    lap = 0.92 + 0.08 * ((yy % course) / course)
    tone = np.array([0.72, 0.70, 0.62])
    rgb = np.stack([lap * t for t in tone], axis=-1)
    rgb *= 0.94 + (fbm(r, size, base=10, octaves=2) - 0.5)[..., None] * 0.10
    nrm = normal_map(((yy % course) / course).astype(np.float32) * 0.4, 1.2).astype(np.float32) / 255.0
    glass = np.array([0.25, 0.30, 0.36])
    for wx0 in (0.14, 0.62):
        x0, w = int(size * wx0), int(size * 0.16)
        rgb[int(size * 0.45):int(size * 0.72), x0:x0 + w] = glass
        rgb[int(size * 0.45):int(size * 0.47), x0:x0 + w] = 0.85
        rgb[int(size * 0.70):int(size * 0.72), x0:x0 + w] = 0.85
        _flatten_n(nrm, int(size * 0.45), int(size * 0.72), x0, x0 + w)
    rgb[int(size * 0.50):, int(size * 0.42):int(size * 0.50)] = np.array([0.34, 0.22, 0.16])
    rgb[:int(size * 0.06)] *= 0.55                                   # eave shadow
    rgb[size - 5:] *= 0.8
    return to_u8(rgb), to_u8(nrm)


def tex_roof(seed: int, size: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Industrial flat roof (~8 m tile): membrane seams, gravel noise, vents, stains."""
    r = _rng(seed, "roof")
    base = 0.42 + (fbm(r, size, base=64, octaves=4) - 0.5) * 0.10
    for sy in range(0, size, size // 6):
        base[sy:sy + 2] *= 0.85
    for sx in range(0, size, size // 6):
        base[:, sx:sx + 2] *= 0.88
    rgb = np.stack([base, base * 0.99, base * 0.96], axis=-1)
    for _ in range(3):  # vents / RTUs baked as darker squares with a shadow edge
        x0, y0 = r.integers(size // 8, size - size // 6, 2)
        w = int(r.integers(size // 24, size // 12))
        rgb[y0:y0 + w, x0:x0 + w] = np.array([0.55, 0.55, 0.56])
        rgb[y0 + w:y0 + w + 4, x0:x0 + w] *= 0.6
    stain = fbm(r, size, base=5, octaves=2)
    rgb *= 0.92 + stain[..., None] * 0.16
    return to_u8(rgb), normal_map(fbm(r, size, base=128, octaves=2) * 0.3, 0.8).astype(np.uint8)


def tex_fence(seed: int, size: int = 512) -> np.ndarray:
    """RGBA chain-link: diamond mesh + top rail + post at the tile edge (3 m x 1.8 m world tile)."""
    r = _rng(seed, "fence")
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    period = size / 14.0
    a = np.abs(((xx + yy) % period) - period / 2) < 1.4
    b = np.abs(((xx - yy) % period) - period / 2) < 1.4
    alpha = (a | b).astype(np.float32)
    alpha[:6] = 1.0                                  # top rail
    alpha[:, :5] = 1.0                               # post (one per 3 m tile)
    lum = 0.52 + (fbm(r, size, base=32, octaves=2) - 0.5) * 0.18
    rgb = np.stack([lum, lum * 1.01, lum * 1.03], axis=-1)
    rgb[:6] *= 1.1
    return np.dstack([to_u8(rgb), (alpha * 255).astype(np.uint8)])


def tex_guardrail(seed: int, w: int = 512, h: int = 128) -> np.ndarray:
    """Galvanized W-beam strip: the W profile baked as horizontal light/shadow bands + bolts."""
    r = _rng(seed, "guard")
    vv = np.linspace(0, 1, h)[:, None]
    profile = 0.55 + 0.34 * np.cos((vv - 0.5) * np.pi * 4)   # two crests + valley
    spec = (fbm(r, w, base=48, octaves=2)[:h, :w] - 0.5) * 0.14
    lum = np.clip(profile + spec, 0, 1)
    rgb = np.stack([lum * 0.94, lum * 0.97, lum * 1.0], axis=-1)
    for bx in range(w // 8, w, w // 4):                       # bolt pairs
        rgb[h // 2 - 3:h // 2 + 3, bx - 3:bx + 3] *= 0.45
    return to_u8(rgb)


def tex_pole_steel(seed: int, w: int = 128, h: int = 512) -> np.ndarray:
    r = _rng(seed, "polest")
    lum = 0.58 + (fbm(r, h, base=24, octaves=3)[:h, :w] - 0.5) * 0.12
    lum *= (0.92 + 0.08 * np.sin(np.linspace(0, np.pi, w))[None, :])  # cylindrical shading
    lum[-int(h * 0.06):] *= 0.75                                       # base grime
    return to_u8(np.stack([lum * 0.96, lum * 0.985, lum], axis=-1))


def tex_pole_wood(seed: int, w: int = 128, h: int = 512) -> np.ndarray:
    r = _rng(seed, "polewd")
    grain = fbm(r, h, base=6, octaves=4)[:h, :w]
    streak = np.abs(np.sin(np.linspace(0, 14 * np.pi, w)))[None, :] * 0.1
    lum = 0.34 + (grain - 0.5) * 0.18 - streak
    rgb = np.stack([lum * 1.25, lum * 0.95, lum * 0.70], axis=-1)
    rgb *= (0.90 + 0.10 * np.sin(np.linspace(0, np.pi, w)))[None, :, None]
    return to_u8(rgb)


def tex_tank(seed: int, size: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Refinery storage tank shell: weathered white paint, weld courses, rust runs, rim grime."""
    r = _rng(seed, "tank")
    base = 0.78 + (fbm(r, size, base=10, octaves=4) - 0.5) * 0.10
    vv = np.linspace(0, 1, size)[:, None]
    rgb = np.stack([base, base * 0.985, base * 0.95], axis=-1)
    for cy in range(0, size, size // 5):  # weld courses
        rgb[cy:cy + 3] *= 0.82
        for c in _rng(seed, f"tankrust{cy}").integers(0, size, 7):
            wpx = int(r.integers(2, 7))
            ln = int(r.integers(size // 20, size // 5))
            fall = np.linspace(0.5, 0.0, ln)[:, None, None]
            seg = rgb[cy:cy + ln, c:c + wpx]
            rgb[cy:cy + ln, c:c + wpx] = seg * (1 - fall[:seg.shape[0]]) + \
                np.array([0.45, 0.27, 0.14]) * fall[:seg.shape[0]]
    rgb *= 1.0 - 0.25 * np.clip(vv - 0.82, 0, 1) / 0.18       # bottom grime
    rgb[:int(size * 0.02)] *= 0.7                              # top rim shadow
    return to_u8(rgb), normal_map(fbm(r, size, base=64, octaves=2) * 0.25, 0.7).astype(np.uint8)


def tex_tree_atlas(seed: int, size: int = 2048) -> np.ndarray:
    """RGBA billboard atlas, 4x2 cells of 512: row1 = trees (cottonwood, ash, elm, juniper),
    row0(bottom) = understory (bush, rabbitbrush, dry shrub, creek reeds)."""
    cell = size // 4
    img = np.zeros((size // 2 * 2, size, 4), np.float32)  # (2 rows of cell) x size

    def blob(canvas_rgb, canvas_a, cx, cy, rx, ry, color, rr, dapple):
        y0, y1 = max(0, int(cy - ry)), min(canvas_a.shape[0], int(cy + ry))
        x0, x1 = max(0, int(cx - rx)), min(canvas_a.shape[1], int(cx + rx))
        if y1 <= y0 or x1 <= x0:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        mask = (d < 1.0) & (dapple[y0:y1, x0:x1] > 0.30)
        sub_rgb = canvas_rgb[y0:y1, x0:x1]
        lit = 1.0 + (cy - yy) / (ry * 2.2) * 0.5             # light from above
        col = np.stack([np.full_like(d, c) for c in color], axis=-1) * lit[..., None]
        sub_rgb[mask] = col[mask]
        canvas_a[y0:y1, x0:x1][mask] = 1.0

    def tree(ci, base_col, *, height=0.92, width=0.78, nblobs=70, trunk_w=14, conifer=False,
             trunk_h=0.42, dapple_thr=0.30):
        r = _rng(seed, f"tree{ci}")
        rgb = np.zeros((cell * 2, cell, 3), np.float32)
        a = np.zeros((cell * 2, cell), np.float32)
        # use a 1x2 vertical canvas then downsample? keep square cell: canvas = cell x cell
        rgb = np.zeros((cell, cell, 3), np.float32)
        a = np.zeros((cell, cell), np.float32)
        dap = fbm(r, cell, base=48, octaves=4)
        gx, gy = cell // 2, cell - 4
        # trunk
        tx = float(gx)
        for yy_ in range(gy, int(cell * (1 - trunk_h)), -2):
            t = (gy - yy_) / (cell * trunk_h)
            wpx = max(2, int(trunk_w * (1 - t * 0.7)))
            tx += float(r.uniform(-1.2, 1.2))
            c = 0.30 - t * 0.06
            rgb[yy_:yy_ + 2, int(tx - wpx / 2):int(tx + wpx / 2)] = [c * 1.15, c * 0.95, c * 0.8]
            a[yy_:yy_ + 2, int(tx - wpx / 2):int(tx + wpx / 2)] = 1.0
        # branches
        tips = []
        for _ in range(7):
            bx, by = tx + r.uniform(-8, 8), cell * (1 - trunk_h) + r.uniform(-10, 30)
            ang = r.uniform(-2.4, -0.7)
            for s in range(int(r.integers(20, 48))):
                ang += r.uniform(-0.2, 0.2)
                bx += np.cos(ang) * 3
                by += np.sin(ang) * 3
                if 0 < int(by) < cell - 1 and 0 < int(bx) < cell - 1:
                    rgb[int(by):int(by) + 2, int(bx):int(bx) + 2] = [0.30, 0.25, 0.20]
                    a[int(by):int(by) + 2, int(bx):int(bx) + 2] = 1.0
            tips.append((bx, by))
        # canopy
        ccy = cell * (1 - height) + cell * height * (0.52 if not conifer else 0.55) * 0.62
        ccy = cell * (1 - height * 0.97) + (cell * 0.30)
        for i in range(nblobs):
            if conifer:
                t = i / nblobs
                cy_ = cell * (1 - height) + t * (cell * (height - trunk_h * 0.6))
                rx = (cell * width * 0.5) * (0.15 + 0.85 * t) * 0.6
                ry = rx * 0.55
                cx_ = gx + r.uniform(-rx * 0.3, rx * 0.3)
            else:
                src = tips[int(r.integers(0, len(tips)))]
                cx_ = np.clip(src[0] + r.uniform(-cell * 0.16, cell * 0.16), cell * 0.08, cell * 0.92)
                cy_ = np.clip(src[1] + r.uniform(-cell * 0.14, cell * 0.10),
                              cell * (1 - height), cell * (1 - trunk_h * 0.8))
                rx = r.uniform(cell * 0.07, cell * width * 0.20)
                ry = rx * r.uniform(0.7, 0.95)
            shade = r.uniform(0.8, 1.2)
            col = (base_col[0] * shade, base_col[1] * shade, base_col[2] * shade)
            blob(rgb, a, cx_, cy_, rx, ry, col, r, dap)
        return rgb, a

    variants = [
        ((0.32, 0.42, 0.14), dict(height=0.94, width=0.86, nblobs=85, trunk_w=18)),   # cottonwood
        ((0.26, 0.36, 0.13), dict(height=0.90, width=0.70, nblobs=70, trunk_w=12)),   # ash
        ((0.22, 0.30, 0.12), dict(height=0.95, width=0.55, nblobs=60, trunk_w=10)),   # elm (narrow)
        ((0.26, 0.32, 0.20), dict(height=0.88, width=0.62, nblobs=90, conifer=True)), # juniper
    ]
    shrubs = [
        ((0.30, 0.38, 0.15), dict(height=0.55, width=0.85, nblobs=45, trunk_w=4, trunk_h=0.10)),  # bush
        ((0.48, 0.46, 0.20), dict(height=0.48, width=0.80, nblobs=40, trunk_w=3, trunk_h=0.08)),  # rabbitbrush
        ((0.45, 0.38, 0.24), dict(height=0.50, width=0.75, nblobs=26, trunk_w=4, trunk_h=0.14)),  # dry shrub
        ((0.42, 0.44, 0.18), dict(height=0.72, width=0.45, nblobs=0, trunk_w=0, trunk_h=0.0)),    # reeds
    ]
    atlas = np.zeros((size // 2, size, 4), np.float32)
    for i, (col, kw) in enumerate(variants):
        rgb, a = tree(i, col, **kw)
        atlas[0:cell, i * cell:(i + 1) * cell, :3] = rgb
        atlas[0:cell, i * cell:(i + 1) * cell, 3] = a
    for i, (col, kw) in enumerate(shrubs):
        if i == 3:  # reeds: vertical blade fan
            r = _rng(seed, "reeds")
            rgb = np.zeros((cell, cell, 3), np.float32)
            a = np.zeros((cell, cell), np.float32)
            gx, gy = cell // 2, cell - 3
            for _ in range(150):
                ang = r.uniform(-0.5, 0.5) - np.pi / 2
                ln = r.uniform(cell * 0.3, cell * 0.7)
                x, y = gx + r.uniform(-cell * 0.18, cell * 0.18), float(gy)
                shade = r.uniform(0.7, 1.25)
                for s in range(int(ln)):
                    x += np.cos(ang) * 1.0 + r.uniform(-0.3, 0.3)
                    y += np.sin(ang) * 1.0
                    if 0 < int(y) < cell and 0 < int(x) < cell - 1:
                        rgb[int(y), int(x):int(x) + 2] = [col[0] * shade, col[1] * shade, col[2] * shade]
                        a[int(y), int(x):int(x) + 2] = 1.0
        else:
            rgb, a = tree(10 + i, col, **kw)
        atlas[cell:, i * cell:(i + 1) * cell, :3] = rgb
        atlas[cell:, i * cell:(i + 1) * cell, 3] = a
    return np.dstack([to_u8(atlas[..., :3]), to_u8(atlas[..., 3:4])[..., 0]])


def tex_signs(seed: int, roads: list[str], size: int = 1024) -> tuple[np.ndarray, dict]:
    """US road-sign atlas + manifest of UV rects (OBJ convention, v=0 at image bottom).
    Cells (256 px): row0 top = STOP|SL35|SL45|CHEVRON; row1 = curve-L|curve-R|DNE|XING;
    rows 2-3 = street blades (512x128 each, from real route road names) + 100/50 boards."""
    img = np.zeros((size, size, 4), np.float32)
    img[..., :3] = 0.5
    C = size // 4
    manifest: dict[str, list[float]] = {}

    def rect_uv(x0, y0, w, h):  # pixel rect (top-left) -> OBJ uv rect [u0,v0,u1,v1]
        return [x0 / size, 1 - (y0 + h) / size, (x0 + w) / size, 1 - y0 / size]

    def cell_bg(cx, cy, color, margin=12):
        x0, y0 = cx * C + margin, cy * C + margin
        img[y0:(cy + 1) * C - margin, x0:(cx + 1) * C - margin, :3] = color
        img[y0:(cy + 1) * C - margin, x0:(cx + 1) * C - margin, 3] = 1.0
        return x0, y0, C - 2 * margin

    # STOP — red octagon
    x0, y0, w = cell_bg(0, 0, (0.0, 0.0, 0.0, ), margin=10)
    yy, xx = np.mgrid[0:w, 0:w].astype(np.float32) - w / 2
    octa = (np.abs(xx) < w * 0.48) & (np.abs(yy) < w * 0.48) & (np.abs(xx) + np.abs(yy) < w * 0.66)
    sub = img[y0:y0 + w, x0:x0 + w]
    sub[..., :3][octa] = np.array([0.62, 0.07, 0.10])
    sub[..., 3] = octa.astype(np.float32)
    ring = octa & ~((np.abs(xx) < w * 0.44) & (np.abs(yy) < w * 0.44) & (np.abs(xx) + np.abs(yy) < w * 0.61))
    sub[..., :3][ring] = np.array([0.92, 0.92, 0.92])
    draw_text_centered(img[..., :3], y0 + w // 2, "STOP", 7, (0.95, 0.95, 0.95), img[..., 3],
                       cx_px=x0 + w // 2)
    manifest["stop"] = rect_uv(x0 - 10, y0 - 10, C, C)
    manifest["stop"] = rect_uv(0, 0, C, C)

    # speed limits
    for i, sl in enumerate(("35", "45")):
        x0, y0, w = cell_bg(1 + i, 0, (0.93, 0.93, 0.90), margin=26)
        img[y0:y0 + 4, x0:x0 + w, :3] = 0.05
        img[y0 + w - 4:y0 + w, x0:x0 + w, :3] = 0.05
        img[y0:y0 + w, x0:x0 + 4, :3] = 0.05
        img[y0:y0 + w, x0 + w - 4:x0 + w, :3] = 0.05
        draw_text_centered(img[..., :3], y0 + int(w * 0.18), "SPEED", 4, (0.05, 0.05, 0.05), img[..., 3], x0 + w // 2)
        draw_text_centered(img[..., :3], y0 + int(w * 0.38), "LIMIT", 4, (0.05, 0.05, 0.05), img[..., 3], x0 + w // 2)
        draw_text_centered(img[..., :3], y0 + int(w * 0.72), sl, 9, (0.05, 0.05, 0.05), img[..., 3], x0 + w // 2)
        manifest[f"speed{sl}"] = rect_uv((1 + i) * C, 0, C, C)

    # chevron panel (black on yellow, points right; mirror UVs for left)
    x0, y0, w = cell_bg(3, 0, (0.97, 0.72, 0.02), margin=14)
    yy, xx = np.mgrid[0:w, 0:w].astype(np.float32)
    arrow = np.abs(xx - (w * 0.30 + np.abs(yy - w / 2) * 0.55)) < w * 0.09
    arrow &= (yy > w * 0.10) & (yy < w * 0.90)
    img[y0:y0 + w, x0:x0 + w, :3][arrow] = np.array([0.06, 0.06, 0.06])
    manifest["chevron"] = rect_uv(3 * C, 0, C, C)

    # curve warning diamonds
    for i, (label, flip) in enumerate((("L", -1), ("R", 1))):
        cx, cy = i, 1
        x0, y0 = cx * C, cy * C
        yy, xx = np.mgrid[0:C, 0:C].astype(np.float32) - C / 2
        dia = (np.abs(xx) + np.abs(yy)) < C * 0.46
        ring = dia & ((np.abs(xx) + np.abs(yy)) > C * 0.42)
        sub = img[y0:y0 + C, x0:x0 + C]
        sub[..., :3][dia] = np.array([0.97, 0.72, 0.02])
        sub[..., :3][ring] = np.array([0.06, 0.06, 0.06])
        sub[..., 3][dia] = 1.0
        # curved arrow: polyline
        pts = [(0.0, 0.30), (0.02 * flip, 0.18), (0.06 * flip, 0.06), (0.13 * flip, -0.04),
               (0.22 * flip, -0.11), (0.20 * flip, -0.2)]
        for k in range(len(pts) - 1):
            for t in np.linspace(0, 1, 24):
                px = (pts[k][0] * (1 - t) + pts[k + 1][0] * t) * C + C / 2
                py = (pts[k][1] * (1 - t) + pts[k + 1][1] * t) * C + C / 2
                img[y0 + int(py) - 4:y0 + int(py) + 4, x0 + int(px) - 4:x0 + int(px) + 4, :3] = 0.06
        manifest[f"curve_{label}"] = rect_uv(x0, y0, C, C)

    # DO NOT ENTER
    x0, y0, w = cell_bg(2, 1, (0.93, 0.93, 0.90), margin=20)
    yy, xx = np.mgrid[0:w, 0:w].astype(np.float32) - w / 2
    disk = (xx ** 2 + yy ** 2) < (w * 0.46) ** 2
    sub = img[y0:y0 + w, x0:x0 + w]
    sub[..., :3][disk] = np.array([0.66, 0.08, 0.10])
    bar = disk & (np.abs(yy) < w * 0.10)
    sub[..., :3][bar] = np.array([0.95, 0.95, 0.95])
    draw_text_centered(img[..., :3], y0 + int(w * 0.18), "DO NOT", 3, (0.95, 0.95, 0.95), img[..., 3], x0 + w // 2)
    draw_text_centered(img[..., :3], y0 + int(w * 0.84), "ENTER", 3, (0.95, 0.95, 0.95), img[..., 3], x0 + w // 2)
    manifest["dne"] = rect_uv(2 * C, C, C, C)

    # pedestrian crossing diamond
    x0, y0 = 3 * C, C
    yy, xx = np.mgrid[0:C, 0:C].astype(np.float32) - C / 2
    dia = (np.abs(xx) + np.abs(yy)) < C * 0.46
    sub = img[y0:y0 + C, x0:x0 + C]
    sub[..., :3][dia] = np.array([0.97, 0.72, 0.02])
    sub[..., 3][dia] = 1.0
    ring = dia & ((np.abs(xx) + np.abs(yy)) > C * 0.42)
    sub[..., :3][ring] = np.array([0.06, 0.06, 0.06])
    draw_text_centered(img[..., :3], y0 + C // 2, "XING", 5, (0.06, 0.06, 0.06), img[..., 3], x0 + C // 2)
    manifest["xing"] = rect_uv(x0, y0, C, C)

    # street blades (512x128) from real road names
    def shorten(name: str) -> str:
        out = name.upper()
        for a, b in (("NORTH ", "N "), ("SOUTH ", "S "), ("EAST ", "E "), ("WEST ", "W "),
                     ("STREET", "ST"), ("AVENUE", "AVE"), ("BOULEVARD", "BLVD"), ("NORTHFIELD ", "")):
            out = out.replace(a, b)
        return out[:14]

    blades = [shorten(n) for n in (roads or [])][:4] or ["MAIN ST"]
    bw, bh = size // 2, size // 8
    for i, name in enumerate(blades):
        bx = (i % 2) * bw
        by = 2 * C + (i // 2) * bh
        img[by + 8:by + bh - 8, bx + 8:bx + bw - 8, :3] = np.array([0.05, 0.32, 0.16])
        img[by + 8:by + bh - 8, bx + 8:bx + bw - 8, 3] = 1.0
        img[by + 8:by + 12, bx + 8:bx + bw - 8, :3] = 0.92
        img[by + bh - 12:by + bh - 8, bx + 8:bx + bw - 8, :3] = 0.92
        draw_text_centered(img[..., :3], by + bh // 2, name, 6, (0.95, 0.95, 0.95), img[..., 3], bx + bw // 2)
        manifest[f"blade{i}"] = rect_uv(bx, by, bw, bh)
    manifest["n_blades"] = float(len(blades))

    # brake-marker boards 100 / 50 (white on red, race dressing)
    for i, num in enumerate(("100", "50")):
        x0 = (2 + i) * C
        y0 = 3 * C + C // 4
        img[y0:y0 + C // 2, x0 + 10:x0 + C - 10, :3] = np.array([0.75, 0.10, 0.10])
        img[y0:y0 + C // 2, x0 + 10:x0 + C - 10, 3] = 1.0
        draw_text_centered(img[..., :3], y0 + C // 4, num, 8, (0.97, 0.97, 0.97), img[..., 3], x0 + C // 2)
        manifest[f"board{num}"] = rect_uv(x0, y0, C, C // 2)

    return np.dstack([to_u8(img[..., :3]), to_u8(img[..., 3:4])[..., 0]]), manifest


def tex_adboards(seed: int, size: int = 1024) -> tuple[np.ndarray, dict]:
    """Sponsor banners + highway gantry plates. Returns (RGB, manifest of OBJ-V uv rects)."""
    img = np.zeros((size, size, 3), np.float32) + 0.1
    manifest: dict[str, list[float]] = {}

    def rect_uv(x0, y0, w, h):
        return [x0 / size, 1 - (y0 + h) / size, (x0 + w) / size, 1 - y0 / size]

    panels = [
        ("PRODRIVE", (0.07, 0.12, 0.35), (0.95, 0.95, 0.97), (0.85, 0.65, 0.05)),
        ("SAND CREEK RACEWAY", (0.05, 0.30, 0.16), (0.95, 0.95, 0.95), (0.9, 0.9, 0.9)),
        ("K10 MOTORSPORT", (0.08, 0.08, 0.09), (0.95, 0.80, 0.10), (0.6, 0.6, 0.6)),
        ("COMMERCE CITY CO", (0.55, 0.10, 0.10), (0.97, 0.97, 0.97), (0.9, 0.75, 0.1)),
    ]
    ph = size // 8
    for i, (txt, bg, fg, stripe) in enumerate(panels):
        y0 = i * ph
        img[y0 + 4:y0 + ph - 4, 4:-4] = bg
        img[y0 + ph - 18:y0 + ph - 10, 4:-4] = stripe
        scale = min(7, (size - 80) // (6 * max(1, len(txt))))
        draw_text_centered(img, y0 + ph // 2 - 4, txt, scale, fg)
        manifest[f"ad{i}"] = rect_uv(0, y0, size, ph)

    gantries = [("DENVER  /  I-270 WEST", "EXIT 1A  QUEBEC ST"),
                ("COMMERCE CITY  NEXT 3 EXITS", "US 6 / 85  VASQUEZ BLVD")]
    for i, (l1, l2) in enumerate(gantries):
        y0 = size // 2 + i * (size // 8)
        img[y0 + 4:y0 + size // 8 - 4, 4:-4] = np.array([0.06, 0.27, 0.14])
        img[y0 + 6:y0 + size // 8 - 6, 6:10] = 0.9
        img[y0 + 6:y0 + size // 8 - 6, -10:-6] = 0.9
        draw_text_centered(img, y0 + size // 24, l1, 4, (0.95, 0.95, 0.95))
        draw_text_centered(img, y0 + size // 10, l2, 3, (0.95, 0.95, 0.95))
        manifest[f"gantry{i}"] = rect_uv(0, y0, size, size // 8)

    # start/finish banner with checkered top/bottom edges
    y0 = size - size // 8
    img[y0:, :] = np.array([0.10, 0.10, 0.12])
    chk = (((np.arange(size) // 16)[:, None] + (np.arange(size) // 16)[None, :]) % 2)[:16, :, None] > 0
    img[y0:y0 + 16] = np.where(chk, 0.95, 0.05)
    img[size - 16:] = np.where(chk, 0.95, 0.05)
    draw_text_centered(img, y0 + size // 16, "SAND CREEK RACEWAY", 5, (0.95, 0.95, 0.95))
    manifest["banner"] = rect_uv(0, y0, size, size // 8)
    return to_u8(img), manifest


def tex_tires(seed: int, size: int = 256) -> np.ndarray:
    """Stacked-tire wall wrap: dark rubber rings (V = one tire course per quarter)."""
    r = _rng(seed, "tires")
    vv = np.linspace(0, 4 * np.pi * 2, size)[:, None]
    ring = 0.16 + 0.10 * np.maximum(0, np.sin(vv))
    lum = ring + (fbm(r, size, base=24, octaves=2) - 0.5) * 0.05
    return to_u8(np.repeat(lum, 3, axis=-1).reshape(size, size, 3) * np.array([1.0, 1.0, 1.05]))


def tex_horizon(seed: int, w: int = 2048, h: int = 512) -> np.ndarray:
    """RGBA 360° backdrop ring: Front Range silhouette to the west, downtown blocks to the SW,
    low industrial haze elsewhere. U = azimuth/360 (0 = north, clockwise via atan2(x,z))."""
    r = _rng(seed, "horizon")
    az = np.linspace(0, 360, w, endpoint=False)

    def noise1d(name: str, base: int) -> np.ndarray:
        row = fbm(_rng(seed, name), 1024, base=base, octaves=5, gain=0.55)[0]
        return np.interp(np.linspace(0, 1023, w), np.arange(1024), row)

    def ridged(n: np.ndarray) -> np.ndarray:            # peaks instead of domes
        return 1.0 - np.abs(2.0 * n - 1.0)

    def sector(center, width):
        d = np.minimum(np.abs(az - center), 360 - np.abs(az - center))
        return np.clip(1 - d / width, 0, 1)

    mtn = sector(272, 62) ** 0.55                        # Front Range: due west, wide
    peaks = ridged(noise1d("hz_peaks", 28))
    rolling = noise1d("hz_roll", 10)
    far_ridge = 0.05 + 0.03 * rolling + mtn * (0.10 + 0.42 * peaks)
    near_ridge = 0.03 + 0.02 * rolling + sector(268, 40) * (0.05 + 0.16 * ridged(noise1d("hz_p2", 48)))
    yy = np.linspace(1, 0, h)[:, None]                   # 1 at top row
    sil_far = yy < far_ridge[None, :]
    sil_near = yy < near_ridge[None, :]
    rgb = np.zeros((h, w, 3), np.float32)
    haze = np.array([0.63, 0.68, 0.76])
    mtn_col = np.array([0.46, 0.53, 0.65])
    col = haze * (1 - mtn[None, :, None]) + mtn_col * mtn[None, :, None]
    fade = np.clip(yy / np.maximum(far_ridge[None, :], 1e-3), 0, 1)
    rgb[:] = col * (1.0 - 0.22 * fade[..., None])
    # snow above ~82% of each peak, west range only
    snow = sil_far & (yy > far_ridge[None, :] * 0.82) & (mtn[None, :] > 0.45) & (peaks[None, :] > 0.55)
    rgb[snow] = np.array([0.88, 0.90, 0.94])
    rgb[sil_near] = np.array([0.50, 0.56, 0.62])         # darker foothill band in front
    sil = sil_far | sil_near
    # downtown Denver: tower cluster SSW
    for i in range(12):
        cx = int((212 + r.uniform(-6.5, 6.5)) / 360 * w)
        bw = int(r.integers(5, 14))
        bh = float(r.uniform(0.07, 0.17))
        tower = (np.abs(np.arange(w) - cx) < bw)[None, :] & (yy < bh)
        rgb[tower] = np.array([0.49, 0.54, 0.62]) * float(r.uniform(0.9, 1.08))
        sil = sil | tower
    alpha = sil.astype(np.float32) * 0.92
    # soften the top edge
    edge = sil & (yy > (np.maximum(far_ridge, near_ridge)[None, :] - 0.012))
    alpha[edge] *= 0.55
    return np.dstack([to_u8(rgb), (alpha * 255).astype(np.uint8)])


def tex_solid(seed: int, name: str, color: tuple[float, float, float],
              size: int = 64, noise: float = 0.05) -> np.ndarray:
    """Near-solid utility texture (paint, dark steel, lamp lens…) with a whisper of noise."""
    r = _rng(seed, name)
    lum = 1.0 + (fbm(r, size, base=8, octaves=2) - 0.5) * noise * 2
    return to_u8(np.stack([np.clip(color[i] * lum, 0, 1) for i in range(3)], axis=-1))


# ---------------------------------------------------------------- main

def generate(project_dir: str | Path) -> dict:
    project_dir = Path(project_dir)
    cfg = json.loads((project_dir / "track.config.json").read_text(encoding="utf-8"))
    env = cfg.get("environment", {})
    seed = int(env.get("seed", 10))
    roads = cfg.get("route", {}).get("roads", [])
    out = Path(__file__).resolve().parents[2] / "assets" / "textures" / "generated"
    out.mkdir(parents=True, exist_ok=True)

    manifest: dict = {"seed": seed, "atlas": {}}
    d, n = tex_road(seed)
    write_png(out / "road_diffuse.png", d)
    write_png(out / "road_normal.png", n)
    write_png(out / "road_wear.png", tex_wear(seed))
    d, n = tex_kerb(seed)
    write_png(out / "kerb_diffuse.png", d)
    write_png(out / "kerb_normal.png", n)
    d, n = tex_grass(seed)
    write_png(out / "grass_diffuse.png", d)
    write_png(out / "grass_normal.png", n)
    write_png(out / "gravel_diffuse.png", tex_dirt(seed))
    d, n = tex_concrete(seed)
    write_png(out / "concrete_diffuse.png", d)
    write_png(out / "concrete_normal.png", n)
    # facade variant library — per-zone building looks (downloads composited when cached)
    fac_counts = {"ind": len(INDUSTRIAL_BASES), "com": len(COMMERCIAL_BASES),
                  "off": len(OFFICE_BASES), "res": 1}
    for i in range(fac_counts["ind"]):
        d, n = tex_facade_industrial_v(seed, i)
        write_png(out / f"fac_ind_{i}.png", d)
        write_png(out / f"fac_ind_{i}_n.png", n)
    for i in range(fac_counts["com"]):
        d, n = tex_facade_commercial_v(seed, i)
        write_png(out / f"fac_com_{i}.png", d)
        write_png(out / f"fac_com_{i}_n.png", n)
    for i in range(fac_counts["off"]):
        d, n = tex_facade_office_v(seed, i)
        write_png(out / f"fac_off_{i}.png", d)
        write_png(out / f"fac_off_{i}_n.png", n)
    d, n = tex_facade_residential_v(seed)
    write_png(out / "fac_res_0.png", d)
    write_png(out / "fac_res_0_n.png", n)
    manifest["facades"] = fac_counts
    d, n = tex_roof(seed)
    write_png(out / "roof_flat.png", d)
    write_png(out / "roof_flat_n.png", n)
    write_png(out / "fence_chain.png", tex_fence(seed))
    write_png(out / "guardrail.png", tex_guardrail(seed))
    write_png(out / "pole_steel.png", tex_pole_steel(seed))
    write_png(out / "pole_wood.png", tex_pole_wood(seed))
    d, n = tex_tank(seed)
    write_png(out / "tank_metal.png", d)
    write_png(out / "tank_metal_n.png", n)
    write_png(out / "tree_atlas.png", tex_tree_atlas(seed))
    d, m = tex_signs(seed, roads)
    write_png(out / "signs_atlas.png", d)
    manifest["atlas"]["signs"] = m
    d, m = tex_adboards(seed)
    write_png(out / "adboards.png", d)
    manifest["atlas"]["ads"] = m
    write_png(out / "tirewall.png", tex_tires(seed))
    write_png(out / "horizon.png", tex_horizon(seed))
    write_png(out / "paint_white.png", tex_solid(seed, "pw", (0.92, 0.92, 0.88)))
    write_png(out / "paint_yellow.png", tex_solid(seed, "py", (0.86, 0.62, 0.08)))
    write_png(out / "steel_dark.png", tex_solid(seed, "sd", (0.16, 0.16, 0.18)))
    write_png(out / "lamp_warm.png", tex_solid(seed, "lw", (0.98, 0.88, 0.55), noise=0.02))
    write_png(out / "water_calm.png", tex_solid(seed, "wc", (0.10, 0.17, 0.21), size=256, noise=0.12))

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    pngs = sorted(p.name for p in out.glob("*.png"))
    return {"out": str(out), "count": len(pngs), "textures": pngs}


def main() -> None:
    argv = sys.argv
    if "--" in argv:                       # blender --background --python texgen.py -- <dir>
        project_dir = argv[argv.index("--") + 1]
    elif len(argv) > 1:
        project_dir = argv[1]
    else:
        raise SystemExit("usage: [blender --background --python] texgen.py [--] <project-dir>")
    info = generate(project_dir)
    print(f"[texgen] wrote {info['count']} textures -> {info['out']}")


if __name__ == "__main__":
    main()
