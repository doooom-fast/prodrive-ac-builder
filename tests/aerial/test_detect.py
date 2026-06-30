"""Image-size readers (PNG + JPEG header) and the asphalt colour test."""

import struct
import tempfile
from pathlib import Path

from scripts.aerial import detect
from tests.aerial._png import ring_image, write_png


def test_image_size_png():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.png"
        write_png(p, 40, 24, [bytes([180, 160, 120]) * 40 for _ in range(24)])
        assert detect.image_size(p) == (40, 24)


def test_image_size_jpeg_header():
    # Hand-build the smallest JPEG that carries a SOF0 frame header (no scan needed for sizing).
    # SOFn frame: precision, then height (70), then width (130).
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 70, 130) + b"\x03" \
        + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" \
        + sof0 + b"\xff\xd9"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.jpg"
        p.write_bytes(jpeg)
        assert detect.image_size(p) == (130, 70)


def test_is_asphalt_separates_surface_from_dirt_and_grass():
    assert detect.is_asphalt(120, 120, 120)        # neutral grey road
    assert detect.is_asphalt(95, 100, 105)         # slightly cool grey
    assert not detect.is_asphalt(180, 160, 120)    # tan dirt (warm, saturated)
    assert not detect.is_asphalt(90, 140, 70)      # vegetation (green)
    assert not detect.is_asphalt(20, 20, 20)       # near-black (too dark = shadow)


def test_asphalt_mask_finds_the_ring():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ring.png"
        write_png(p, 80, 80, ring_image(80, 40, 40, 28, 7))
        mask, gw, gh = detect.asphalt_mask(p, step=1)
        assert (gw, gh) == (80, 80)
        on = sum(c for row in mask for c in row)
        assert on > 200          # the ring is detected
        assert not mask[40][40]  # the tan infield is not
