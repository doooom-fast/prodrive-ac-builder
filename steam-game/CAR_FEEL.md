# CAR_FEEL — the priority

> **This is the one thing that must be right.** The owner drives a real sim rig; the Steam market is
> sim-rig owners. A gorgeous world on a mushy car is a failed product. Build and tune this *first*
> (Milestone M0), and protect it as everything else grows.

The goal, in the owner's words: **weighty, sometimes slow, sometimes fast, in a feedback loop with
the environment**, and it must **feel real "within reason of our fantasy world."** We are not
chasing validated tire data — we are chasing a car that a serious sim driver believes through the
wheel.

---

## Why UE5's built-in vehicle is not enough (and the plan)

Chaos Vehicles (UE5's built-in) is fine for arcade/gameplay cars but its force-feedback story for
direct-drive wheels is weak — it leans on canned rumble/effects, not a computed steering-rack torque.
Direct-drive owners feel the difference instantly.

**The plan:** treat FFB as a **first-class, physics-derived output**, decoupled from UE's generic
input system.

1. **Vehicle physics in a fixed high-rate substep.** Run the tire/suspension model at a fixed
   timestep (target **≥ 360 Hz**, independent of render framerate). Chaos can host the rigid body,
   but the **tire forces and self-aligning torque are ours to compute** so we control the feel and
   the FFB signal. If Chaos's tire model fights us, replace just the tire model (a brush/Pacejka-lite
   model is enough for "believable"), not the whole vehicle.
2. **FFB = steering-rack torque, computed, sent as a constant force.** Each physics substep, sum the
   torques acting on the steering rack — primarily **tire self-aligning torque** (pneumatic trail ×
   lateral force) plus caster, plus a small friction/damping/inertia model — and output it as a
   **signed DirectInput/FFB constant-force effect** at the substep rate. This is exactly how AC /
   iRacing / rF2 drive a DD base. No spring/damper canned effects as the primary channel.
3. **Dedicated FFB thread.** Do not gate FFB on the game thread or render thread. A separate thread
   (or the physics thread) reads the latest computed torque and writes the effect at a steady high
   rate. Stale/janky FFB is worse than none.
4. **Environmental feedback loop.** The "world pushes the car" pillar lives here: biomes modulate
   grip, drag, weight, and FFB texture (see [environment coupling](#environment-coupling)). This is a
   *design feature*, not noise — keep it intentional and readable.

> Implementation note for the M0 session: prototype the FFB path **early and standalone** — a spinning
> wheel driven by a hand-authored torque curve — to prove the DD output path (Moza SDK and/or generic
> DirectInput constant force) *before* wiring it to physics. De-risk the hardware seam first.

---

## Physics model (target, not dogma)

- **Tire model:** brush model or simplified Pacejka — enough to get a real slip curve (grip rises,
  peaks, falls) so the car communicates the limit through the wheel. The *peak and falloff* are what
  the driver feels; get those honest.
- **Self-aligning torque:** the heart of FFB. Pneumatic trail collapses near the limit → the wheel
  goes light right as grip peaks. That lightening is *the* signal sim drivers read. Model it.
- **Suspension:** sprung/unsprung, load transfer front/rear and left/right. Load transfer changes
  per-tire grip → the car rotates believably and the FFB weights up under load.
- **Weight & inertia:** the car should feel *heavy*. Real mass, real yaw inertia. "Sometimes slow"
  should feel like moving mass, not low top speed. Powertrain with believable torque delivery.
- **Handbrake:** analog Moza handbrake wired to rear brake bias / rotation — an *expressive* control
  for painterly slides, not just parking.

Everything is a fantasy tuning on top of believable structure. It's OK for grip levels, power, and
weight to be unrealistic **as long as the wheel tells a coherent, physical story.**

---

## Tuning targets (what "feels good" means, checkably)

- **Latency:** end-to-end input→FFB response feels immediate. Physics substep ≥ 360 Hz; FFB output
  rate ≥ 300 Hz; no perceptible lag between countersteer and force change.
- **Center feel:** a clear, weighty on-center without notchiness or deadzone; caster returns the
  wheel naturally.
- **Limit communication:** the driver can catch a slide *by feel alone* (eyes closed test) — the
  wheel lightens at the grip peak and loads up on the catch.
- **Weight:** the car reads as heavy machinery in motion; direction changes take effort and settle.
- **No clipping / no noise:** FFB scaled so peak forces don't clip the 9 Nm base in normal driving;
  no high-frequency buzz that isn't intentional road/biome texture.
- **Owner sign-off:** the owner drives it on the real rig and says it feels good. This is the final
  gate for M0 and cannot be faked by an AI session — flag it explicitly for a human driving test.

---

## Hardware support matrix

Owner's rig is the **tuning reference**; broad support is a **release** requirement (M3).

| Class | Owner's device | Support approach |
|-------|----------------|------------------|
| **Wheelbase (DD)** | Moza R9 (9 Nm) | Primary: Moza SDK if it improves fidelity. Fallback + broad support: **generic DirectInput/RawInput constant-force FFB** — covers Fanatec, Simucube, Simagic, Logitech, Thrustmaster DD/belt/gear. Per-base torque scaling + soft-clip. |
| **Pedals** | Heusinkveld Ultimate+ (load cell) | **Brake is force, not travel** — expose a force→brake curve with adjustable gamma; don't treat brake as a linear axis. Standard axis path for potentiometer pedals. Per-pedal calibration + curves in-game. |
| **Shifter** | Simagic sequential + H-pattern | Support both. Auto-detect / let player pick. Sequential = flow; H-pattern = deliberate, weighty moments. |
| **Handbrake** | Moza analog handbrake | Analog axis → rear brake / rotation. Also usable as an expressive art input. |
| **Generic** | — | Everything through **SDL2 or DirectInput**, not just XInput. Full **rebind + calibration UI**. Sane defaults for popular bases. Graceful **keyboard/gamepad fallback** so non-rig players (and the store page) work — but the rig is where it sings. |

**Displays:** 39" curved ultrawide (correct wide-aspect FOV, no stretch; the frame is compositional)
and **Valve Index VR** (OpenXR, 120 Hz target). See [`ARCHITECTURE.md`](./ARCHITECTURE.md#vr).

---

## Acceptance criteria (M0 gate)

See [`ROADMAP.md`](./ROADMAP.md#m0) — M0 is *this doc, made real on the seed route*. Summary:
computed-torque FFB on the Moza R9, physics substep ≥ 360 Hz, load-cell brake curve, drivable on the
imported Gala Ave → Benchley-Weinberger centerline, and the **eyes-closed slide-catch** + **owner
sign-off** both pass.
