#!/usr/bin/env python3
"""Dependency-free runner for the test suite (pytest not required in this env).

The test files are plain ``test_*`` functions using ``tempfile`` (no pytest fixtures), so they run
both here and under pytest in the project's 3.11 dev env.

Usage:  python tests/run_tests.py
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    passed = failed = 0
    for f in sorted((ROOT / "tests").rglob("test_*.py")):
        mod = _load(f)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print(f"PASS {f.name}::{name}")
            except Exception:
                failed += 1
                print(f"FAIL {f.name}::{name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
