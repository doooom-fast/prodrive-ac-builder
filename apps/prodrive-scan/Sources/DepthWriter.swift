// DepthWriter.swift — persists throttled ARKit sceneDepth maps as raw Float32.
//
// Per the capture plan we keep depth at a few Hz (not every frame) — a balance between detail and the
// multi-GB-per-lap bundle size. Each file is the depthMap's row-major little-endian Float32 buffer;
// width/height/format live once in manifest.depth so the files stay header-free. A LiDAR depthMap is
// kCVPixelFormatType_DepthFloat32 at 256×192.

import CoreVideo
import Foundation

final class DepthWriter {
    private let layout: BundleLayout
    private let minInterval: Double         // seconds between persisted depth maps
    private var lastWrite = -Double.greatestFiniteMagnitude

    private(set) var width = 0
    private(set) var height = 0
    private(set) var count = 0

    init(layout: BundleLayout, hz: Double) {
        self.layout = layout
        self.minInterval = hz > 0 ? 1.0 / hz : .greatestFiniteMagnitude
    }

    var hz: Double { minInterval > 0 ? 1.0 / minInterval : 0 }

    /// Write this frame's depth if enough time has elapsed. Returns the relative ref to log, or nil.
    func writeIfDue(_ depthMap: CVPixelBuffer, frameIndex: Int, time: Double) -> String? {
        guard time - lastWrite >= minInterval else { return nil }
        lastWrite = time

        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(depthMap) else { return nil }

        let w = CVPixelBufferGetWidth(depthMap)
        let h = CVPixelBufferGetHeight(depthMap)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(depthMap)
        let rowBytes = w * MemoryLayout<Float32>.size
        width = w; height = h

        let (rel, url) = layout.depthRef(frameIndex)
        var data = Data(capacity: rowBytes * h)
        // Copy row by row to drop any stride padding → a clean w*h*4 byte blob.
        for row in 0..<h {
            let src = base.advanced(by: row * bytesPerRow)
            data.append(Data(bytes: src, count: rowBytes))
        }
        do {
            try data.write(to: url)
            count += 1
            return rel
        } catch {
            return nil
        }
    }
}
