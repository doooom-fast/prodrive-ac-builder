# Gates changelog

Every change to a gate threshold, bypass, exclusion, or wiring gets an entry here **in the same
PR**: what changed, measured justification, and Kevin's sign-off. Silent weakening is how v1's
gates went vacuous (`V1-AUTOPSY.md` §3). Append-only; newest first.

Gate run *results* are not logged here — they append to each project's
`data/gate_history.jsonl` so trends are visible.

---

## 2026-08-10 — Baseline inventory (no changes; recording inherited v1 state)

Documenting the thresholds and bypasses as found, so future changes have a comparison point.
None of these are hereby endorsed; items marked ⚠ are queued for review in the v2 backlog
(`V2-OPERATING-MODEL.md` #3).

| Gate | Current behavior | Flag |
|---|---|---|
| `scripts/geometry/audit_mesh.py` | Checks A,B,D,E,F,G,H,I gate at count 0; check C warn-only and exception-swallowed (`:267`) | ⚠ C can silently disable |
| `audit_mesh.py:322` | "Curb flush" tolerance ±0.5 m within 3.5 m reach | ⚠ 5× looser than a real curb |
| `audit_mesh.py:307` | Wall may float ≤1.4 m, or any amount with a seated neighbour within 2.4 m | ⚠ |
| `scripts/geometry/drive_test.py:552` | Allows 1 unguarded excursion drop per km | ⚠ car-destroyer allowance |
| `drive_test.py:556` | ≤12 severe (>6 cm) steps/km; 75–150 bumps/km — calibrated to Sand Creek's own output | ⚠ self-referential calibration |
| `drive_test.py:546` | `GATE_EXCURSIONS_ADVISORY=1` demotes drops to advisory | ⚠ bypass env var — remove |
| `scripts/ac/verify_kn5.py:40` | `POKE_MAX = 20` terrain pokes allowed in shipped kn5 | ⚠ |
| `scripts/ac/kn5_ground_check.py:453` | Walls/props pass at ≤0.2 m median / ≤0.4 m p95 hover, ≤1% >0.3 m, ≤10% feet unreferenced | ⚠ |
| `kn5_ground_check.py:633` | `GATE_CONTACT_ADVISORY=1` overwrites measured contact fraction with 0.0 | ⚠ bypass env var — remove |
| `kn5_ground_check.py:253` | 170 m embankment exemption around declared bridge spans | review |
| `build_network.sh` | Inline reimplementation runs only checks A+B of 9; no drive test, no fidelity | ⚠ park path or wire real gates |
| `build_loop.sh` | No drive test, no mesh audit (Blender-first path); currently unrunnable (no `loop.blend` exists) | parked |
| Wiring | `build.sh` runs drive+audit+verify+fidelity hard (`set -euo pipefail`, no `|| true`); stage-resume skips gates bound to earlier stages | resume caveat noted |
