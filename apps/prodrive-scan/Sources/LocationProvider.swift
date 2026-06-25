// LocationProvider.swift — latest GPS fix + true heading, sampled by the AR loop.
//
// CoreLocation pushes updates on its own cadence (~1 Hz); the AR delegate reads `latest()` every
// frame and stamps it onto that frame's sample. We keep the most recent location + heading and let
// the frame log carry-forward — fusion on the Mac only needs the fixes, not a fix per frame.

import CoreLocation

final class LocationProvider: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let lock = NSLock()
    private var location: CLLocation?
    private var headingTrue: Double?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
        manager.activityType = .automotiveNavigation
        manager.distanceFilter = kCLDistanceFilterNone
    }

    func start() {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
        if CLLocationManager.headingAvailable() {
            manager.startUpdatingHeading()
        }
    }

    func stop() {
        manager.stopUpdatingLocation()
        manager.stopUpdatingHeading()
    }

    /// Snapshot for the current frame, or nil if no fix yet.
    func latest() -> GPSSample? {
        lock.lock(); defer { lock.unlock() }
        guard let loc = location else { return nil }
        return GPSSample(
            lat: loc.coordinate.latitude,
            lon: loc.coordinate.longitude,
            alt: loc.verticalAccuracy >= 0 ? loc.altitude : nil,
            hacc: loc.horizontalAccuracy,
            vacc: loc.verticalAccuracy >= 0 ? loc.verticalAccuracy : nil,
            head_true: headingTrue,
            speed: loc.speed >= 0 ? loc.speed : nil)
    }

    /// Best available horizontal accuracy so far (for the live HUD). Large if no fix.
    func currentAccuracy() -> Double {
        lock.lock(); defer { lock.unlock() }
        return location?.horizontalAccuracy ?? .greatestFiniteMagnitude
    }

    // MARK: CLLocationManagerDelegate

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        lock.lock(); location = loc; lock.unlock()
    }

    func locationManager(_ manager: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        guard newHeading.trueHeading >= 0 else { return }   // -1 until calibrated
        lock.lock(); headingTrue = newHeading.trueHeading; lock.unlock()
    }
}
