// ProdriveScanApp.swift — entry point for Prodrive Scan, the track-agnostic capture app.
//
// One screen, one job: record a windshield run (video + 6DoF pose + GPS + barometer + LiDAR) into a
// session bundle the Prodrive AC Builder Mac pipeline ingests. The app has zero track knowledge.

import SwiftUI

@main
struct ProdriveScanApp: App {
    var body: some Scene {
        WindowGroup {
            RecorderView()
        }
    }
}
