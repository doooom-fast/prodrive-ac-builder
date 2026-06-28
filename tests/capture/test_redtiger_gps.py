"""Decode of REDTIGER (YOUQING/Novatek) dashcam freeGPS blocks — scripts/capture/redtiger_gps.

Builds a synthetic freeGPS block (the real on-card layout, reverse-engineered + validated against the
burned-in stamp) so the parser is covered without the 800 MB source file. Plain tempfile + asserts for
tests/run_tests.py under the no-numpy system python.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from scripts.capture import redtiger_gps as rg


def _block(lat_ddmm, lon_ddmm, ns=b"N", ew=b"W", hms=(10, 33, 16), md=(4, 10)) -> bytes:
    b = bytearray(0xE0)
    b[0:8] = b"freeGPS "
    struct.pack_into("<I", b, 8, 0x90)
    b[12:22] = b"YOUQINGGPS"
    struct.pack_into("<f", b, rg.LAT_OFF, lat_ddmm)        # +36 latitude
    struct.pack_into("<f", b, rg.LON_OFF, lon_ddmm)        # +40 longitude
    b[68:71] = b"A" + ns + ew                              # fix-valid + hemispheres
    h, mi, s = hms
    mo, d = md
    struct.pack_into("<III", b, 76, h, mi, s)             # time before the year anchor (ya-12)
    b[88:92] = rg.YEAR_LE                                  # 0x000007EA = 2026
    struct.pack_into("<II", b, 92, mo, d)                 # month, day after (ya+4)
    return bytes(b)


def _write(blocks: list[bytes]) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    f.write(b"\x00" * 64)                                  # leading filler (real files have mdat header)
    for blk in blocks:
        f.write(blk)
        f.write(b"\x11" * 32)                              # inter-block filler
    f.close()
    return f.name


def test_decodes_denver_fix():
    # 39.7400 N, 105.0400 W in DDDmm.mmmm  => 3944.40 / 10502.40
    path = _write([_block(3944.40, 10502.40)])
    fixes = rg.parse_fixes(path)
    assert len(fixes) == 1
    f = fixes[0]
    assert abs(f["lat"] - 39.7400) < 1e-3, f["lat"]
    assert abs(f["lon"] - (-105.0400)) < 1e-3, f["lon"]    # West => negative
    assert f["t"] == "2026-04-10T10:33:16"


def test_hemispheres_and_speed_from_motion():
    a = _block(3944.40, 10502.40, hms=(10, 0, 0))
    b = _block(3944.40, 10503.40, hms=(10, 0, 1))          # +1 min of longitude in 1 s
    fixes = rg.parse_fixes(_write([a, b]))
    assert len(fixes) == 2
    assert fixes[0]["speed_kmh"] == 0.0                    # first fix has no prior
    assert fixes[1]["speed_kmh"] > 0.0                     # derived from the eastward step
    # southern/eastern hemisphere signs
    s = rg.parse_fixes(_write([_block(3944.40, 10502.40, ns=b"S", ew=b"E")]))[0]
    assert s["lat"] < 0 and s["lon"] > 0


def test_no_blocks_returns_empty():
    # an exported clip with the freeGPS stripped → no fixes (not a crash)
    f = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    f.write(b"\x00\x11\x22" * 5000)
    f.close()
    assert rg.parse_fixes(f.name) == []


def test_gpx_roundtrips():
    fixes = rg.parse_fixes(_write([_block(3944.40, 10502.40)]))
    gpx = rg.to_gpx(fixes)
    assert gpx.startswith("<?xml") and "<trkpt" in gpx
    assert 'lat="39.7399' in gpx and 'lon="-105.0400' in gpx   # float32 precision of 39.7400 / -105.0400
    assert "2026-04-10T10:33:16Z" in gpx
