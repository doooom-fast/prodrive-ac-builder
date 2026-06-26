// VideoWriter.swift — encodes ARFrame.capturedImage to an HEVC .mov via AVAssetWriter.
//
// Lazily initialised on the first frame so the encoder is sized to the actual capture resolution.
// Presentation times are relative to the session start (seconds), matching the `t` field in
// samples.jsonl, so the Mac can seek the video by a sample's timestamp. Frames offered while the
// encoder is busy are dropped (pose/GPS for that frame are still logged).

import AVFoundation
import CoreVideo

final class VideoWriter {
    private(set) var width = 0
    private(set) var height = 0
    private(set) var frameCount = 0

    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var started = false
    private let url: URL
    private let transform: CGAffineTransform   // rotates the landscape-native frame upright for the mount
    private(set) var lastError: String?        // surfaced if the encoder fails mid-recording

    init(url: URL, transform: CGAffineTransform) {
        self.url = url
        self.transform = transform
    }

    /// Append one frame at `time` seconds since session start. Safe to call before/while configuring.
    func append(_ pixelBuffer: CVPixelBuffer, at time: Double) {
        if writer == nil { configure(with: pixelBuffer) }
        guard let writer, let input, let adaptor else { return }

        let pts = CMTime(seconds: max(0, time), preferredTimescale: 1_000_000)
        if !started {
            writer.startWriting()
            writer.startSession(atSourceTime: pts)
            started = true
        }
        if writer.status == .failed {
            if lastError == nil { lastError = writer.error?.localizedDescription ?? "encoder failed" }
            return
        }
        guard writer.status == .writing, input.isReadyForMoreMediaData else { return }
        if adaptor.append(pixelBuffer, withPresentationTime: pts) {
            frameCount += 1
        }
    }

    /// Finish encoding and block until the file is finalised. Even if this never runs (crash/kill) or
    /// the writer has failed, the fragmented-MP4 stream written so far is still playable.
    func finish() {
        guard let writer, let input, started else { return }
        guard writer.status == .writing else {
            lastError = writer.error?.localizedDescription ?? "writer not writing (status \(writer.status.rawValue))"
            return
        }
        input.markAsFinished()
        let sema = DispatchSemaphore(value: 0)
        writer.finishWriting { sema.signal() }
        sema.wait()
        if writer.status == .failed { lastError = writer.error?.localizedDescription ?? "finishWriting failed" }
    }

    private func configure(with pixelBuffer: CVPixelBuffer) {
        width = CVPixelBufferGetWidth(pixelBuffer)
        height = CVPixelBufferGetHeight(pixelBuffer)
        let pixelFormat = CVPixelBufferGetPixelFormatType(pixelBuffer)

        guard let writer = try? AVAssetWriter(outputURL: url, fileType: .mov) else { return }
        // Fragmented MP4: write a moov up front + a moof fragment every few seconds, so the file stays
        // PLAYABLE even if finishWriting never completes or the app is killed. Without this, an
        // unfinalised capture is a dead `ftyp+mdat` with no moov (the whole 32-min first capture was lost
        // this way). 6 s keeps the fragment overhead negligible.
        writer.movieFragmentInterval = CMTime(seconds: 6, preferredTimescale: 600)
        let settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.hevc,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
        ]
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        input.expectsMediaDataInRealTime = true
        // ARKit's capturedImage is landscape-native; tag with the mount-derived rotation so it plays level.
        input.transform = transform

        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: pixelFormat,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ])

        guard writer.canAdd(input) else { return }
        writer.add(input)
        self.writer = writer
        self.input = input
        self.adaptor = adaptor
    }
}
