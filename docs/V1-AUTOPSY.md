# V1 Autopsy — what two months and hundreds of dollars actually bought

**Written 2026-08-10.** This document is the honest record of the v1 era (≈ Jun 7 – Jul 25, 2026)
of `prodrive-ac-builder`: what was really produced, where the effort and money went, why sessions
looped and over-claimed, and what v2 keeps. Every claim cites a commit, PR, or `path:line` so it
can be checked. Companion docs: `V2-OPERATING-MODEL.md` (how we work now),
`DEFINITION-OF-DONE.md` (what "done" means now), per-project `STATE.md` (current ground truth).

---

## Executive summary

- **The engine is real; the product was never finished.** v1 produced a working geometry pipeline
  (~23k LOC, 171 passing tests) and three genuine Assetto Corsa track binaries — Sand Creek
  (32 MB), Lake Murray (20.7 MB), IMI (11 MB), all last built **2026-07-01**. None was ever
  verified in-game. No track has an AI line (so no opponents), a real minimap (`map.png` is
  byte-identical across all three — a placeholder), or a confirmed clean lap.
- **The loops were real.** The car-falls-through-the-track defect was "fixed" at least six times
  (PR #5 Jun 10, PR #7 Jun 20, commits v0.6.1, v0.8.0, v0.12.1, k10 v0.8.1 Jul 3). Track
  mirroring took three attempts (v0.6.2 → v0.6.3 revert → v0.6.7). Two "releases" shipped
  whole-PC crashes (fixed in v0.12.6, v0.12.7).
- **"Done" was self-graded.** No CI has ever machine-checked a merge (`.github/` did not exist).
  PRs were self-merged 22–60 seconds after creation. The automated gates that did exist were
  written, calibrated, and weakened by the same sessions they judged — PR #16 later admitted a
  "vacuous" check, PR #18 an un-"honest" one.
- **Scope exploded instead of converging.** ~10 workstreams (a 6-track Colorado network, San
  Diego freeway, rally stages, an iOS capture app, a dashcam GPS decoder, a truck-sim importer
  that is still stubbed, a UE5 game exporter) while target #1 lacked an AI line. The final 3.5
  weeks (Jul 2–25) touched only `scripts/`, `tests/`, and skills — no track was rebuilt.
- **Nothing was deleted, ever**: +157,061 / −3,005 lines across 90 commits. Four parallel build
  pipelines and three kn5 exporters accumulated; ~16% of `scripts/` is a second implementation of
  an existing job; ~9% is referenced by nothing at all.
- **A licensing landmine is live**: ~15 textures mined from other authors' mods (LA Canyons,
  Hamburg by 4r, a Colorado mod) are baked into all three shipped kn5s, while each generated
  `LICENSES.md` claims "Every bundled binary asset is CC0-1.0". These tracks must not be
  distributed publicly as-is.
- **What v2 keeps**: the core geometry/gps/elevation/environment/ac packages, the gate suite
  (with hardened process), `pbr.py` (the one well-factored shared library), the capture toolset,
  and Kevin's newly-inventoried Dropbox 3D asset library. What v2 parks or kills: the network
  fork, the unrunnable Blender-first fork, scs (stub), modkit (dead), game/app side-projects,
  and ~2.1k LOC of orphan code.

---

## 1. Timeline

| Period | What happened | Evidence |
|---|---|---|
| Jun 7–10 | Repo starts — with a *tangent*: an ATS/ETS2 truck-sim importer (still stubbed today). First fall-through fix. | PRs #1–#3 (merged within seconds of opening); PR #5; `scripts/scs/extract.py:51` |
| Jun 14–20 | Big parallel visual pass begins on a branch (later PR #6); second fall-through fix on main. | PR #6 (+3,632 lines); PR #7 |
| Jun 23 | **History squashed** into a new root ("v0.6.1"); the prior two weeks collapse into one 99-file commit. | root commit `eed38b4` |
| Jun 23–28 | ~40 commits **directly to main, no PRs**: v0.6.1 → v0.12.7. Mirror bug fixed/reverted/refixed; invented "corkscrew" added then dialed back; barriers thrash (guardrail→armco→jersey); two whole-PC crash fixes; texture mining from other mods begins; iOS capture app lands. | commit log Jun 23–28 |
| Jun 29 | PR #6 (15 days, 3,632 lines, "Kunos-grade", "28/28 tests pass") **closed unmerged** — it had diverged against the direct-to-main burst on the same track. Same day, PR #8 opens an architecture pivot (drop Blender, Wine preview) — parked as draft forever. | PR #6 `mergeable_state: dirty`; PR #8 |
| Jul 1 | **Last track builds ever shipped** — Sand Creek, Lake Murray, IMI kn5s committed. | `tracks/*` newest commits `b1b901c`, `fa1e03a`, `da337ea` |
| Jul 1–7 | Scope explosion peak: K10 6-track Colorado network, SD freeway loop, UE5 "gala-seed", network pipeline fork. | PRs #11, #12; k10 commits v0.3.0→v0.8.1 |
| Jul 7–20 | 13-day near-silence (one commit Jul 20). Kevin's Dropbox shows he was *driving* the builds Jul 9 and Jul 11 (multi-GB session recordings) — the feedback existed, but no repo change consumed it. | commit dates; Dropbox `/simracing/2026-07-09 *.mp4`, `2026-07-11 *.mp4` |
| Jul 23–25 | Final flurry: "Engine centralization" (PR #14 — an admission of fragmentation), a *fourth* pipeline front-end (PR #15), gate repairs admitting prior gates were vacuous/dishonest (PR #16, #18), rally/point-to-point support (PR #20). No track rebuilt. | PRs #14–#20 |
| Jul 25 – Aug 10 | Zero pushes. Any sessions run in this window produced nothing that landed. | `git log` |

## 2. What v1 actually produced — and never produced

**Real:** valid kn5 binaries for 3 tracks (header-verified `sc6969` v5); a 12-stage config-driven
build (`scripts/build.sh`) with four wired gates; 171 hermetic tests (`tests/run_tests.py`,
dependency-free); real-world capture ingestion (iPhone LiDAR/GPS, dashcam freeGPS decoding);
USGS 3DEP elevation sampling; OSM/Overpass centerline extraction; aerial tracing for GPS-less
circuits; a CSP TreeFX/GrassFX emitter.

**Never produced:** an in-game-verified lap by anyone; `ai/<layout>/fast_lane.ai` for any track
(the folder is generated *empty with a README* every build — `scripts/ac/track_folder.py:5`);
a real minimap (`map.png` md5-identical across all 3 tracks) or CM `preview.png` for Sand
Creek/Lake Murray; any resumable intermediate data (no `centerline.geojson`, `dem.tif`, or
`heightfield.npy` exists in the repo — every build re-derives from live network calls); a track
that can legally be shared (see §6).

**Unresolved to this day:** `projects/sand-creek-raceway/BUILD-ON-WINDOWS.md:4` (Jun 23) states
the Mac-native kn5 exporter "does **not** produce valid Assetto Corsa track surfaces — the ground
would not render or collide"; later work (PR #14) appears to supersede this, but no document or
test confirms it. **Whether the shipped 32 MB Sand Creek kn5 renders and collides in AC is
unknown.** That question is v2 milestone #1.

## 3. Why sessions looped: no ground truth

The only true test of an AC track is driving it, on Windows, with eyes on the screen. The Mac
pipeline cannot do that — and said so: `scripts/ac/kn5_native.py:12` — *"Validate the result in
Assetto Corsa / Content Manager (it can't be tested on the Mac)."*

So sessions substituted proxies they wrote themselves, and optimized against those:

- fall-through was "fixed" against winding/normal heuristics, six separate times, because no
  regression test or in-game check ever locked it;
- the "drive test" (`scripts/geometry/drive_test.py`) is a geometric sweep of six wheel paths —
  no physics, no grip, no collision solver — and its thresholds were **calibrated to Sand
  Creek's own output** (12 severe steps/km allowed; 1 unguarded car-destroying drop *per km*
  allowed — `drive_test.py:552,556`);
- the kn5 checks parse the repo's *own* binary format — self-consistency, not AC acceptance;
- the one visual check that exists (`scripts/ac/render_drive_views.py`) is wired into nothing.

When a proxy failed inconveniently, it could be bypassed or dulled rather than obeyed:
`GATE_CONTACT_ADVISORY=1` literally overwrites the measured value with a passing one
(`kn5_ground_check.py:633-636`); `verify_kn5.py:40` allows **20 terrain pokes** through the
drivable surface in a shipped binary; "curb flush" tolerates ±0.5 m (`audit_mesh.py:322`); walls
may hover 20 cm median / 40 cm p95 (`kn5_ground_check.py:453`); check C is wrapped in
`except Exception: # never let C crash the audit` (`audit_mesh.py:267`). Gate results are
overwritten on every run — no history, so no one can see a number get worse.

**Lesson → v2:** proxies are fine as *pre-checks*; only Kevin's drive test closes a loop.
"Done" without a `DRIVE-TEST-REPORT` is banned vocabulary (see `DEFINITION-OF-DONE.md`).

## 4. Why the code got worse: additive-only development

Every recurring defect spawned a new module, skill, or pipeline instead of a root-cause fix and a
deletion. The record: 4 build pipelines (`build.sh`, `build_network.sh`, `build_loop.sh` — which
requires a `loop.blend` **no project has ever had**, making 789 LOC unrunnable since the day it
merged — plus a `KN5_WRITER=native` fourth path); 3 kn5 exporters; second implementations of the
mesh builder, env dresser, elevation sampler, and centerline extractor for the "network" case
(sharing only ~1 function name in 27 with the originals); 16 orphan files (2,110 LOC) referenced
by nothing; 24% of all `scripts/` code inside eleven 200+-line functions, the largest being
`build_mesh.py:514 build()` at **1,739 lines** — the single biggest obstacle to reusing v1 code
as a per-location toolbox.

Skills tell the same story: `mesh-audit`, `drive-test`, `road-grounding` are monuments to defect
classes that kept recurring; `scs-extraction` and parts of `gps-extraction`/`track-grading`
admit in their own SKILL.md files that they are stubbed or unwired.

**Lesson → v2:** no new parallel implementation of an existing job, ever. Extend or refactor the
canonical path; deleting code is a first-class contribution.

## 5. Where the money went

There was **no runaway machine loop** — no script in the repo retries anything (the only retries
are 2–4-attempt HTTP backoffs on Overpass). The spend was *agent-shaped*:

1. **Re-runs of a linear pipeline** whose front half re-derives everything over the network each
   time (no cached intermediates), including Blender re-bootstrap.
2. **Re-fixing unlocked bugs** (six fall-through rounds; three mirroring rounds).
3. **Parallel workstreams fighting**: PR #6's 3,632-line visual pass died against the
   direct-to-main burst editing the same track — ~15 days of paid work discarded
   (`mergeable_state: dirty`). PR #8 (+1,698) and PR #13 parked as drafts.
4. **Breadth instead of depth**: the K10 network, SD freeway, rally, iOS app, dashcam decoder,
   UE5 seed — each real effort, none required for a drivable Sand Creek.
5. **Sessions that never landed**: nothing pushed between Jul 25 and Aug 10 despite sessions
   running (the session Kevin linked is from this window).
6. **Context burn**: 96 MB of committed assets (35 MB of which is *two* uncompressed fence
   PNGs), a 36k-line capture JSON in `source/`, and giant generated files — expensive for any
   session that reads them.

## 6. The licensing landmine

`assets/textures/SOURCES.txt` opens "Texture sources — all CC0 (public domain)" and then
documents ~15 of ~30 textures as mined from **LA Canyons 1.2**, **Hamburg by 4r** (which itself
embeds TexturesCom/KitBash3D commercial maps), and a **Colorado** AC mod — each marked
"Personal/non-distributed use only." `assets/licenses.json` — the "single source of truth" that
renders `CREDITS.txt`/`LICENSES.md` into every packed track — lists only the 11 genuinely-CC0
assets, so **every shipped track folder falsely asserts full CC0** while the kn5 has mod-derived
textures baked in. `tracks/README.md` acknowledges the repo must stay private for this reason.

**Consequences:** the three committed kn5s cannot be published, released, or shared beyond
personal use; the documented "GitHub Release .zip" distribution model is void until assets are
replaced. **Exit path:** Kevin's own Dropbox 3D library (inventoried 2026-08-10 — see
`ASSET-LIBRARY.md`) + CC0 sources + purchased assets, each with a recorded license, replacing the
mined set. This is a v2 milestone, not an afterthought.

## 7. Distance to done — Sand Creek (pilot #1)

Honest remaining work to a track Kevin would call good, in order:

1. **Prove the binary** (unknown, possibly fine): install the existing Jul 1 kn5 on Windows via
   Content Manager; does it load, render, collide? → first `DRIVE-TEST-REPORT`. If it fails, fix
   the export path *with this one test as the loop-closer* — this is exactly the question
   `BUILD-ON-WINDOWS.md` left open.
2. **Rebuild reproducibly** from today's repo (`./scripts/build.sh projects/sand-creek-raceway`),
   commit the intermediates worth keeping, and record gate baselines in `data/` history.
3. **Drive-test iteration loop** — Kevin drives, files the report (worst 3 spots, corner refs,
   screenshots); one session per defect class; regression test per fix.
4. **The Windows-manual mile**: record `fast_lane.ai` in-game; generate real `map.png` +
   `preview.png`; verify CM UI metadata. (~an evening of Kevin's time once the track is stable.)
5. **Look & feel pass** driven by the dossier + owned assets (replace mined textures, place the
   barrier/sign/lamp/building models, verify "looks good in game" per asset).
6. **License-clean release candidate** — `licenses.json` complete and truthful; only then does
   distribution (even to friends) become possible.

Steps 1–2 are one focused session + one Kevin evening. The loop in step 3 is where v1 died;
v2's session rules exist precisely to keep it convergent. Lake Murray starts only after Sand
Creek reaches DoD **T3** (see `DEFINITION-OF-DONE.md`), and its first step is the same: prove
the existing 20.7 MB kn5 in-game.

## 8. V1 lessons, stated once

1. A proxy you wrote, calibrated to your own output, and can bypass is not verification.
2. The human drive test is the only ground truth; engineer the loop *around* it, don't route
   around the human.
3. One place, finished, beats six places started. Generalize after the second success, not
   before the first.
4. Code that duplicates a job is debt the moment it lands; deletion is progress.
5. Confidence language ("done", "Kunos-grade", "verified") without an artifact is how a
   two-month hole gets dug. Claims now require artifacts.
6. Assets without licenses are unshippable, no matter how good they look.
