# Location Dossier — <Place name> (<slug>)

> Copy to `projects/<slug>/dossier.md`. Fill every section — "unknown, will verify via X" is a
> valid answer; silence is not. Kevin reviews and approves this document **before any geometry
> is built**. The dossier is the customization: what makes THIS place itself, and exactly how
> we'll build that.

## 1. Identity & intent
- What is this place (street loop / road course / freeway / rally stage) and why this one?
- The drive we're chasing (tight industrial sprint? flowing lakeside loop?). 2–3 sentences.
- Layouts wanted (single loop first; variants only as AC configs over one mesh).

## 2. Route geometry (facts, per street/segment)
| Segment | Streets | Length | Lanes/width (measured, source) | Curbs/sidewalk | Surface & condition | Notes |
|---|---|---|---|---|---|---|
Sources: OSM tags (verify widths against aerial measurement — don't trust defaults), county GIS,
Kevin's capture/dashcam footage, LiDAR scans. Note one-ways, medians, painted vs raised islands,
crossings, rail lines, bridges/culverts.

## 3. Elevation & drainage
Real grades along the route (3DEP), notable crests/dips/blind spots, bridge decks, creek
crossings, known drainage features. Street loops get *real* elevation only — no invented
banking (CLAUDE.md first principles; `track-grading` is for purpose-built circuits).

## 4. Corner-by-corner character
Numbered corner list with: real-world reference imagery (Street View/Mapillary link or capture
frame), what defines the corner (building at apex? pole line? fence?), curb reality, and any
QA-relevant hazard (crest, off-camber, narrowing).

## 5. Built environment & landmarks
Architecture stock (industrial metal? brick? stucco?), specific landmarks that make the place
recognizable, signage inventory (street blades, stop/yield, overhead), street furniture
(lights, hydrants, poles, wires), fencing types per stretch.

## 6. Vegetation & terrain palette
Species actually present (e.g. plains cottonwood, poplar rows, scrub), density per stretch,
ground cover (dry grass? gravel verge?), backdrop/skyline (mountains? water? refinery?).

## 7. Atmosphere & light
Latitude/orientation sun character, typical sky, time-of-day presets worth shipping, the one
photo that nails the mood.

## 8. Asset plan (owned-first — see `docs/ASSET-LIBRARY.md`)
| Need (from §5–§6) | Owned asset (Dropbox path) | License status | Conversion notes (scale/Y-up/PoT/EXR→PNG) | Placement | Or GAP → purchase candidate (store link, price) |
|---|---|---|---|---|---|
Rules: every row has a license entry before import; purchases only from the GAP column and only
after the owned-asset in-game proof (`V2-OPERATING-MODEL.md` §Assets); no mined mod content, ever.

## 9. Data sources & capture assets
Overpass extracts, DEM tiles, KML (only for deliberate off-network segments), Kevin's recordings
(`/simracing/...`), LiDAR scans, route maps — with paths/dates.

## 10. Location-specific QA criteria
What the drive test must specifically confirm here, beyond the standard report — e.g. "the
Quebec St bridge joint doesn't launch the car", "warehouse row reads as Commerce City, not
generic", per-asset look checks.

## 11. Build plan (short)
Toolbox pieces + order, config deltas, bespoke work this location needs, gates + thresholds,
first drive-test question.

---
**Kevin's approval:** ☐ approved as-is / ☐ approved with changes noted above — date:
