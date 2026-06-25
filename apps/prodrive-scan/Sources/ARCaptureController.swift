// ARCaptureController.swift — the ARSession delegate that produces a session bundle.
//
// Every ARFrame (on a private serial AR queue) becomes one synchronized log line: 6DoF pose +
// intrinsics from ARKit, the latest GPS/baro snapshot, an HEVC video frame, and (throttled) a LiDAR
// depth map. Scene-reconstruction anchors are accumulated for a fused mesh at stop. The app stays a
// dumb logger — no track knowledge — exactly as the pipeline expects.

import ARKit

enum CaptureError: LocalizedError {
    case noSession
    var errorDescription: String? {
        switch self {
        case .noSession: return "AR session not ready yet — wait for the camera preview."
        }
    }
}

struct CaptureStats {
    var frames = 0
    var depthMaps = 0
    var meshAnchors = 0
    var gpsAccuracy = Double.greatestFiniteMagnitude
    var hasLidar = false
    var elapsed = 0.0
}

final class ARCaptureController: NSObject, ARSessionDelegate {
    /// The session is owned by the preview view (ARSCNView.session) and attached here so the view can
    /// render while we receive ARSessionDelegate callbacks — the supported ARKit split.
    private(set) weak var session: ARSession?

    private let location: LocationProvider
    private let altimeter: AltimeterProvider
    private let meshExporter = MeshExporter()
    private let arQueue = DispatchQueue(label: "prodrive-scan.arsession")

    private var layout: BundleLayout?
    private var sampleLog: SampleLog?
    private var videoWriter: VideoWriter?
    private var depthWriter: DepthWriter?

    private var recording = false
    private var hasLidar = false
    private var frameIndex = 0
    private var startTimestamp = 0.0
    private var startDate = Date()
    private var depthHz = 0.0
    private var stats = CaptureStats()
    private var device = DeviceInfo(model: "", os: "", name: "", has_lidar: false)
    private var appVersion = ""

    /// Called (on the AR queue) with fresh stats; the coordinator hops to main before publishing.
    var onStats: ((CaptureStats) -> Void)?

    init(location: LocationProvider, altimeter: AltimeterProvider) {
        self.location = location
        self.altimeter = altimeter
        super.init()
    }

    /// Wire up to the preview view's session. Receives delegate callbacks on a private serial queue.
    func attach(to session: ARSession) {
        self.session = session
        session.delegate = self
        session.delegateQueue = arQueue
    }

    /// LiDAR mesh + sceneDepth available on this device (iPhone Pro / iPad Pro).
    static var lidarSupported: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
            && ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
    }

    /// Run the session for the live camera preview without writing anything.
    func startPreview() {
        guard let session else { return }
        let cfg = ARWorldTrackingConfiguration()
        cfg.worldAlignment = .gravity
        session.run(cfg)
    }

    func startRecording(device: DeviceInfo, appVersion: String, depthHz: Double,
                        videoTransform: CGAffineTransform) throws {
        guard let session else { throw CaptureError.noSession }
        let layout = BundleLayout()
        try layout.create()
        hasLidar = Self.lidarSupported

        self.layout = layout
        self.sampleLog = try SampleLog(url: layout.samplesURL)
        self.videoWriter = VideoWriter(url: layout.videoURL, transform: videoTransform)
        self.depthWriter = hasLidar ? DepthWriter(layout: layout, hz: depthHz) : nil
        self.depthHz = depthHz
        self.device = DeviceInfo(model: device.model, os: device.os, name: device.name, has_lidar: hasLidar)
        self.appVersion = appVersion

        let cfg = ARWorldTrackingConfiguration()
        cfg.worldAlignment = .gravity            // gravity-aligned, arbitrary yaw — fused via GPS on Mac
        if hasLidar {
            cfg.sceneReconstruction = .mesh
            cfg.frameSemantics.insert(.sceneDepth)
        }

        frameIndex = 0
        startTimestamp = 0
        startDate = Date()
        stats = CaptureStats()
        stats.hasLidar = hasLidar
        recording = true
        session.run(cfg, options: [.resetTracking, .removeExistingAnchors])
    }

    /// Stop, finalise every writer, and write manifest.json. Returns the bundle root, or nil.
    func stopRecording() -> URL? {
        guard recording, let layout else { return nil }
        session?.pause()

        var root: URL?
        arQueue.sync {                            // serialise after any in-flight frame callback
            recording = false
            let endDate = Date()

            videoWriter?.finish()
            let sampleCount = sampleLog?.finish() ?? 0
            let video = videoWriter
            let depth = depthWriter

            var mesh: MeshInfo?
            if hasLidar {
                let (v, f) = meshExporter.export(to: layout.meshURL)
                mesh = MeshInfo(file: SessionBundle.meshName, vertex_count: v, face_count: f,
                                frame: "arkit_world")
            }

            let wall = max(0.001, endDate.timeIntervalSince(startDate))
            let videoCount = video?.frameCount ?? 0
            let manifest = Manifest(
                schema_version: SessionBundle.schemaVersion,
                producer: SessionBundle.producer,
                app_version: appVersion,
                session_id: layout.id,
                started_at: Timestamps.iso(startDate),
                ended_at: Timestamps.iso(endDate),
                device: device,
                video: VideoInfo(file: SessionBundle.videoName, codec: "hevc",
                                 width: video?.width ?? 0, height: video?.height ?? 0,
                                 fps: (Double(videoCount) / wall).rounded(toPlaces: 1),
                                 frame_count: videoCount),
                depth: (hasLidar && (depth?.count ?? 0) > 0)
                    ? DepthInfo(dir: SessionBundle.depthDir, format: "f32_raw",
                                width: depth?.width ?? 0, height: depth?.height ?? 0,
                                count: depth?.count ?? 0, hz: depth?.hz ?? 0)
                    : nil,
                mesh: mesh,
                samples: SamplesInfo(file: SessionBundle.samplesName, count: sampleCount),
                coordinate_notes: SessionBundle.coordinateNotes)
            try? layout.writeManifest(manifest)
            root = layout.root
        }

        self.layout = nil
        self.sampleLog = nil
        self.videoWriter = nil
        self.depthWriter = nil
        return root
    }

    // MARK: ARSessionDelegate

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard recording else { return }
        if startTimestamp == 0 { startTimestamp = frame.timestamp }
        let t = frame.timestamp - startTimestamp
        let i = frameIndex
        frameIndex += 1

        videoWriter?.append(frame.capturedImage, at: t)

        var depthRef: String?
        if let dw = depthWriter, let sd = frame.sceneDepth {
            depthRef = dw.writeIfDue(sd.depthMap, frameIndex: i, time: t)
        }

        let K = frame.camera.intrinsics
        let sample = FrameSample(
            i: i, t: t,
            cam: frame.camera.transform.columnMajor,
            intr: [K.columns.0.x, K.columns.1.y, K.columns.2.x, K.columns.2.y],
            gps: location.latest(), baro: altimeter.latest(), depth: depthRef)
        sampleLog?.append(sample)

        stats.frames = i + 1
        stats.depthMaps = depthWriter?.count ?? 0
        stats.meshAnchors = meshExporter.anchorCount
        stats.gpsAccuracy = location.currentAccuracy()
        stats.elapsed = t
        if i % 10 == 0 { onStats?(stats) }
    }

    func session(_ session: ARSession, didAdd anchors: [ARAnchor]) {
        meshExporter.update(anchors.compactMap { $0 as? ARMeshAnchor })
    }

    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) {
        meshExporter.update(anchors.compactMap { $0 as? ARMeshAnchor })
    }

    func session(_ session: ARSession, didRemove anchors: [ARAnchor]) {
        meshExporter.remove(anchors.compactMap { ($0 as? ARMeshAnchor)?.identifier })
    }
}

// MARK: - small helpers

extension simd_float4x4 {
    /// 16 floats in column-major order — the layout ingest expects for `cam`.
    var columnMajor: [Float] {
        [columns.0.x, columns.0.y, columns.0.z, columns.0.w,
         columns.1.x, columns.1.y, columns.1.z, columns.1.w,
         columns.2.x, columns.2.y, columns.2.z, columns.2.w,
         columns.3.x, columns.3.y, columns.3.z, columns.3.w]
    }
}

extension Double {
    func rounded(toPlaces places: Int) -> Double {
        let p = pow(10.0, Double(places))
        return (self * p).rounded() / p
    }
}
