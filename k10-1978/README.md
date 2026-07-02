# 1978

> **Title: _1978_** (owner-decided, final). The era the game lives in — the childhood streets as they
> were, seen through gritty 70s film stock. Internal codename in code/paths remains `Gala` (after
> Gala Ave; identifiers can't start with a digit). **This repo (`k10-1978`) is the game** — plan now,
> UE5 project as it's built. The real-world seed pipeline lives in the sibling repo
> [`k10-motorsports/prodrive-ac-builder`](https://github.com/k10-motorsports/prodrive-ac-builder).

**One line:** an atmospheric driving-as-painting experience for sim rigs — the car is the brush,
telemetry is the paint, and the sky, terrain, and weather are the canvas. It starts on a real street
in 1978 San Diego and dissolves outward into procedural, abstract worlds — all of it soaked in a
**gritty 70s** aesthetic: film grain, sodium light, heavy analog machinery.

The docs at the repo root are the **handoff plan**. They are written for **future Claude Code
sessions** to pick up and build against — not a human design doc. Every milestone has concrete,
checkable acceptance criteria so a fresh session can tell what "done" means without re-litigating
the vision.

---

## Read this first (fresh-session orientation)

You are (probably) a new session with no memory of this plan. Here is the whole thing in 60 seconds:

1. **What we're building.** A UE5 game where driving *is* the art. Not a racing game. There is no
   lap time (though there is a *feel* of speed and effort). You drive a weighty, believable
   70s-era car through worlds that are painted in real time by how you drive. The whole experience
   is set in **autumn 1978** — gritty film-stock visuals, fall colors, analog everything. Sold on
   Steam as both a **driving** experience and a **relaxing** one. VR-capable (Valve Index), plays
   great flat on a 39" ultrawide.

2. **Where it comes from.** The sibling repo `prodrive-ac-builder` is a Python pipeline that turns
   real roads into Assetto Corsa tracks. It already built the **Lake Murray Loop** and a **San Diego
   neighborhood freeroam** — the childhood neighborhood — and one of those maps "got weird" in
   a way that inspired this game. **We reuse that pipeline**: it produces the real, georeferenced
   seed geometry (Gala Ave → Benchley-Weinberger Elementary) and exports it as a bundle committed
   into this repo under `seed/`; Unreal grows the abstract world outward from that anchor. See
   [`PIPELINE_BRIDGE.md`](./PIPELINE_BRIDGE.md).

3. **The one thing that must be right.** **Car feel.** The owner drives a real sim rig and the Steam
   market is sim-rig owners. If the car doesn't feel weighty, physical, and alive through
   direct-drive force feedback, nothing else matters. The first vertical slice is *car feel on the
   seed route* — see [`CAR_FEEL.md`](./CAR_FEEL.md) and Milestone **M0** in [`ROADMAP.md`](./ROADMAP.md).

4. **Engine.** Unreal Engine 5. The plan assumes UE5.4+ (World Partition, PCG, Niagara, OpenXR).

---

## Document map

| Doc | What it's for |
|-----|---------------|
| [`VISION.md`](./VISION.md) | Creative bible. Pillars, tone, the driving↔relaxing duality, references, non-goals. Read to understand *why*. |
| [`CAR_FEEL.md`](./CAR_FEEL.md) | **The priority.** Physics model, FFB architecture, hardware support matrix, tuning targets, acceptance criteria. |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | UE5 technical architecture. Telemetry bus, telemetry→visual system, procedural world (PCG), VR, module layout. |
| [`PIPELINE_BRIDGE.md`](./PIPELINE_BRIDGE.md) | How the `prodrive-ac-builder` pipeline feeds this repo. Exact data contract (centerline + elevation + ENU projection → `seed/` bundle → Unreal). |
| [`ROADMAP.md`](./ROADMAP.md) | Milestones M0→M4 (vertical slice → Steam release), each with acceptance criteria written for AI sessions. |

**Suggested reading order for a builder session:** README → CAR_FEEL → ROADMAP (find current milestone)
→ the doc that milestone points at.

---

## Repo layout

```
k10-1978/
├── CLAUDE.md            # session orientation (points here)
├── README.md            # this file + the plan docs below
├── VISION.md  CAR_FEEL.md  ARCHITECTURE.md  PIPELINE_BRIDGE.md  ROADMAP.md
├── seed/                # the exported real-world seed bundle (gala_seed.json + heightfield)
│                        #   — produced by prodrive-ac-builder, committed here (see PIPELINE_BRIDGE)
└── Gala/                # the UE5 project (created at M0; codename dir — see title note above)
```

---

## Current status

**Phase: planning / handoff.** No Unreal project exists yet, and `seed/` is not yet populated. The
Python seed pipeline exists and is proven for this neighborhood — see `projects/san-diego-loop/`
and `projects/san-diego-cruise/` in `prodrive-ac-builder`.

**Next concrete action** for the first builder session: stand up the UE5 project skeleton and hit
Milestone **M0** (car feel on the seed route). See [`ROADMAP.md`](./ROADMAP.md#m0).

---

## Owner's rig (primary target — must feel first-class here)

| Component | Model | Notes for the plan |
|-----------|-------|--------------------|
| Wheelbase | **Moza R9** | Direct drive, 9 Nm. FFB must be a computed rack torque, not a canned effect. Moza SDK + generic DirectInput fallback. |
| Pedals | **Heusinkveld Ultimate+** | **Load-cell brake** — brake input is *force*, not travel. Needs a force→brake curve, not a linear axis. |
| Shifter | **Simagic sequential + H-pattern** | Support both modes. H-pattern + clutch is period-canonical for the 1978 car; sequential is a supported flow/comfort mode. |
| Handbrake | **Moza handbrake** | Analog. Wire to a real handbrake channel — useful as an expressive/art input, not just parking. |
| Display | **39" curved (ultrawide)** | Correct FOV + triple-ish aspect handling; the frame is part of the canvas. |
| VR | **Valve Index** | OpenXR, 120Hz target, seated cockpit reference = low sim-sickness risk. |
| GPU | **RTX 4090** | Budget for Lumen + volumetric skies + Niagara at high res / VR. Don't design to the floor; scale down for min-spec. |

Broad hardware support is a **release** requirement (Steam market), but the owner's rig is the
tuning reference. See [`CAR_FEEL.md`](./CAR_FEEL.md#hardware-support-matrix).
