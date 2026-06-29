"""Drive a generated track in Assetto Corsa inside a Mac Wine bottle — no PC round-trip.

A CrossOver / Whisky / plain-Wine bottle on the Mac holds AC (and optionally Content Manager and
CSP). This module:

  1. discovers those bottles and the AC install inside each,
  2. installs a freshly-built track into the bottle's ``content/tracks`` (reusing
     :mod:`scripts.ac.install`), and
  3. launches a quick drive by writing AC's ``cfg/race.ini`` into the bottle's user docs and
     running ``acs.exe`` through the bottle's Wine runner.

What needs Wine vs. not:
  - Discovery, install, and cfg generation are Mac-native Python — they only read/write files
    inside the bottle's ``drive_c`` and need no Wine at all (and run fine off-Mac for tests).
  - Only the final launch shells out to the Wine runner. AC itself drives well under Wine/DXVK;
    CSP (Custom Shaders Patch) is the fragile piece — see ``scripts/preview/README.md`` for the
    staged plan (vanilla AC first, CSP gated).

CLI::

    python -m scripts.preview.bottle --list                      # bottles + AC installs found
    python -m scripts.preview.bottle sand-creek-raceway          # install into the bottle
    python -m scripts.preview.bottle sand-creek-raceway --drive   # install + quick drive
    python -m scripts.preview.bottle sand-creek-raceway --drive --car ks_mazda_miata --layout full
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.ac.install import (
    BuiltTrack,
    assemble_and_install,
    discover_tracks,
    resolve_track,
)

# --- bottle discovery ----------------------------------------------------------

# CrossOver ships its own Wine; this is where the launcher binary lives on macOS.
CROSSOVER_WINE = Path(
    "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine"
)


@dataclass
class Bottle:
    """A Wine prefix that might contain an Assetto Corsa install."""

    name: str
    prefix: Path  # the WINEPREFIX (the dir that *contains* drive_c)
    drive_c: Path
    kind: str  # "crossover" | "whisky" | "wine" | "custom"
    wine: Path | None  # runner binary, if we know which one drives this prefix


def _drive_c(prefix: Path) -> Path | None:
    """The ``drive_c`` for a prefix — accepting either the prefix or drive_c itself."""
    if prefix.name == "drive_c" and prefix.is_dir():
        return prefix
    dc = prefix / "drive_c"
    return dc if dc.is_dir() else None


def _wine_on_path() -> Path | None:
    from shutil import which

    found = which("wine") or which("wine64")
    return Path(found) if found else None


def _crossover_bottles(home: Path) -> list[Bottle]:
    base = home / "Library" / "Application Support" / "CrossOver" / "Bottles"
    wine = CROSSOVER_WINE if CROSSOVER_WINE.exists() else None
    out: list[Bottle] = []
    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if (dc := _drive_c(d)):
                out.append(Bottle(d.name, d, dc, "crossover", wine))
    return out


def _whisky_bottles(home: Path) -> list[Bottle]:
    # Whisky has moved its bottle store between releases; check both known roots.
    bases = [
        home / "Library" / "Containers" / "com.isaacmarovitz.Whisky" / "Bottles",
        home / "Library" / "Application Support" / "com.isaacmarovitz.Whisky" / "Bottles",
    ]
    wine = _wine_on_path()  # Whisky bundles GPTK Wine; fall back to PATH if we can't find it
    out: list[Bottle] = []
    for base in bases:
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if (dc := _drive_c(d)):
                out.append(Bottle(d.name, d, dc, "whisky", wine))
    return out


def _plain_wine_bottles(home: Path) -> list[Bottle]:
    out: list[Bottle] = []
    wine = _wine_on_path()
    for env in ("AC_BOTTLE", "WINEPREFIX"):
        val = os.environ.get(env)
        if val and (dc := _drive_c(Path(val).expanduser())):
            out.append(Bottle(Path(val).name or env, dc.parent, dc, "custom", wine))
    default = home / ".wine"
    if (dc := _drive_c(default)):
        out.append(Bottle(".wine", default, dc, "wine", wine))
    return out


def find_bottles(home: Path | None = None) -> list[Bottle]:
    """Every Wine prefix we can spot (CrossOver, Whisky, plain Wine, ``AC_BOTTLE``/``WINEPREFIX``)."""
    home = home or Path.home()
    seen: set[str] = set()
    out: list[Bottle] = []
    for b in (
        _plain_wine_bottles(home)  # explicit env first — most trusted
        + _crossover_bottles(home)
        + _whisky_bottles(home)
    ):
        key = os.path.normcase(str(b.drive_c.resolve()))
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


# --- AC inside a bottle --------------------------------------------------------

# Default Steam libraries inside a Windows prefix, relative to drive_c.
_STEAM_AC_RELS = (
    "Program Files (x86)/Steam/steamapps/common/assettocorsa",
    "Program Files/Steam/steamapps/common/assettocorsa",
)


@dataclass
class BottleAC:
    """An Assetto Corsa install located inside a bottle, ready to install into and launch."""

    bottle: Bottle
    ac_root: Path  # .../assettocorsa
    acs_exe: Path  # acs.exe (the game)
    cm_exe: Path | None  # Content Manager.exe, if installed
    docs_dir: Path | None  # AC user-docs dir inside the prefix (cfg/ lives here)

    @property
    def tracks_dir(self) -> Path:
        return self.ac_root / "content" / "tracks"


def _ac_user_docs(drive_c: Path) -> Path | None:
    """Find the ``Documents/Assetto Corsa`` dir inside a prefix (Wine maps My Documents there)."""
    for users in (drive_c / "users",):
        if not users.is_dir():
            continue
        for user in sorted(p for p in users.iterdir() if p.is_dir()):
            for docs in ("Documents", "My Documents"):
                ac = user / docs / "Assetto Corsa"
                if ac.is_dir():
                    return ac
    return None


def _find_cm(ac_root: Path, drive_c: Path) -> Path | None:
    """Content Manager exe — beside AC, or in its AppData install location."""
    candidates = [
        ac_root / "Content Manager.exe",
        ac_root / "Content Manager Safe Mode.exe",
    ]
    for user in sorted((drive_c / "users").glob("*")) if (drive_c / "users").is_dir() else []:
        candidates.append(
            user / "AppData" / "Local" / "AcTools Content Manager" / "Content Manager.exe"
        )
    return next((c for c in candidates if c.is_file()), None)


def ac_in_bottle(bottle: Bottle) -> BottleAC | None:
    """Locate the AC install inside a bottle, if there is one."""
    for rel in _STEAM_AC_RELS:
        ac_root = bottle.drive_c / rel
        acs = ac_root / "acs.exe"
        if acs.is_file():
            return BottleAC(
                bottle=bottle,
                ac_root=ac_root,
                acs_exe=acs,
                cm_exe=_find_cm(ac_root, bottle.drive_c),
                docs_dir=_ac_user_docs(bottle.drive_c),
            )
    return None


def discover_bottle_acs(home: Path | None = None) -> list[BottleAC]:
    """All AC installs found across all discoverable bottles."""
    return [ac for b in find_bottles(home) if (ac := ac_in_bottle(b))]


# --- quick-drive cfg -----------------------------------------------------------

# Base-game Kunos car present in every AC install — a safe default to spawn in.
DEFAULT_CAR = "tatuusfa1"


def quick_race_ini(slug: str, layout: str, car: str = DEFAULT_CAR) -> str:
    """A minimal single-car practice ``race.ini`` for a track + layout.

    AC reads this from ``Documents/Assetto Corsa/cfg/race.ini`` and launches straight into a
    practice session. ``layout`` maps to ``CONFIG_TRACK`` (empty for a track with no sub-layouts)."""
    return "\n".join(
        [
            "[RACE]",
            f"TRACK={slug}",
            f"CONFIG_TRACK={layout}",
            f"MODEL={car}",
            "CARS=1",
            "AI_LEVEL=100",
            "[CAR_0]",
            "SETUP=",
            "SKIN=",
            "MODEL=-",
            "DRIVER_NAME=Preview",
            "[SESSION_0]",
            "NAME=Practice",
            "TYPE=1",  # 1 = practice
            "LAPS=0",
            "DURATION_MINUTES=0",
            "SPAWN_SET=PIT",
            "[TEMPERATURE]",
            "AMBIENT=22",
            "ROAD=28",
            "[WEATHER]",
            "NAME=3_clear",
            "[LIGHTING]",
            "SUN_ANGLE=32",
            "",
        ]
    )


def write_quick_race(ac: BottleAC, slug: str, layout: str, car: str = DEFAULT_CAR) -> Path:
    """Write the quick-drive ``race.ini`` into the bottle's AC user docs. Returns the path."""
    if ac.docs_dir is None:
        raise FileNotFoundError(
            "Could not find the AC user-docs dir inside the bottle "
            "(Documents/Assetto Corsa). Launch AC once so it creates its config, then retry."
        )
    cfg = ac.docs_dir / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    race = cfg / "race.ini"
    race.write_text(quick_race_ini(slug, layout, car), encoding="utf-8")
    return race


# --- launch --------------------------------------------------------------------

def launch_cmd(ac: BottleAC) -> list[str]:
    """The argv to launch the game through the bottle's Wine runner."""
    wine = ac.bottle.wine
    if wine is None:
        raise FileNotFoundError(
            f"No Wine runner known for bottle '{ac.bottle.name}' ({ac.bottle.kind}). "
            "Pass --wine /path/to/wine, or install CrossOver."
        )
    return [str(wine), str(ac.acs_exe)]


def drive(
    ac: BottleAC,
    slug: str,
    layout: str,
    *,
    car: str = DEFAULT_CAR,
    dry_run: bool = False,
) -> list[str]:
    """Write the quick-race cfg and launch the game. Returns the launch argv (also when dry-run)."""
    write_quick_race(ac, slug, layout, car)
    cmd = launch_cmd(ac)
    env = {**os.environ, "WINEPREFIX": str(ac.bottle.prefix)}
    if dry_run or sys.platform != "darwin":
        # Off-Mac (e.g. the build container / CI) we can't run Wine — surface the exact command.
        print("  [dry-run] would launch:")
        print(f"    WINEPREFIX={ac.bottle.prefix} \\\n      {' '.join(cmd)}")
        return cmd
    subprocess.Popen(cmd, env=env, cwd=str(ac.ac_root))  # noqa: S603 — explicit argv, no shell
    return cmd


# --- layout helpers ------------------------------------------------------------

def _layout_for(track: BuiltTrack, requested: str | None) -> str:
    """Resolve the requested layout to a real one (default: first; '' if the track has no layouts).

    AC's ``CONFIG_TRACK`` is the sub-layout folder name; ``full`` is conventional for the main one
    but a single-config track wants an empty string."""
    if requested:
        return requested
    if not track.layouts:
        return ""
    return track.layouts[0]


# --- CLI -----------------------------------------------------------------------

def _print_bottles(acs: list[BottleAC]) -> None:
    if not acs:
        print(
            "No Assetto Corsa install found in any Wine bottle.\n"
            "Looked for CrossOver / Whisky / plain-Wine prefixes with "
            "...drive_c/Program Files (x86)/Steam/.../assettocorsa/acs.exe.\n"
            "Set AC_BOTTLE=/path/to/prefix to point at a custom bottle, or see "
            "scripts/preview/README.md to create one."
        )
        return
    print("Assetto Corsa installs found in bottles:")
    for ac in acs:
        cm = "✓ CM" if ac.cm_exe else "no CM"
        docs = "✓ cfg" if ac.docs_dir else "⚠ no user-docs yet (launch AC once)"
        runner = ac.bottle.wine.name if ac.bottle.wine else "⚠ no runner"
        print(f"  • [{ac.bottle.kind}] {ac.bottle.name}")
        print(f"      ac:     {ac.ac_root}")
        print(f"      runner: {runner}   {cm}   {docs}")


def _choose_ac(acs: list[BottleAC], bottle_name: str | None) -> BottleAC | None:
    if bottle_name:
        match = next((a for a in acs if a.bottle.name == bottle_name), None)
        if not match:
            print(f"error: no bottle named '{bottle_name}'. Found: "
                  f"{', '.join(a.bottle.name for a in acs) or '(none)'}", file=sys.stderr)
        return match
    return acs[0] if acs else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prodrive-ac-preview",
        description="Install + drive a built track in Assetto Corsa inside a Mac Wine bottle.",
    )
    p.add_argument("project", nargs="?", help="project dir, name, or slug to preview")
    p.add_argument("-l", "--list", action="store_true",
                   help="list bottles + AC installs and exit")
    p.add_argument("--bottle", metavar="NAME", help="bottle to use (default: first found)")
    p.add_argument("--drive", action="store_true",
                   help="after installing, launch a quick drive")
    p.add_argument("--car", default=DEFAULT_CAR, help=f"car to spawn (default: {DEFAULT_CAR})")
    p.add_argument("--layout", help="track layout / CONFIG_TRACK (default: the track's first)")
    p.add_argument("--wine", metavar="PATH", help="override the Wine runner binary")
    p.add_argument("-f", "--force", action="store_true",
                   help="overwrite an existing install in the bottle")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would happen; copy nothing, launch nothing")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    acs = discover_bottle_acs()
    if args.wine:  # apply the override to every discovered bottle
        for ac in acs:
            ac.bottle.wine = Path(args.wine).expanduser()

    if args.list or not args.project:
        _print_bottles(acs)
        return 0 if acs else 1

    track = resolve_track(args.project)
    if not track:
        built = ", ".join(t.slug for t in discover_tracks()) or "(none built yet)"
        print(f"error: no built track matches '{args.project}'. Built: {built}", file=sys.stderr)
        return 1

    ac = _choose_ac(acs, args.bottle)
    if not ac:
        _print_bottles(acs)
        return 1

    print(f"Installing {track.slug} into bottle '{ac.bottle.name}': {ac.tracks_dir}")
    try:
        dest = assemble_and_install(track, ac.tracks_dir, dry_run=args.dry_run, force=args.force)
        print(f"  {'[dry-run] would install' if args.dry_run else '✓ installed'} → {dest}")
    except (FileExistsError, FileNotFoundError, OSError) as e:
        print(f"  ✗ {e}", file=sys.stderr)
        return 1

    if args.drive:
        layout = _layout_for(track, args.layout)
        print(f"Launching quick drive: {track.slug} / {layout or '(no layout)'} in {args.car}")
        try:
            drive(ac, track.slug, layout, car=args.car, dry_run=args.dry_run)
        except FileNotFoundError as e:
            print(f"  ✗ {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
