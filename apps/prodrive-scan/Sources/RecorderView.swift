// RecorderView.swift — the single capture screen: live AR preview, status HUD, record button.

import ARKit
import SwiftUI

struct RecorderView: View {
    @StateObject private var coordinator = CaptureCoordinator()

    var body: some View {
        ZStack {
            ARPreview(controller: coordinator.controller)
                .ignoresSafeArea()

            VStack {
                statusHUD
                Spacer()
                if let bundle = coordinator.lastBundle, !coordinator.isRecording {
                    savedBanner(bundle)
                }
                HStack {
                    Spacer()
                    recordButton
                }
            }
            .padding()
        }
        .onAppear { coordinator.onAppear() }
        .statusBarHidden(true)
    }

    // MARK: HUD

    private var statusHUD: some View {
        // Card hugs its content (background wraps the VStack); the spacers keep it pinned top-left.
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                if coordinator.isRecording {
                    Label(timeString(coordinator.stats.elapsed), systemImage: "record.circle.fill")
                        .foregroundStyle(.red)
                        .font(.headline.monospacedDigit())
                }
                hudRow("Frames", "\(coordinator.stats.frames)")
                hudRow("GPS", gpsString(coordinator.stats.gpsAccuracy))
                if coordinator.lidarAvailable {
                    hudRow("LiDAR", "\(coordinator.stats.depthMaps) maps · \(coordinator.stats.meshAnchors) mesh")
                } else {
                    hudRow("LiDAR", "unavailable")
                }
            }
            .fixedSize()
            .font(.subheadline.monospacedDigit())
            .padding(12)
            .background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 12))
            .foregroundStyle(.white)

            Spacer(minLength: 0)
        }
    }

    private func hudRow(_ label: String, _ value: String) -> some View {
        HStack(spacing: 8) {
            Text(label).foregroundStyle(.white.opacity(0.6))
            Text(value)
        }
    }

    private func savedBanner(_ bundle: String) -> some View {
        Label("Saved \(bundle)", systemImage: "checkmark.circle.fill")
            .font(.footnote)
            .padding(8)
            .background(.green.opacity(0.85), in: Capsule())
            .foregroundStyle(.white)
            .padding(.bottom, 8)
    }

    private var recordButton: some View {
        Button(action: coordinator.toggle) {
            ZStack {
                Circle().stroke(.white, lineWidth: 5).frame(width: 78, height: 78)
                RoundedRectangle(cornerRadius: coordinator.isRecording ? 6 : 33)
                    .fill(.red)
                    .frame(width: coordinator.isRecording ? 34 : 66,
                           height: coordinator.isRecording ? 34 : 66)
                    .animation(.easeInOut(duration: 0.2), value: coordinator.isRecording)
            }
        }
        .padding(.bottom, 24)
    }

    private func timeString(_ s: Double) -> String {
        String(format: "%02d:%02d", Int(s) / 60, Int(s) % 60)
    }

    private func gpsString(_ acc: Double) -> String {
        acc >= .greatestFiniteMagnitude / 2 ? "no fix" : String(format: "±%.0f m", acc)
    }
}

/// Bridges an ARSCNView into SwiftUI. The view owns the ARSession; we attach the controller as its
/// session delegate and start the preview.
struct ARPreview: UIViewRepresentable {
    let controller: ARCaptureController

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        view.automaticallyUpdatesLighting = true
        controller.attach(to: view.session)
        controller.startPreview()
        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}
}
