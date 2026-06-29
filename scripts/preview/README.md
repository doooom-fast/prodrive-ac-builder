# Mac preview bottle — drive a generated track without the PC round-trip

`scripts.preview.bottle` installs a freshly-built track into an Assetto Corsa install running
inside a Mac **Wine bottle** (CrossOver / Whisky / plain Wine) and launches a quick drive — so the
build → drive loop stays on the Mac instead of copying to a Windows box.

```
python -m scripts.preview.bottle --list                       # bottles + AC installs found
python -m scripts.preview.bottle sand-creek-raceway            # install into the bottle
python -m scripts.preview.bottle sand-creek-raceway --drive    # install + quick drive
python -m scripts.preview.bottle sand-creek-raceway --drive --car ks_mazda_miata --layout full
```

## What runs where

| Step | Needs Wine? | Notes |
|------|-------------|-------|
| Discover bottles + AC install | No | Pure file/path reads under `drive_c`. Runs anywhere (incl. CI). |
| Install track into the bottle | No | Reuses `scripts.ac.install.assemble_and_install`. |
| Write `cfg/race.ini` | No | Writes into the bottle's `Documents/Assetto Corsa/cfg/`. |
| **Launch the game** | **Yes** | Shells out to the bottle's Wine runner on `acs.exe`. macOS only. |

Off-Mac (the build container / CI) the launch step is a **dry run** that prints the exact
`WINEPREFIX=… wine …/acs.exe` command instead of executing it. The discovery, install, and cfg
logic is unit-tested in `tests/preview/test_bottle.py`.

## Staged validation plan (the actual spike)

The risk this spike retires is **"can we drive a generated track on the Mac at all, and how far up
the fidelity ladder does Wine hold?"** Validate in order — each stage is a go/no-go gate:

1. **Vanilla AC drives at all.** Steam + AC in a CrossOver bottle, no CSP. `--list` finds it,
   `--drive` spawns on the track. *Lowest risk; proves the no-PC-roundtrip thesis.* If this works
   the laborious loop is already dead.
2. **Content Manager loads.** CM in the same bottle, recognizes the installed track, quick-drives
   it. (CM is .NET; needs `dotnet`/`wine-mono` in the prefix.) Lets us drive exactly as users will.
3. **CSP renders.** Custom Shaders Patch is the **fragile** rung — it hooks DX11 hard. This is the
   one most likely to break under Wine/DXVK and the reason this is a *spike*, not a promise. If CSP
   won't cooperate, the fallback is: drive geometry/AI in vanilla AC on the Mac, keep the existing
   Blender/Eevee `preview.png` as the lighting check, and reserve CSP QA for the PC.

Record where it breaks — that result decides whether the Mac bottle is a full preview or a
geometry/drive-test tier with CSP still on the PC.

## One-time Mac setup (manual)

AC is a paid Steam title, so the bottle can't be provisioned from this repo — do it once on the Mac:

1. Install **CrossOver** (or Whisky). CrossOver's bundled Wine is at
   `/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine` (the launcher already
   looks there).
2. Create a **Windows 10** bottle, install **Steam** into it, then install **Assetto Corsa**.
3. Launch AC once so it creates `Documents/Assetto Corsa/` (the cfg dir the launcher writes into).
4. *(Optional, stages 2–3)* Install **Content Manager** and **CSP** into the same bottle.

Then point the tool at it — auto-detected for CrossOver/Whisky/`~/.wine`, or explicitly:

```
export AC_BOTTLE="$HOME/Library/Application Support/CrossOver/Bottles/AC"   # the dir holding drive_c
python -m scripts.preview.bottle --list
```

Use `--wine /path/to/wine` to override the runner (e.g. Whisky's GPTK Wine, or a custom DXVK build).

## Known follow-ups

- **`race.ini` is best-effort.** AC's quick-race format is version-sensitive and can't be tested
  off-Mac; the car/session keys may need tuning once stage 1 runs. `--car` overrides the default
  (`tatuusfa1`, a base-game Kunos car).
- **AC_START/AC_PIT orientation** carries over from the kn5 export caveat (positions exported,
  facing may need an in-game tweak).
- **Launch via CM** (instead of raw `acs.exe`) is the cleaner path once stage 2 is green — CM owns
  the preset/weather/CSP plumbing. The current launcher drives `acs.exe` directly so stage 1 needs
  nothing but vanilla AC.
