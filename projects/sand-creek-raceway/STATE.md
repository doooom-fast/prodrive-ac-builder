# STATE — Sand Creek Raceway (pilot #1)

> Ledger of what is VERIFIED (artifact-backed) vs CLAIMED (awaiting drive test) vs NEXT.
> Updated at the end of every session (CLAUDE.md rule 7). Seeded 2026-08-10 from the v1 audit.

**DoD tier: T0 (as of the 2026-07-01 build; unproven from today's checkout).**
**Canonical config: THIS project** (`projects/sand-creek-raceway`, v0.15.3, circuit pipeline
`./scripts/build.sh`). The Sand Creek copy inside `projects/k10-colorado` (layout[0], v0.8.1,
network pipeline) is **superseded** — do not extend it.

## Verified (artifact-backed)
- A 32.1 MB kn5 with a valid AC header exists — `tracks/sand_creek_raceway/`, built 2026-07-01
  (commit `b1b901c`). Claimed length 9,687 m, 4 pitboxes (ui_track.json).
- 171-test hermetic suite passes (`python tests/run_tests.py`).
- Real capture evidence exists: `source/realworld_capture.json` (804 KB), dashcam GPS decoding,
  Kevin's drive recordings in Dropbox `/simracing/` (Jun 23, Jul 9, Jul 11).

## NOT verified — open questions (in order)
1. **Does the Jul 1 kn5 load, render, and collide in AC?** Never attempted.
   `BUILD-ON-WINDOWS.md` (Jun 23) says a Mac-exported kn5 had invalid surfaces; PR #14 likely
   superseded that; no artifact proves either way. → v2 milestone #1.
2. Does `./scripts/build.sh projects/sand-creek-raceway` still complete from a clean checkout
   (T0 re-proof)? Front half re-derives via live Overpass/3DEP (no intermediates committed).
3. All of T2–T5: install, laps, AI line (`ai/` holds only a README), real minimap
   (placeholder `map.png`), CM preview (missing), license-clean assets (currently mined —
   NOT distributable, see `docs/V1-AUTOPSY.md` §6).

## Known defects & risks (from v1 record)
- Fall-through recurred 6× in v1; treat any recurrence as gate/test gap first, mesh bug second.
- Gate thresholds inherited loose (see `docs/GATES-CHANGELOG.md` baseline ⚠ rows).
- `data/` contains only `connectors.local.json` + `street_labels.json`; two stale handoff zips
  (14 MB + 13 MB) sit in the project dir.

## Next (v2 backlog for this track — see `docs/V2-OPERATING-MODEL.md`)
1. Kevin: install the existing Jul 1 zip/kn5 via Content Manager → first
   `DRIVE-TEST-REPORT` (even "won't load" is gold — it answers open question #1).
2. Session: reproducible rebuild; commit intermediates; start `data/gate_history.jsonl`.
3. Dossier (`docs/templates/LOCATION-DOSSIER.md`) — Commerce City industrial character +
   owned-asset plan (`docs/ASSET-LIBRARY.md`): jersey barriers, US sign pack, street lamps,
   containers, poplars.
4. Owned-asset in-game proof → unlock Kevin's asset purchases.
5. Iterate to T3 → AI-line evening (T4) → license-clean (T5).

## Session log
- 2026-08-10 — v1 autopsy + v2 reboot; this ledger seeded. (This session changed docs/process
  only — no runtime code, no rebuild.)
