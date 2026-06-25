# Prodrive Scan

A **track-agnostic** iOS capture app for the Prodrive AC Builder pipeline. Mount the phone on the
windshield, drive the real route, and it records everything needed to make a built AC track *look like
the real place*:

- **HEVC video** of the route (from the ARKit camera frame)
- **6DoF camera pose** + intrinsics per frame (ARKit world tracking)
- **GPS** lat/lon/altitude + **true heading** (CoreLocation)
- **Barometric** relative altitude + pressure (CoreMotion) — the smooth signal for road grade
- **LiDAR** depth maps (throttled) + a fused scene mesh (iPhone/iPad Pro)

The app has **zero track knowledge** — it's a dumb logger. Association to a specific track happens on
the Mac at ingest, by projecting the captured GPS into the same local-metre frame the track mesh was
built in. One app, every track.

## Output: a session bundle (schema v1)

Each recording writes a directory under the app's Documents folder:

```
prodrive-scan-<UTC-stamp>-<id>/
  manifest.json   # session + device + counts + file refs + schema_version
  samples.jsonl   # one record per ARFrame: pose, intrinsics, GPS, baro, depth-ref
  video.mov       # HEVC
  depth/          # throttled sceneDepth maps (raw float32; dims in manifest.depth)
  mesh.obj        # fused LiDAR mesh in ARKit world coords
```

The contract is mirrored on the Mac in [`scripts/capture/bundle.py`](../../scripts/capture/bundle.py).
`SessionBundle.schemaVersion` (Swift) and `SCHEMA_VERSION` (Python) **must stay in lockstep**.

## Build & run

This Mac builds it; the **capture itself needs a physical iPhone Pro** (ARKit + LiDAR + GPS don't run
in the simulator — the simulator only proves it compiles).

```bash
cd apps/prodrive-scan
xcodegen generate                 # project.yml → ProdriveScan.xcodeproj (the .xcodeproj is gitignored)
open ProdriveScan.xcodeproj
```

Then in Xcode:
1. Select the **ProdriveScan** target → **Signing & Capabilities** → set your **Team** (the spec leaves
   `DEVELOPMENT_TEAM` blank; it can't be scripted headlessly).
2. Pick your iPhone as the run destination and press **Run**.
3. Grant **Camera**, **Location** (While Using), and **Motion** when prompted.

Compile-check without a device (what CI / this Mac does):

```bash
xcodegen generate
xcodebuild -scheme ProdriveScan -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' build
```

## Recording

Tap the red button to start; tap again to stop. The HUD shows elapsed time, frame count, GPS accuracy,
and LiDAR depth-map / mesh-anchor counts. On stop it finalises the video, writes `manifest.json`, and
shows the saved bundle name.

## Getting a bundle onto the Mac

Bundles can be multiple GB per lap, so they live **outside git** (like the mined mod assets). The app
sets `UIFileSharingEnabled` + `LSSupportsOpeningDocumentsInPlace`, so grab a bundle via any of:

- **Finder** (USB): select the iPhone → **Files** tab → **Prodrive Scan** → drag the folder out.
- **Files app** → On My iPhone → Prodrive Scan → AirDrop / copy to a synced folder.

## Ingest (on the Mac)

```bash
python3 -m scripts.capture.ingest projects/<slug> <path-to-bundle>
```

This projects every GPS fix into the track's mesh frame, matches it to the centerline (arc-length
**station** + signed lateral offset), and distils the run into committed
`projects/<slug>/source/realworld_capture.json`. Re-ingesting is idempotent; multiple laps accumulate.
See [`scripts/capture/ingest.py`](../../scripts/capture/ingest.py).
