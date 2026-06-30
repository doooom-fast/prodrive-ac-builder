"""Minimal stdlib PNG writer for tests — 8-bit RGB, no row filtering, no Pillow."""

import struct
import zlib


def _chunk(typ: bytes, data: bytes) -> bytes:
    body = typ + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def write_png(path, w: int, h: int, rows: list[bytes]) -> None:
    """``rows`` = h byte-strings, each w*3 bytes of RGB."""
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0 (None)
        raw += row
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(raw)))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def ring_image(size: int, cx: float, cy: float, radius: float, thick: float,
               fg=(120, 120, 120), bg=(180, 160, 120)) -> list[bytes]:
    """A grey asphalt ring (fg) on tan ground (bg) — a synthetic closed track."""
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            row += bytes(fg if abs(d - radius) <= thick / 2 else bg)
        rows.append(bytes(row))
    return rows
