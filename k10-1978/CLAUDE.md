# 1978 — session orientation

This repo is **_1978_**: a UE5 driving-as-art experience for sim rigs, set in gritty autumn 1978.
The car is the brush, telemetry is the paint, the sky and terrain are the canvas. Internal codename
in code/paths is `Gala` (identifiers can't start with a digit).

**Start every session at [`README.md`](README.md)** — it orients you in 60 seconds and maps the
plan docs. Then open [`ROADMAP.md`](ROADMAP.md), find the current milestone in the status tracker,
and work against its acceptance criteria.

## Non-negotiables (from the plan — details in the docs)

- **Never regress car feel.** Substepped physics (≥ 360 Hz) and computed rack-torque FFB
  (≥ 300 Hz) are the product's spine. Re-run the M0 checks after every milestone. `CAR_FEEL.md`.
- **Telemetry bus is the only source for visuals.** No visual system reads raw physics directly.
  `ARCHITECTURE.md`.
- **The era is total.** Film-stock rendering, fall palette, no modern-day anything in frame.
  `VISION.md`.
- **Real geometry comes from the `seed/` bundle** (exported by the sibling repo
  `k10-motorsports/prodrive-ac-builder`) — never hardcoded, never hand-traced. `PIPELINE_BRIDGE.md`.
- **Human gates cannot be self-certified** (driving feel, VR comfort, Steam ops) — flag them,
  update the ROADMAP status tracker honestly.

## Layout

- Plan docs at repo root (`VISION`, `CAR_FEEL`, `ARCHITECTURE`, `PIPELINE_BRIDGE`, `ROADMAP`).
- `seed/` — committed real-world seed bundle (input, not generated here).
- `Gala/` — the UE5 project (created at milestone M0).
