// CaptureCoordinator.swift — the @MainActor brain the SwiftUI view binds to.
//
// Owns the providers + AR controller, exposes record state and live stats, and turns the AR queue's
// stats callbacks into @Published updates on the main thread.

import ARKit
import SwiftUI
import UIKit

@MainActor
final class CaptureCoordinator: ObservableObject {
    @Published var isRecording = false
    @Published var stats = CaptureStats()
    @Published var lastBundle: String?
    @Published var errorMessage: String?

    let lidarAvailable = ARCaptureController.lidarSupported
    let controller: ARCaptureController

    private let location = LocationProvider()
    private let altimeter = AltimeterProvider()

    static let depthHz = 4.0   // throttled per-frame depth — the capture-plan decision

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
    }

    init() {
        controller = ARCaptureController(location: location, altimeter: altimeter)
        controller.onStats = { [weak self] s in
            Task { @MainActor in self?.stats = s }
        }
    }

    /// Start sensors + live preview when the screen appears.
    func onAppear() {
        location.start()
        altimeter.start()
        controller.startPreview()
    }

    func toggle() { isRecording ? stop() : start() }

    private func start() {
        do {
            try controller.startRecording(device: DeviceID.info(hasLidar: lidarAvailable),
                                          appVersion: appVersion, depthHz: Self.depthHz)
            stats = CaptureStats()
            stats.hasLidar = lidarAvailable
            errorMessage = nil
            isRecording = true
        } catch {
            errorMessage = "Couldn't start recording: \(error.localizedDescription)"
            isRecording = false
        }
    }

    private func stop() {
        let url = controller.stopRecording()
        isRecording = false
        lastBundle = url?.lastPathComponent
        controller.startPreview()   // resume the live preview
    }
}

/// Hardware identity for the manifest (read on the main thread, then handed to the AR controller).
enum DeviceID {
    static func info(hasLidar: Bool) -> DeviceInfo {
        DeviceInfo(model: modelIdentifier,
                   os: "\(UIDevice.current.systemName) \(UIDevice.current.systemVersion)",
                   name: UIDevice.current.name,
                   has_lidar: hasLidar)
    }

    static var modelIdentifier: String {
        var sys = utsname()
        uname(&sys)
        return Mirror(reflecting: sys.machine).children.reduce(into: "") { acc, el in
            if let v = el.value as? Int8, v != 0 { acc.append(Character(UnicodeScalar(UInt8(v)))) }
        }
    }
}
