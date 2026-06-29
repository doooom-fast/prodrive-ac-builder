"""Preview-bottle units: bottle discovery, AC-in-bottle location, layout + race.ini generation.

Pure-Python (tempfile, no pytest fixtures) so it runs under both ``tests/run_tests.py`` and pytest.
The actual Wine launch is not exercised here — only the file/path logic that runs Mac-native.
"""

import os
import tempfile
from pathlib import Path

from scripts.ac.install import BuiltTrack
from scripts.preview import bottle


# --- helpers -------------------------------------------------------------------

def _make_ac(drive_c: Path, *, with_cm=False, with_docs=False, user="crossover") -> Path:
    """Lay down a fake Steam AC install (+ optional CM / user docs) inside a prefix's drive_c."""
    ac_root = drive_c / "Program Files (x86)" / "Steam" / "steamapps" / "common" / "assettocorsa"
    (ac_root / "content" / "tracks").mkdir(parents=True, exist_ok=True)
    (ac_root / "acs.exe").write_bytes(b"MZ")
    if with_cm:
        (ac_root / "Content Manager.exe").write_bytes(b"MZ")
    if with_docs:
        (drive_c / "users" / user / "Documents" / "Assetto Corsa").mkdir(parents=True, exist_ok=True)
    return ac_root


def _crossover_bottle(home: Path, name: str) -> Path:
    """Create a CrossOver bottle skeleton under a fake HOME and return its drive_c."""
    dc = home / "Library" / "Application Support" / "CrossOver" / "Bottles" / name / "drive_c"
    dc.mkdir(parents=True, exist_ok=True)
    return dc


# --- bottle discovery ----------------------------------------------------------

def test_find_bottles_crossover():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        _crossover_bottle(home, "AC")
        _crossover_bottle(home, "Other")
        bottles = bottle.find_bottles(home)
        names = {b.name for b in bottles}
        assert names == {"AC", "Other"}
        assert all(b.kind == "crossover" for b in bottles)
        assert all(b.drive_c.name == "drive_c" for b in bottles)


def test_find_bottles_env_override(monkeypatch=None):
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        prefix = home / "custom-prefix"
        (prefix / "drive_c").mkdir(parents=True)
        old = os.environ.get("AC_BOTTLE")
        os.environ["AC_BOTTLE"] = str(prefix)
        try:
            bottles = bottle.find_bottles(home)
        finally:
            if old is None:
                os.environ.pop("AC_BOTTLE", None)
            else:
                os.environ["AC_BOTTLE"] = old
        assert any(b.kind == "custom" and b.drive_c == prefix / "drive_c" for b in bottles)


def test_find_bottles_dedups_same_drive_c():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        dc = _crossover_bottle(home, "AC")
        old = os.environ.get("AC_BOTTLE")
        os.environ["AC_BOTTLE"] = str(dc.parent)  # same prefix via env + crossover scan
        try:
            bottles = bottle.find_bottles(home)
        finally:
            if old is None:
                os.environ.pop("AC_BOTTLE", None)
            else:
                os.environ["AC_BOTTLE"] = old
        resolved = [os.path.normcase(str(b.drive_c.resolve())) for b in bottles]
        assert len(resolved) == len(set(resolved)), "drive_c should be de-duplicated"


# --- AC inside a bottle --------------------------------------------------------

def test_ac_in_bottle_found_with_cm_and_docs():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        dc = _crossover_bottle(home, "AC")
        ac_root = _make_ac(dc, with_cm=True, with_docs=True)
        b = bottle.Bottle("AC", dc.parent, dc, "crossover", None)
        ac = bottle.ac_in_bottle(b)
        assert ac is not None
        assert ac.ac_root == ac_root
        assert ac.acs_exe == ac_root / "acs.exe"
        assert ac.cm_exe == ac_root / "Content Manager.exe"
        assert ac.docs_dir == dc / "users" / "crossover" / "Documents" / "Assetto Corsa"
        assert ac.tracks_dir == ac_root / "content" / "tracks"


def test_ac_in_bottle_absent():
    with tempfile.TemporaryDirectory() as td:
        dc = Path(td) / "drive_c"
        dc.mkdir()
        b = bottle.Bottle("empty", dc.parent, dc, "custom", None)
        assert bottle.ac_in_bottle(b) is None


def test_ac_in_bottle_no_docs_is_none():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        dc = _crossover_bottle(home, "AC")
        _make_ac(dc, with_docs=False)
        ac = bottle.ac_in_bottle(bottle.Bottle("AC", dc.parent, dc, "crossover", None))
        assert ac is not None and ac.docs_dir is None


def test_discover_bottle_acs_endtoend():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        dc = _crossover_bottle(home, "AC")
        _make_ac(dc, with_docs=True)
        _crossover_bottle(home, "NoGame")  # bottle without AC is skipped
        acs = bottle.discover_bottle_acs(home)
        assert len(acs) == 1 and acs[0].bottle.name == "AC"


# --- quick-race cfg + layout ---------------------------------------------------

def test_quick_race_ini_contents():
    ini = bottle.quick_race_ini("sand_creek_raceway", "full", car="ks_mazda_miata")
    assert "TRACK=sand_creek_raceway" in ini
    assert "CONFIG_TRACK=full" in ini
    assert "MODEL=ks_mazda_miata" in ini
    assert "TYPE=1" in ini  # practice session


def test_write_quick_race_creates_cfg():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        dc = _crossover_bottle(home, "AC")
        _make_ac(dc, with_docs=True)
        ac = bottle.ac_in_bottle(bottle.Bottle("AC", dc.parent, dc, "crossover", None))
        race = bottle.write_quick_race(ac, "sand_creek_raceway", "full")
        assert race.is_file() and race.name == "race.ini"
        assert "TRACK=sand_creek_raceway" in race.read_text()


def test_write_quick_race_without_docs_raises():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        dc = _crossover_bottle(home, "AC")
        _make_ac(dc, with_docs=False)
        ac = bottle.ac_in_bottle(bottle.Bottle("AC", dc.parent, dc, "crossover", None))
        try:
            bottle.write_quick_race(ac, "x", "full")
            raise AssertionError("expected FileNotFoundError when no user-docs dir")
        except FileNotFoundError:
            pass


def _track(slug="t", layouts=("full", "interior")) -> BuiltTrack:
    return BuiltTrack(slug=slug, name=slug, folder=Path("/x"), kn5=None, layouts=list(layouts))


def test_layout_for_defaults_to_first():
    assert bottle._layout_for(_track(), None) == "full"


def test_layout_for_respects_request():
    assert bottle._layout_for(_track(), "interior") == "interior"


def test_layout_for_no_layouts_is_empty():
    assert bottle._layout_for(_track(layouts=()), None) == ""


def test_launch_cmd_requires_runner():
    b = bottle.Bottle("AC", Path("/p"), Path("/p/drive_c"), "whisky", None)
    ac = bottle.BottleAC(b, Path("/ac"), Path("/ac/acs.exe"), None, None)
    try:
        bottle.launch_cmd(ac)
        raise AssertionError("expected FileNotFoundError without a wine runner")
    except FileNotFoundError:
        pass


def test_launch_cmd_with_runner():
    b = bottle.Bottle("AC", Path("/p"), Path("/p/drive_c"), "crossover", Path("/usr/bin/wine"))
    ac = bottle.BottleAC(b, Path("/ac"), Path("/ac/acs.exe"), None, None)
    assert bottle.launch_cmd(ac) == ["/usr/bin/wine", "/ac/acs.exe"]
