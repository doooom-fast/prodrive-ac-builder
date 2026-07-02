# ARCHITECTURE — 1978 (UE5)

> Code/paths use the internal codename **`Gala`** (identifiers can't start with a digit); the game
> is titled **1978**.

Technical architecture. Assumes **Unreal Engine 5.4+**. This is a shape to build toward, not a
frozen spec — but the seams below (telemetry bus, intensity, seed import) are the load-bearing ones;
change them deliberately.

---

## Module layout (proposed)

Keep gameplay/physics/art decoupled so sessions can work on one without breaking others.

```
Gala/ (UE5 project)
├── Plugins/
│   ├── GalaVehicle/        # physics + FFB: substepped tire model, rack-torque, FFB thread, input/rebind
│   ├── GalaTelemetry/      # the telemetry bus (single source of truth for "how the car is being driven")
│   ├── GalaPaint/          # telemetry → visuals: MPC drivers, Niagara, post-process, sky/weather
│   ├── GalaWorld/          # procedural world: PCG, biomes, intensity, the golf-course sanctum
│   └── GalaSeedImport/     # editor/runtime import of the Python pipeline's centerline + heightfield
├── Content/
│   ├── Vehicle/  Sky/  Biomes/  Sanctum/  Audio/  UI/
└── Config/                  # rig profiles, quality tiers, VR settings
```

---

## Telemetry bus

The **single source of truth** for "how the car is being driven." Everything visual and audio reads
from it; nothing reads raw physics state directly. This is the literal implementation of *telemetry
is the paint*.

Sampled every frame (and accumulated in physics substeps), published as a struct / gameplay data
object:

| Channel | Use downstream |
|---------|----------------|
| speed, longitudinal accel | palette temperature, motion blur, wind, audio pitch |
| lateral G, yaw rate | world "churn", camera lean, color smear direction |
| slip angle (per axle), at-limit flag | saturation spikes, particle bursts, the "on the edge" shimmer |
| throttle / brake / clutch | energy in/out of the painting; brake = restraint |
| suspension travel / load (per corner) | terrain ripple, impact accents |
| steering angle + **rack torque** | FFB (out) and a visual "effort" signal |
| RPM / powertrain load | rhythmic/percussive audio, pulse of the world |
| handbrake | expressive slide → deliberate paint strokes |
| distance-from-anchor, position | biome selection, sanctum proximity |

**Rule:** if a visual isn't driven by a telemetry channel or `intensity`, it probably violates the
"car is the brush" pillar — question it. (See [`VISION.md`](./VISION.md).)

---

## Intensity: the master mood value

A single smoothed scalar (0 = serene ↔ 1 = churning) derived from the telemetry bus (a weighted,
time-smoothed blend of speed, lateral G, slip, and input aggression). It drives the
driving↔relaxing duality globally:

- Feeds a **Material Parameter Collection** (`MPC_Mood`) that art assets sample — one knob, whole
  world responds, coherently.
- Modulates sky drama, weather speed, scatter density, audio layers, color grade.
- **Hysteresis + slew limits** so it eases, never flickers. The transition being *smooth* is a
  vision requirement, not a nice-to-have.
- **Sanctum override:** proximity to the golf-course sanctum pulls perceived intensity down toward
  reverent-calm regardless of driving (see [`VISION.md`](./VISION.md) → sanctum). The sanctum wins.

---

## Telemetry → visual system (GalaPaint)

- **Material Parameter Collections** as the backbone: telemetry + intensity → global MPC params →
  sampled by sky, terrain, road, and post-process materials. Cheap, global, coherent.
- **Niagara** for emissive/particle "brush strokes" spawned by events (limit hits, gear changes,
  handbrake) and continuous emitters scaled by speed/slip.
- **Post-process** volume driven by MPC: color grade, bloom, smear, chromatic drift tied to lateral
  motion. This is a lot of the "painting" — lean on it.
- **The film-stock layer (always on):** a final full-screen pass that makes the game "shot in 1978" —
  grain, halation, gate weave, anamorphic flare, vignette (see
  [`VISION.md`](./VISION.md#the-1978-aesthetic-gritty-70s-fall-colors)). Intensity modulates the
  *stock* (faded matinee ↔ pushed night stock), never removes it. All grading routes through
  **fall-palette LUTs** — biomes select between autumn grades; nothing escapes the palette. Must
  work in VR (stereo-coherent grain/flares — render in-world-scale, not screen-space-per-eye, to
  avoid stereo mismatch) and be cheap enough for the 120 Hz budget.
- **Sky & weather:** UE Volumetric Clouds + a custom sky material for the abstract/dramatic look;
  **not** photoreal weather. Low autumn sun, long shadows, haze/smog-glow, sodium-amber nights.
  Time-of-day and sky state are art-directed via intensity + biome, and double as the lighting the
  Python `lighting` skill philosophy already respects (true-north, dramatic sun). Sky is a
  *character*.

---

## Procedural world (GalaWorld)

- **World Partition + PCG** (UE5 Procedural Content Generation framework). The **real seed route is
  the spine**; PCG scatters/morphs the world outward from it.
- **Biome selection** as a function of `distance-from-anchor`, `intensity`, and a per-drive history
  (where the player has pushed hard). Biomes: neighborhood (real) → swirling textures → dense forest
  → ghost town → desert (see [`VISION.md`](./VISION.md#world--biome-vocabulary)). Blended, not hard
  borders.
- **Determinism:** seed PCG from a run seed so a drive is reproducible/shareable if desired; the
  **sanctum is hand-authored and exempt** from procedural variation (a fixed point).
- **Environment coupling:** biomes write back into the vehicle — forest raises drag/weight and FFB
  heaviness; desert lightens; ghost town lowers grip. This closes the *feedback loop with the
  environment* pillar. Keep the coupling readable and intentional (route it through GalaVehicle
  params, not ad-hoc).

---

## VR

- **OpenXR**, Valve Index. Seated **cockpit as fixed reference frame** = low sim-sickness risk (the
  cockpit is stable while the world moves — good vection hygiene). Target **120 Hz**; dynamic
  resolution / foveation to hold frametime.
- Comfort options: vignette-on-intensity (optional), horizon lock option, snap-free (it's driving).
- **Flat + VR share one world.** VR is a first-class render target, not a mode fork. The 39"
  ultrawide is the flat reference; both must look composed.
- Budget: 4090 can do Lumen + volumetrics + Niagara in VR *if* we tier it. Design with **quality
  tiers** from day one; don't paint into a corner that only a 4090 can render.

---

## Performance & scaling

- Physics substep rate is sacred (see [`CAR_FEEL.md`](./CAR_FEEL.md)) — never sacrifice FFB rate for
  visuals. Decouple render fps from physics fully.
- Quality tiers (min-spec → 4090/VR) gate volumetrics, Lumen, Niagara counts, PCG density.
- Everything visual keys off the telemetry bus + MPC, so scaling down = fewer particles / cheaper
  materials, **not** a different game.
