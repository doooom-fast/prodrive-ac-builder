# Definition of Done — the tier ladder

"Done" is banned vocabulary in this repo (CLAUDE.md rule 3). Progress is claimed only as a
**tier**, and only with the tier's artifact linked in the project's `STATE.md`. Tiers are per
location. Skipping tiers is not possible by definition — each includes the ones below it.

| Tier | Claim | Required artifact (linked in STATE.md) |
|---|---|---|
| **T0 — Builds** | `./scripts/build.sh projects/<slug>` completes end-to-end from a clean checkout | Build log + zip in `build/` |
| **T1 — Gates pass** | All four wired gates green at recorded thresholds | `data/gate_history.jsonl` entry (append-only) |
| **T2 — Installs & loads** | Track installs via Content Manager and loads to the spawn without crash, on Kevin's Windows machine | Drive-test report §Install (screenshot of car on track) |
| **T3 — Drivable** | Kevin completes 3 consecutive clean laps: no fall-through, no invisible walls, no car-breaking geometry | Full `DRIVE-TEST-REPORT` with verdict DRIVABLE |
| **T4 — Playable** | AI line recorded in-game (`fast_lane.ai`), real minimap + CM preview, timing/sectors verified, AI race starts | Report + `ai/` contents + `map.png`/`preview.png` in the track folder |
| **T5 — Polished** | Looks and performs right everywhere: dossier look-checks pass, stable frame rate, complete CM assets; Kevin calls it finished | Drive-test report §Look verdicts + final zip |

Notes:
- **Distribution is a non-goal** (personal use only — Kevin, 2026-08-10). Kitbashed content is
  welcome at every tier; there is no "releasable" bar to clear.
- A regression drops the tier until re-proven; STATE.md records the drop and why.
- "Gates pass" (T1) is a **pre-check**, never a proxy for T2+ — that substitution is the exact
  v1 failure (`V1-AUTOPSY.md` §3).
- Current standing (2026-08-10): Sand Creek and Lake Murray hold **T0 as of Jul 1 builds**
  (unproven from today's checkout) and nothing higher — T2 has never been attempted.
