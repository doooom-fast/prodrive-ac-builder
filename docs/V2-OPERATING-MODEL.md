# V2 Operating Model — Claude as orchestrator

v1 tried to be an anywhere-machine and finished nothing (`V1-AUTOPSY.md`). v2 is a **studio
process**: Claude orchestrates a curated toolbox per location, Kevin is the ground truth, and
every claim carries an artifact. One size does not fit all — the *research* decides what each
build needs.

## Roles

- **Kevin** — owner. Approves dossiers, build plans, spending, deletions, gate changes. Runs the
  Windows drive tests. His report is the only thing that closes a loop.
- **Claude (orchestrator session)** — researches, plans, selects tools, runs builds/gates, keeps
  `STATE.md` truthful, hands off zips, never self-certifies.

## The per-location cycle

### Phase R — Research → `projects/<slug>/dossier.md`
Use `templates/LOCATION-DOSSIER.md`. Sources: aerial + Street View/Mapillary imagery, OSM tags,
county GIS/zoning, USGS 3DEP, Kevin's capture footage & drive recordings (`/simracing` in
Dropbox), LiDAR scans, and the owned 3D asset library (`ASSET-LIBRARY.md`). Output: per-street
geometry facts, the *character* of the place (buildings, vegetation, backdrop, light), the asset
plan (owned model → placement, or gap → purchase candidate with price), and location-specific QA
criteria. **Kevin reviews the dossier before any geometry is built** — disagreements are fixed
in text, not in meshes.

### Phase P — Build plan (in the dossier, short)
Which toolbox pieces run, in what order, with which config; what bespoke work this location
needs; which gates apply with which thresholds; what the next drive test must answer.

### Phase B — Build (Mac, scripted)
`./scripts/build.sh projects/<slug> [stage]`. Gate results append to
`data/gate_history.jsonl` — never overwrite-only. Commit intermediates worth keeping
(centerline, heightfield) so builds are resumable and diffs reviewable.

### Phase H — Handoff
Zip + a short handoff note in `STATE.md`: what changed, what the drive test should probe,
known-open items. Nothing in the note may claim beyond its DoD tier.

### Phase D — Drive test (Windows, Kevin, ~5–15 min)
`templates/DRIVE-TEST-REPORT.md`: install result, laps, worst 3 spots with corner refs +
screenshots, per-asset look verdicts when relevant. Screen recordings welcome (they were
already being made in v1 — Jul 9/11 — but nothing consumed them; now they land in the report).

### Phase I — Iterate
One session per defect class from the report. Fix → regression test → gates → next handoff.
The cycle repeats until DoD tiers advance. Sessions that discover scope creep park it in
`STATE.md → Next`, not in code.

## Session protocol (mechanics)

- Open: read `STATE.md` + latest drive-test report; state the session goal.
- Work: smallest change that advances the goal; respect CLAUDE.md rules 1–8.
- Close: gates run; branch pushed; `STATE.md` updated (Verified / Claimed-awaiting-test / Next);
  honest close-out sentence. A session that only researched still lands its dossier text.

## Verification policy

- **Tiered DoD** (`DEFINITION-OF-DONE.md`): T0 builds → T1 gates pass → T2 installs & loads →
  T3 Kevin drives clean laps → T4 AI line + minimap + preview → T5 license-clean release.
  A tier is claimed only with its artifact linked in `STATE.md`.
- **Gates**: pre-checks, not truth. Changes to thresholds/bypasses require a
  `GATES-CHANGELOG.md` entry with Kevin's sign-off. Existing bypass env vars
  (`GATE_CONTACT_ADVISORY`, `GATE_EXCURSIONS_ADVISORY`) are scheduled for removal (backlog #3).
- **CI** (`.github/workflows/tests.yml`): `python tests/run_tests.py` on every push/PR — the
  first machine check this repo has ever had. Keep it green; it runs in seconds.

## Assets (Kevin's conditions, encoded)

**Personal use only — distribution is a non-goal** (Kevin, 2026-08-10). That unlocks full
kitbashing: mine and adapt anything that makes a location look right — the Dropbox `/Blender`
library (`ASSET-LIBRARY.md`: barriers, US traffic signs, street lamps, pylons, containers,
modular buildings, fences, poplar/pine trees, 4K PBR sets, HDRI sky), the
`/simracing/mods archive`, assets extracted from installed mods via `scripts/modkit`, purchased
packs. No license ledger, no gate. The one honesty rule: generated credits files stop claiming
"all CC0" when it isn't true — generated docs don't lie (backlog #4).

**Proof before purchase** (unchanged): take 2–3 owned models (recommended: Concrete Barrier
4 MTS, traffic-sign pack, a street lamp) end-to-end — convert (scale-to-meters, Y-up, PBR→AC
material via `pbr.py`, power-of-two, EXR→PNG/DDS), place at Sand Creek, Kevin verdicts "looks
good in game" in a drive-test report. **Only after that proof does Kevin start paying for
assets**, from dossier gap-lists with store links and prices he approves.

## Cost controls

- Research and planning happen in cheap text phases; expensive build/iterate sessions run only
  against an approved plan with a named goal.
- Cache/commit intermediates; never re-derive the world to tweak a kerb (resume by stage).
- Two failed attempts at the same defect in one session → stop, write findings to `STATE.md`,
  end the session. A fresh scoped session beats a spiral.
- Big binaries stay out of sessions' way: nothing reads `tracks/` or `assets/` wholesale; the
  36k-line capture JSON is data, not reading material.

## V2 backlog (session #1 onward, in order)

1. **Prove the Sand Creek kn5 in-game** (autopsy §7 step 1) — the open question that ends the
   "does the exporter even work" ambiguity. One Kevin evening + one session.
2. Reproducible rebuild + committed intermediates + `gate_history.jsonl` baseline.
3. Gate hardening: delete bypass env vars; make `build_network.sh`'s inline 2-of-9 audit call
   the real module (or park the network path entirely); wire `render_drive_views.py` into the
   build as an artifact for drive-test prep.
4. Owned-asset proof (§Assets) → then Kevin's first purchases. Same pass: stop emitting the
   false "all CC0" credits text from the pack stage (honesty fix, not a legal one).
5. Drive-test iteration to T3, then T4 (AI line evening), then polish to T5.
6. Refactor debt *as needed by the above, not speculatively*: split `build_mesh.build()` (1,739
   lines) along its stage seams the first time a change requires touching it.
7. Deletions with Kevin's approval: orphan files (autopsy §4 list), `scs` stubs, or their
   explicit PARKED retention. (`modkit` is revived — it's the kitbash miner.)
8. Lake Murray dossier — only after Sand Creek T3.
