# Prodrive AC Builder — v2

Build **real places** as drivable Assetto Corsa tracks. One location at a time, deeply
researched, customized per build. Everything before 2026-08 is **v1**; its full record — what
worked, what looped, what it cost — is `docs/V1-AUTOPSY.md`. v2 exists to not repeat it.

**Project order: 1) Sand Creek Raceway → 2) Lake Murray.** No work on the next location before
the current one reaches DoD **T3** (Kevin-verified drivable — `docs/DEFINITION-OF-DONE.md`).

---

## The v2 operating model

**Claude is the orchestrator of a toolbox — there is no one-shot pipeline.** Each location gets:

```
LOCATION DOSSIER  →  BUILD PLAN  →  TOOLBOX RUNS + GATES  →  HANDOFF  →  KEVIN DRIVE-TESTS
 (researched,        (Kevin           (Mac, scripted)        (zip +      (Windows, structured
  Kevin reviews)      approves)                               notes)      report back)
```

Detail: `docs/V2-OPERATING-MODEL.md`. Templates: `docs/templates/LOCATION-DOSSIER.md`,
`docs/templates/DRIVE-TEST-REPORT.md`. Per-project ground truth: `projects/<slug>/STATE.md`.

### Non-negotiable session rules (each traces to a v1 failure)

1. **One location, one goal per session.** State the goal in the first message of work; if it
   isn't reached, say so plainly. A session never opens a second front.
2. **Dossier before geometry.** No mesh work for a location until its dossier exists and Kevin
   has approved it. The dossier decides customization on paper, where iteration is cheap.
3. **Banned vocabulary:** "done", "complete", "verified", "ready to drive" — unless quoting a
   `DRIVE-TEST-REPORT` or a DoD tier with its artifact linked. The honest formulation is
   "gates pass; awaiting drive test."
4. **Gates are law.** Never weaken a threshold, add a bypass, or skip a wired gate without an
   entry in `docs/GATES-CHANGELOG.md` (measurement, rationale, Kevin's sign-off). Gate history
   appends to `projects/<slug>/data/gate_history.jsonl` — numbers must be comparable over time.
5. **No parallel implementations.** Extend or refactor the canonical path (`scripts/build.sh`);
   never fork a `_v2`/`_network`/`_native` twin. Deleting code is a first-class contribution.
6. **Every fixed bug gets a regression test** in the same commit. v1 fixed fall-through six
   times because nothing locked the fix.
7. **Sessions always land**: push the branch and update `STATE.md` (Verified / Claimed /
   Next) before ending — even mid-task. Unpushed work is money burned (Jul 25–Aug 10 taught this).
8. **Assets must be licensed.** Every asset in a build has an entry in `assets/licenses.json`
   proving distribution rights. Kevin's Dropbox 3D library (`docs/ASSET-LIBRARY.md`) is the
   primary source; mined mod content is being retired (see autopsy §6) and must never be added.
   New purchases only via a dossier "gap" list Kevin approves — after the owned-asset
   look-good-in-game proof (`docs/V2-OPERATING-MODEL.md` §Assets).

## First principles (unchanged from v1 — they held)

- **The screenshot is a selection aid, not data.** Geometry derives from OSM/Overpass; KML only
  where the route deliberately leaves the road network; aerial tracing only when no OSM exists.
- **Reproducible from `track.config.json`** — no hardcoded coordinates/widths/rotations in
  scripts; derived values are written back to config. (v2 addendum: tuned *constants* belong in
  config or a documented defaults table, not as magic numbers in code.)

## Build environment split

| Platform | Role |
|---|---|
| **Mac** (headless) | Data acquisition, geometry, Blender build, kn5 export, gates. Fully code-driven. |
| **Windows** (Kevin) | The only ground truth: install via Content Manager, drive, record AI lane, screenshot. Structured feedback via `DRIVE-TEST-REPORT`. |

Anything the Mac side cannot verify (rendering, collision-in-game, look & feel, AI recording) is
**by definition unverified** until the Windows loop says otherwise.

## Conventions (enforced; unchanged)

- **Meters, Y-up**, origin from config (`centroid` default), true north resolved and written
  back to `true_north_rotation_deg`.
- **Surface naming:** `1ROAD_*` drivable (keyed to `surfaces.ini`), `1KERB_*` kerbs, no numeric
  prefix = visual-only. Dummies: `AC_START_0..N`, `AC_PIT_0..N`, `AC_TIME_0_L/R…`,
  `AC_HOTLAP_START_0`.
- **Elevation source priority:** USGS 3DEP 1 m → OpenTopography → SRTM 30 m; smooth along the
  racing line.
- **Textures:** power-of-two dimensions (build preflight enforces; violations hard-crash AC/CSP).

## The toolbox (v1 code, curated — see autopsy §4 for the map)

| Status | Packages |
|---|---|
| **CORE** (canonical path) | `scripts/gps`, `elevation`, `geometry`, `environment`, `ac`, `vendor/io_import_accsv`, `tests` (`python tests/run_tests.py`, hermetic, CI-checked) |
| **USEFUL** (situational) | `capture` (iPhone/dashcam ingest), `trace` (drawn-route matching), `aerial` (GPS-less circuits), `lighting` |
| **PARKED** (do not extend without Kevin) | `game` (UE5 seed), `apps/prodrive-scan`, `assets` (one-shot generators), network fork (`build_network.sh` + `*_network_*`), loop fork (`build_loop.sh`, unrunnable — no project has `loop.blend`) |
| **STUB / DEAD** | `scs` (NotImplementedError×5), `modkit` (zero references) |

**Canonical build:** `./scripts/build.sh projects/<slug> [start-stage]` — stages
`gps elev project mesh env blend kn5 pack` with gates `drive`, `audit`, `verify`, `fidelity`
wired in. Requires Blender 4.x via `scripts/bootstrap_blender.sh` (or `KN5_WRITER=native` —
experimental, see autopsy §2 open question).

## Skills (11)

`gps-extraction`, `aerial-tracing`, `route-tracing`, `elevation`, `track-grading` (racetracks
only, unwired parts noted in its SKILL.md), `lighting`, `ac-track-modding`, `mesh-audit`,
`drive-test`, `road-grounding`, `scs-extraction` (stub). Statuses per SKILL.md are authoritative
— several honestly admit gaps; keep it that way.

## Repo layout (truthful as of 2026-08-10)

```
├── CLAUDE.md                    # this file — v2 constitution
├── docs/                        # V1-AUTOPSY, V2-OPERATING-MODEL, DEFINITION-OF-DONE,
│                                # GATES-CHANGELOG, ASSET-LIBRARY, templates/
├── scripts/                     # the toolbox (see table above)
├── tests/                       # hermetic suite — python tests/run_tests.py (CI runs this)
├── .claude/skills/              # 11 skills
├── assets/                      # shared textures/models + licenses.json (license landmine
│                                # being retired — autopsy §6)
├── vendor/                      # GPL kn5 exporter addon (patched at clone time)
├── apps/prodrive-scan/          # PARKED iOS capture app
├── projects/<slug>/             # track.config.json, STATE.md, dossier.md, source/, data/, build/
└── tracks/<slug>/               # last shipped installable folders (Jul 1; no AI lines yet)
```
