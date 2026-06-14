"""Fetch the pinned CC0 building-material set from ambientCG into assets/textures/downloads/.

The facade factory in ``texgen.py`` composites real scanned materials (corrugated steel
colourways, tilt-up concrete, brick, plaster, multi-storey glass facades) with procedural
doors/docks/storefronts/sign-bands to build the per-zone building variant library. Everything
here is CC0 (https://docs.ambientcg.com/license/); the set is PINNED so builds stay
reproducible. Cached and gitignored — texgen falls back to fully-procedural bases when a
download is missing, so offline builds still work.

Run:  python3 -m scripts.ac.fetch_textures            # downloads anything missing
      python3 -m scripts.ac.fetch_textures --force    # re-download all
"""

from __future__ import annotations

import io
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

USER_AGENT = "prodrive-ac-builder/0.1 (https://github.com/k10-motorsports/prodrive-ac-builder)"
URL = "https://ambientcg.com/get?file={aid}_1K-JPG.zip"

# pinned CC0 set — (ambientCG asset id, role used by texgen's facade factory)
ASSETS = [
    ("CorrugatedSteel007A", "industrial corrugated, pale"),
    ("CorrugatedSteel006A", "industrial corrugated, light grey"),
    ("CorrugatedSteel005",  "industrial corrugated, blue-grey"),
    ("CorrugatedSteel002",  "industrial corrugated, weathered"),
    ("Concrete034",         "tilt-up concrete panel"),
    ("Concrete046",         "tilt-up concrete panel, smooth"),
    ("Bricks051",           "commercial brick, red"),
    ("Bricks097",           "commercial brick, varied"),
    ("Bricks060",           "commercial brick, tan"),
    ("PaintedPlaster006",   "strip-mall stucco"),
    ("PaintedPlaster017",   "strip-mall stucco, warm"),
    ("Facade001",           "office glass facade"),
    ("Facade018A",          "office facade, panels"),
    ("Facade006",           "office facade, mixed"),
]

WANTED_SUFFIXES = ("_Color.jpg", "_NormalDX.jpg")


def download_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "textures" / "downloads"


def fetch(force: bool = False) -> dict:
    out = download_dir()
    out.mkdir(parents=True, exist_ok=True)
    got, skipped, failed = [], [], []
    for aid, role in ASSETS:
        targets = [out / f"{aid}{suf}" for suf in WANTED_SUFFIXES]
        if all(t.exists() for t in targets) and not force:
            skipped.append(aid)
            continue
        try:
            req = urllib.request.Request(URL.format(aid=aid), headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                blob = resp.read()
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                for name in zf.namelist():
                    for suf in WANTED_SUFFIXES:
                        if name.endswith(suf):
                            (out / f"{aid}{suf}").write_bytes(zf.read(name))
            got.append(aid)
            time.sleep(0.5)  # be polite
        except Exception as exc:  # offline / asset renamed — texgen falls back to procedural
            failed.append(f"{aid} ({exc})")
    return {"downloaded": got, "cached": skipped, "failed": failed, "dir": str(out)}


def main() -> None:
    info = fetch(force="--force" in sys.argv)
    print(f"[fetch_textures] -> {info['dir']}")
    print(f"  downloaded: {len(info['downloaded'])}  cached: {len(info['cached'])}")
    for f in info["failed"]:
        print(f"  FAILED: {f}")
    if info["failed"]:
        print("  (texgen will fall back to procedural bases for missing assets)")


if __name__ == "__main__":
    main()
