// SessionBundle.swift — the on-disk session bundle (schema v1) the Mac pipeline ingests.
//
// This is the Swift half of the contract defined in scripts/capture/bundle.py. `schemaVersion`
// MUST match `SCHEMA_VERSION` there; bump both together. The bundle is a plain directory under the
// app's Documents folder so it is reachable over Finder (USB), the Files app, and AirDrop.

import Foundation

/// Codable models + directory layout for one capture session.
enum SessionBundle {
    /// Must equal `scripts/capture/bundle.py: SCHEMA_VERSION`.
    static let schemaVersion = 1
    static let producer = "prodrive-scan"

    static let manifestName = "manifest.json"
    static let samplesName = "samples.jsonl"
    static let depthDir = "depth"
    static let meshName = "mesh.obj"
    static let videoName = "video.mov"

    static let coordinateNotes =
        "ARKit world is gravity-aligned with an arbitrary yaw at session start; GPS is WGS84. " +
        "Fuse the capture to a track on the Mac via GPS+trueHeading (see scripts/capture/ingest.py)."
}

// MARK: - manifest.json

struct DeviceInfo: Codable {
    let model: String
    let os: String
    let name: String
    let has_lidar: Bool
}

struct VideoInfo: Codable {
    let file: String
    let codec: String
    let width: Int
    let height: Int
    let fps: Double
    let frame_count: Int
}

struct DepthInfo: Codable {
    let dir: String
    let format: String      // "f32_raw" — row-major little-endian Float32, dims here
    let width: Int
    let height: Int
    let count: Int
    let hz: Double
}

struct MeshInfo: Codable {
    let file: String
    let vertex_count: Int
    let face_count: Int
    let frame: String       // "arkit_world"
}

struct SamplesInfo: Codable {
    let file: String
    let count: Int
}

struct Manifest: Codable {
    let schema_version: Int
    let producer: String
    let app_version: String
    let session_id: String
    let started_at: String
    let ended_at: String
    let device: DeviceInfo
    let video: VideoInfo
    let depth: DepthInfo?
    let mesh: MeshInfo?
    let samples: SamplesInfo
    let coordinate_notes: String
}

// MARK: - samples.jsonl (one record per ARFrame)

struct GPSSample: Codable {
    let lat: Double
    let lon: Double
    let alt: Double?
    let hacc: Double?
    let vacc: Double?
    let head_true: Double?
    let speed: Double?
}

struct BaroSample: Codable {
    let rel_alt_m: Double?
    let pressure_kpa: Double?
}

/// One synchronized frame log. `cam` is a column-major 4×4 (ARFrame.camera.transform), ARKit world.
struct FrameSample: Codable {
    let i: Int
    let t: Double
    let cam: [Float]
    let intr: [Float]       // [fx, fy, cx, cy]
    let gps: GPSSample?
    let baro: BaroSample?
    let depth: String?      // relative path to a depth map, or nil on non-depth frames
}

// MARK: - directory

/// Creates and addresses the files inside one bundle directory.
struct BundleLayout {
    let root: URL
    let id: String

    init() {
        let stamp = Timestamps.filenameStamp(Date())
        let short = String(UUID().uuidString.prefix(6)).lowercased()
        self.id = "prodrive-scan-\(stamp)-\(short)"
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        self.root = docs.appendingPathComponent(id, isDirectory: true)
    }

    func create() throws {
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: depthDirURL, withIntermediateDirectories: true)
    }

    var videoURL: URL { root.appendingPathComponent(SessionBundle.videoName) }
    var samplesURL: URL { root.appendingPathComponent(SessionBundle.samplesName) }
    var meshURL: URL { root.appendingPathComponent(SessionBundle.meshName) }
    var manifestURL: URL { root.appendingPathComponent(SessionBundle.manifestName) }
    var depthDirURL: URL { root.appendingPathComponent(SessionBundle.depthDir, isDirectory: true) }

    /// Relative path (as stored in a FrameSample.depth) and absolute URL for a depth frame.
    func depthRef(_ frameIndex: Int) -> (rel: String, url: URL) {
        let name = String(format: "%06d.depthf32", frameIndex)
        return ("\(SessionBundle.depthDir)/\(name)", depthDirURL.appendingPathComponent(name))
    }

    func writeManifest(_ manifest: Manifest) throws {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        try enc.encode(manifest).write(to: manifestURL)
    }
}

enum Timestamps {
    /// Filename-safe UTC stamp (no colons), e.g. 20260625T141233Z.
    static func filenameStamp(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        return f.string(from: date)
    }

    /// Standard ISO8601 (with colons) for manifest started_at / ended_at, e.g. 2026-06-25T14:12:33Z.
    static func iso(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }
}
