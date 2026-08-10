# STATE — Lake Murray (pilot #2) — `san-diego-loop`

> Ledger of VERIFIED vs CLAIMED vs NEXT. Seeded 2026-08-10 from the v1 audit.
> **Queued behind Sand Creek: no build sessions here until Sand Creek reaches DoD T3**
> (CLAUDE.md project order). Dossier research may start earlier only if Kevin asks.

**DoD tier: T0 (as of the 2026-07-01 build; unproven from today's checkout).**
**Canonical config: THIS project** (`projects/san-diego-loop`, v0.2.0, circuit pipeline).
The other San Diego projects — `san-diego-cruise`, `san-diego-freeway-loop`, `gala-seed` —
are **separate v1 experiments, all PARKED**; do not fold them in without Kevin.

## Verified (artifact-backed)
- A 20.7 MB kn5 with a valid AC header exists — `tracks/san_diego_lake_murray/`, built
  2026-07-01 (commit `fa1e03a`, PR #12). Claimed length 15,216 m (ui_track.json).
- Source route: `source/lake_murray_loop.kml` (139 KB) + `data/connectors.local.json`.

## NOT verified — open questions
1. Same as Sand Creek #1: does the kn5 load/render/collide in AC? Never attempted.
2. T2–T5 all unattempted: no AI line, placeholder minimap, no preview.png.
3. Route/layout itself unreviewed by Kevin against intent ("6 connector streets" suburb fill
   was v1 scope creep — PR #12; the v2 dossier decides what stays).

## Next (when unblocked)
1. Quick win alongside Sand Creek's first Windows evening: install this kn5 too — same
   evening, second data point on the exporter question.
2. Full dossier: lakeside character, SD vegetation (palms/eucalyptus vs Commerce City
   industrial), shoreline backdrop, owned-asset mapping.
3. Then the standard cycle: rebuild → gates → iterate to T3+.

## Session log
- 2026-08-10 — v2 reboot; ledger seeded; queued behind Sand Creek.
