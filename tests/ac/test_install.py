"""Installer units: vdf parsing, tracks-dir normalization, discovery, and the copy/assemble step.

Pure-Python (tempfile, no pytest fixtures) so it runs under both ``tests/run_tests.py`` and pytest.
The interactive prompts and live Steam auto-detection are deliberately not exercised here.
"""

import json
import tempfile
from pathlib import Path

from scripts.ac import install


# --- helpers -------------------------------------------------------------------

def _make_track(repo: Path, project: str, slug: str, layouts=("full",), with_kn5=True) -> Path:
    """Create projects/<project>/build/<slug>/ with model inis + an optional sibling kn5."""
    project_dir = repo / "projects" / project
    (project_dir).mkdir(parents=True, exist_ok=True)
    (project_dir / "track.config.json").write_text(
        json.dumps({"name": slug.replace("_", " ").title(), "slug": slug}), encoding="utf-8")
    build = project_dir / "build" / slug
    build.mkdir(parents=True, exist_ok=True)
    for lo in layouts:
        (build / f"models_{lo}.ini").write_text(f"[MODEL_0]\nFILE={slug}.kn5\n", encoding="utf-8")
    (build / "data").mkdir(exist_ok=True)
    (build / "data" / "surfaces.ini").write_text("[SURFACE_0]\n", encoding="utf-8")
    if with_kn5:
        (build / ".." / f"{slug}.kn5").resolve().write_bytes(b"KN5\x00")
    return build


# --- libraryfolders.vdf --------------------------------------------------------

def test_parse_library_folders_new_format():
    vdf = '''"libraryfolders"
{
    "0"
    {
        "path"        "C:\\\\Program Files (x86)\\\\Steam"
    }
    "1"
    {
        "path"        "D:\\\\SteamLibrary"
    }
}'''
    paths = [str(p) for p in install._parse_library_folders(vdf)]
    assert r"C:\Program Files (x86)\Steam" in paths
    assert r"D:\SteamLibrary" in paths


def test_parse_library_folders_old_format():
    vdf = '"LibraryFolders"\n{\n\t"1"\t\t"/mnt/games/SteamLibrary"\n}'
    assert Path("/mnt/games/SteamLibrary") in install._parse_library_folders(vdf)


# --- normalize_tracks_dir ------------------------------------------------------

def test_normalize_accepts_every_level():
    with tempfile.TemporaryDirectory() as d:
        lib = Path(d)
        tracks = install._tracks_under(lib)  # <lib>/steamapps/common/assettocorsa/content/tracks
        tracks.mkdir(parents=True)
        ac_root = tracks.parent.parent          # .../assettocorsa
        content = tracks.parent                 # .../content
        steamapps = lib / "steamapps"
        for base in (tracks, content, ac_root, steamapps, lib):
            assert install.normalize_tracks_dir(base) == tracks, base

    with tempfile.TemporaryDirectory() as d:
        assert install.normalize_tracks_dir(Path(d) / "nope") is None


def test_looks_like_tracks_dir():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "tracks"
        t.mkdir()
        assert install.looks_like_tracks_dir(t)               # named 'tracks'
        other = Path(d) / "stuff"
        (other / "imola" / "ui").mkdir(parents=True)          # holds a track folder
        assert install.looks_like_tracks_dir(other)
        assert not install.looks_like_tracks_dir(Path(d) / "empty-missing")


# --- discovery -----------------------------------------------------------------

def test_discover_and_resolve():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _make_track(repo, "sand-creek-raceway", "sand_creek_raceway",
                    layouts=("full", "short"), with_kn5=True)
        _make_track(repo, "no-model-yet", "no_model_yet", with_kn5=False)
        # a build dir that isn't a track (no models_*.ini) must be ignored
        (repo / "projects" / "junk" / "build" / "junk").mkdir(parents=True)

        tracks = install.discover_tracks(repo)
        by_slug = {t.slug: t for t in tracks}
        assert set(by_slug) == {"sand_creek_raceway", "no_model_yet"}
        assert by_slug["sand_creek_raceway"].layouts == ["full", "short"]
        assert by_slug["sand_creek_raceway"].has_model
        assert not by_slug["no_model_yet"].has_model

        # resolve by slug, by hyphenated project name, and by project dir
        assert install.resolve_track("sand_creek_raceway", repo).slug == "sand_creek_raceway"
        assert install.resolve_track("sand-creek-raceway", repo).slug == "sand_creek_raceway"
        assert install.resolve_track(str(repo / "projects" / "sand-creek-raceway"), repo).slug \
            == "sand_creek_raceway"
        assert install.resolve_track("does-not-exist", repo) is None


# --- assemble_and_install ------------------------------------------------------

def test_install_copies_folder_and_injects_kn5():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _make_track(repo, "sand-creek-raceway", "sand_creek_raceway", layouts=("full", "short"))
        track = install.discover_tracks(repo)[0]
        tracks_dir = repo / "ac" / "content" / "tracks"
        tracks_dir.mkdir(parents=True)

        dest = install.assemble_and_install(track, tracks_dir)
        assert dest == tracks_dir / "sand_creek_raceway"
        assert (dest / "models_full.ini").is_file()
        assert (dest / "data" / "surfaces.ini").is_file()
        # the sibling kn5 must land *inside* the installed folder, where models_*.ini points
        assert (dest / "sand_creek_raceway.kn5").is_file()


def test_install_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _make_track(repo, "p", "trk")
        track = install.discover_tracks(repo)[0]
        tracks_dir = repo / "tracks"
        tracks_dir.mkdir()
        install.assemble_and_install(track, tracks_dir, dry_run=True)
        assert not (tracks_dir / "trk").exists()


def test_install_overwrite_requires_force():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _make_track(repo, "p", "trk")
        track = install.discover_tracks(repo)[0]
        tracks_dir = repo / "tracks"
        (tracks_dir / "trk").mkdir(parents=True)
        (tracks_dir / "trk" / "stale.txt").write_text("old", encoding="utf-8")

        try:
            install.assemble_and_install(track, tracks_dir)
            raise AssertionError("expected FileExistsError")
        except FileExistsError:
            pass

        install.assemble_and_install(track, tracks_dir, force=True)
        # a clean replace: stale files are gone, new model present
        assert not (tracks_dir / "trk" / "stale.txt").exists()
        assert (tracks_dir / "trk" / "trk.kn5").is_file()


def test_install_missing_model_gated():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _make_track(repo, "p", "trk", with_kn5=False)
        track = install.discover_tracks(repo)[0]
        tracks_dir = repo / "tracks"
        tracks_dir.mkdir()

        try:
            install.assemble_and_install(track, tracks_dir)
            raise AssertionError("expected FileNotFoundError")
        except FileNotFoundError:
            pass

        dest = install.assemble_and_install(track, tracks_dir, allow_missing_model=True)
        assert (dest / "models_full.ini").is_file()
        assert not (dest / "trk.kn5").exists()


# --- selection parsing ---------------------------------------------------------

def test_parse_selection():
    assert install._parse_selection("1", 3) == [0]
    assert install._parse_selection("1,3", 3) == [0, 2]
    assert install._parse_selection("2 1 2", 3) == [1, 0]   # dedup, order-preserving
    assert install._parse_selection("a", 3) == [0, 1, 2]
    assert install._parse_selection("all", 3) == [0, 1, 2]
    assert install._parse_selection("", 3) is None
    assert install._parse_selection("9", 3) is None         # out of range
    assert install._parse_selection("x", 3) is None
