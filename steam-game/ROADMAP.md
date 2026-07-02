# ROADMAP — GALA

Milestones for **future Claude sessions**. Each has **acceptance criteria** an AI session can check
itself against, and flags any step that needs a **human** (driving feel, VR comfort, Steam ops).

**Order is deliberate.** Car feel first (M0) because it's the make-or-break and the hardest to
retrofit. Do not skip ahead to pretty visuals on a car that doesn't feel right.

A session should: read [`README.md`](./README.md) → find the current milestone here → open the doc it
points at → do the work → check acceptance criteria → update **Status** below.

---

## Status tracker

| Milestone | State | Notes |
|-----------|-------|-------|
| M0 — Car feel on the seed route | ⬜ not started | first build session starts here |
| M1 — Telemetry as paint | ⬜ not started | |
| M2 — Procedural world + sanctum | ⬜ not started | |
| M3 — Hardware breadth + VR polish | ⬜ not started | |
| M4 — Steam release readiness | ⬜ not started | |

_Update the state emoji and notes as milestones progress. Keep this table honest._

---

## M0 — Car feel on the seed route  {#m0}

**Goal:** the car feels *great* on the Moza R9, driving the real imported Gala Ave →
Benchley-Weinberger centerline. Nothing pretty required. This is [`CAR_FEEL.md`](./CAR_FEEL.md) made
real. **This milestone is the product's spine — protect it forever after.**

Tasks:
1. Stand up the UE5.4+ project skeleton + the plugin layout in [`ARCHITECTURE.md`](./ARCHITECTURE.md#module-layout-proposed).
2. **De-risk FFB first:** standalone spinning-wheel test driven by a hand-authored torque curve →
   prove DD output (Moza SDK and/or generic DirectInput constant force) on the R9.
3. Substepped vehicle physics (≥ 360 Hz): tire model with real slip curve + self-aligning torque;
   suspension + load transfer; heavy mass/inertia.
4. FFB = computed rack torque on a dedicated high-rate thread (≥ 300 Hz output).
5. Input: Moza R9 steering, **Heusinkveld load-cell brake with force→brake curve**, throttle,
   Simagic shifter (seq + H), Moza handbrake. Basic calibration.
6. Import the seed centerline as a drivable spline + rough terrain via `GalaSeedImport` (see
   [`PIPELINE_BRIDGE.md`](./PIPELINE_BRIDGE.md)). Grey-box world is fine.

**Acceptance criteria:**
- [ ] Physics substep runs ≥ 360 Hz, decoupled from render fps (measured, logged).
- [ ] FFB is computed rack torque (not canned effects), output ≥ 300 Hz, no perceptible lag.
- [ ] Load-cell brake responds to *force* via a tunable curve, not linear travel.
- [ ] Car is drivable end-to-end on the imported Gala→Benchley centerline.
- [ ] **Eyes-closed test:** a competent driver can catch a slide by feel alone.
- [ ] 🧑 **Human gate — owner sign-off:** owner drives it on the real rig and confirms it feels
      good. *Cannot be self-certified by an AI session — flag for a driving test.*

---

## M1 — Telemetry as paint  {#m1}

**Goal:** how you drive visibly, coherently changes the world. Prove *car is the brush*.

Tasks: build the **telemetry bus** and the **intensity** scalar; wire `MPC_Mood`; first pass of
post-process + Niagara + sky driven by telemetry; the driving↔relaxing duality readable end to end.
See [`ARCHITECTURE.md`](./ARCHITECTURE.md#telemetry--visual-system-galapaint).

**Acceptance criteria:**
- [ ] Every active visual system reads from the telemetry bus / MPC — none read raw physics directly.
- [ ] Intensity eases smoothly (hysteresis/slew); no flicker; visibly spans serene ↔ churning.
- [ ] Driving calmly vs. hard produces clearly different, *intentional-looking* worlds.
- [ ] FFB rate and feel from M0 are **unregressed** (re-check every milestone).

---

## M2 — Procedural world + sanctum  {#m2}

**Goal:** the world blooms outward from the seed into biomes; the golf-course **sanctum** feels
special, spiritual, and mysterious.

Tasks: World Partition + PCG spine-following generation; biome blending (neighborhood → swirl →
forest → ghost town → desert); **environment→vehicle coupling** (forest drag/weight, desert light,
ghost-town grip); hand-author the **sanctum** as a fixed, reverent, unexplained landmark that the
world gently draws you toward. See [`VISION.md`](./VISION.md) + [`ARCHITECTURE.md`](./ARCHITECTURE.md#procedural-world).

**Acceptance criteria:**
- [ ] Driving away from the anchor transitions through blended biomes (no hard seams).
- [ ] Biomes measurably change car behavior *and* FFB texture, readably (not noise).
- [ ] The sanctum is hand-authored, consistent every drive, and calms the world on approach.
- [ ] 🧑 **Human gate:** the sanctum reads as special/spiritual/mysterious to a fresh player.
- [ ] Abstract dramatic skies present across biomes; sky reads as a character.

---

## M3 — Hardware breadth + VR polish  {#m3}

**Goal:** great beyond the owner's rig; VR is comfortable and composed.

Tasks: generic DirectInput/SDL2 FFB across common bases with per-base scaling; full rebind +
calibration UI; keyboard/gamepad fallback; OpenXR Valve Index at 120 Hz with quality tiers, dynamic
res/foveation; ultrawide FOV correctness; comfort options. See
[`CAR_FEEL.md`](./CAR_FEEL.md#hardware-support-matrix) + [`ARCHITECTURE.md`](./ARCHITECTURE.md#vr).

**Acceptance criteria:**
- [ ] FFB works on ≥ 3 non-Moza bases (belt/gear/other DD) with sane scaling.
- [ ] Rebind + calibration UI covers wheel/pedals/shifter/handbrake; keyboard/gamepad fallback works.
- [ ] VR holds frametime at 120 Hz on the 4090 with a quality tier; flat + VR both look composed.
- [ ] 🧑 **Human gate:** VR comfort check — no significant sim-sickness in a 15-min drive.
- [ ] Min-spec quality tier runs acceptably (defines the Steam min spec).

---

## M4 — Steam release readiness  {#m4}

**Goal:** shippable as a **driving** *and* **relaxing** experience.

Tasks: main menu / options / rig setup flow; onboarding for non-sim players; save/settings; audio
pass (adaptive to intensity); performance across tiers; optional photo/share; Steamworks integration;
store page assets (the trailer showcases car feel + the paint transformation + the sanctum);
accessibility & comfort defaults.

**Acceptance criteria:**
- [ ] First-run rig detection/setup gets a sim owner driving in < 2 minutes.
- [ ] Non-rig player can experience it (gamepad/keyboard) without a broken store review.
- [ ] Stable across quality tiers; documented min/rec specs.
- [ ] Steamworks build uploads, launches from Steam, settings persist.
- [ ] 🧑 **Human gates:** owner final sign-off on feel; store/marketing owned by the user.

---

## Cross-cutting rules (every milestone)

- **Never regress car feel.** Re-run the M0 FFB/latency checks after each milestone.
- **Update the status tracker** above honestly.
- **Flag human gates** (feel, VR comfort, Steam ops) — an AI session cannot self-certify these.
- **Keep the seed reproducible** — real geometry stays sourced from the Python bundle (see
  [`PIPELINE_BRIDGE.md`](./PIPELINE_BRIDGE.md)), never hardcoded in game code.
