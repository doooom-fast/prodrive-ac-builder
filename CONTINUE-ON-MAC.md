# Handoff: continue this work in a local Claude session on the Mac

This file is the bridge between the cloud session where this work started and a fresh `claude`
session on your Mac. The chat transcript doesn't transfer — this captures the state so a local agent
(and you) can pick up cold. Read this first, then `git log` the branch.

**Branch:** `claude/ac-track-gen-plugin-7j2qme` · **PR:** #8 (draft)

---

## The pivot (why we're here)

Reframe the project from a Mac→PC track-build pipeline into a **local, Mac-native generator** aimed
at a future **Content Manager plugin**: user brings a Claude API key + a KML + their installed
mods/AC assets; an **agentic loop driven by the skills** generates a track and dresses it by
kitbashing the user's own installed assets. Generation stays **local-only** (nothing redistributed;
users are advised not to share generated tracks), so mining installed mods for the parts-bin is fair.

Quality north star is "drivable, real, and densely dressed" (Adenau / LA Canyons / SRP as
aspiration, **not** a literal match — those are multi-year hand-built projects; our lever is
asset-reuse density, not bespoke modelling).

Decisions already made (don't re-litigate):
- First spike = **Wine preview bottle** (kill the PC round-trip). ✅ landed.
- Claude invocation = **agentic loop with skills** (not deterministic-only). (Not built yet.)
- "Run on my Mac" scope = **whole pipeline + local Claude**. Bootstrap landed.
- Blender = a removable *host*, not an algorithm → **bpy-free exporter**. ✅ landed.

---

## What's landed on this branch

1. **Wine-bottle preview** — `scripts/preview/bottle.py`, `scripts/preview/README.md`,
   `tests/preview/test_bottle.py`. Discovers CrossOver/Whisky/Wine bottles + the AC install in each;
   installs a built track; quick-drives via `acs.exe`. Mac-native except the launch.
2. **bpy-free kn5 exporter** — `scripts/ac/kn5_export.py`, `tests/ac/test_kn5_export.py`. Pure-Python
   OBJ→kn5; proven by round-trip through `scripts/modkit/extract_kn5.py`. The pipeline no longer
   needs Blender.
3. **Mac bootstrap** — `scripts/bootstrap_mac.sh`, `RUNNING-ON-MAC.md`.

Tests: **101 passed, 0 failed**; ruff clean. (Run `python tests/run_tests.py`.)

---

## What still needs the Mac (the reason the PR is a draft)

None of this can run in CI/cloud — AC is a paid Windows game under Wine. Validate in order:

1. `./scripts/bootstrap_mac.sh` succeeds (watch the rasterio/GDAL step).
2. Build + install + drive:
   ```bash
   source .venv/bin/activate
   python -m scripts.ac.kn5_export projects/sand-creek-raceway
   python -m scripts.preview.bottle --list
   python -m scripts.preview.bottle sand-creek-raceway --drive
   ```
3. **Staged bottle validation** (see `scripts/preview/README.md`): vanilla AC → Content Manager →
   CSP. CSP-under-Wine is the fragile rung — the go/no-go for full-fidelity preview.
4. **kn5 in-AC visual checks** (the exporter can't self-verify these): UV V-orientation (textures
   upside-down → flip with `--no-flip-uv`), shader-property lighting (materials too dark → revisit
   `DEFAULT_SHADER_PROPS` in `kn5_export.py`), dummy facing (AC_START/AC_PIT orientation).

Capture what breaks at each step — that's the next session's input.

---

## Next bet (not started)

**Installed-mods asset indexer** — scan the bottle's
`…/assettocorsa/content/{cars,tracks}` (and extract via `scripts/modkit/extract_kn5.py`) into a
searchable parts-bin so the agentic loop can place density. Local-only; reference, never bake-and-ship.

Then: the agentic generation loop, and the CM plugin shell (thin front-end → Python pipeline).

---

## Starting the local session

```bash
git fetch origin claude/ac-track-gen-plugin-7j2qme
git checkout claude/ac-track-gen-plugin-7j2qme
claude        # fresh local session; point it at this file first
```

The cloud session remains subscribed to PR #8 (wakes on review comments + hourly re-check). If you
continue locally instead, that's fine — just tell the cloud session to stop, or let it idle out.
