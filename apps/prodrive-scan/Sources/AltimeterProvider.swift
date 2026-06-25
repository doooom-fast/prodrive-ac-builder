// AltimeterProvider.swift — barometric relative altitude + pressure, sampled by the AR loop.
//
// CMAltimeter's relative altitude is referenced to the start of updates (so it is per-session, not
// MSL). It's far smoother than GPS altitude, which is why ingest prefers it for road grade. Pressure
// is reported in kPa.

import CoreMotion

final class AltimeterProvider {
    private let altimeter = CMAltimeter()
    private let queue = OperationQueue()
    private let lock = NSLock()
    private var sample: BaroSample?
    private(set) var available = false

    init() {
        queue.name = "prodrive-scan.altimeter"
        queue.maxConcurrentOperationCount = 1
    }

    func start() {
        guard CMAltimeter.isRelativeAltitudeAvailable() else { return }
        available = true
        altimeter.startRelativeAltitudeUpdates(to: queue) { [weak self] data, _ in
            guard let self, let data else { return }
            let s = BaroSample(rel_alt_m: data.relativeAltitude.doubleValue,
                               pressure_kpa: data.pressure.doubleValue)
            self.lock.lock(); self.sample = s; self.lock.unlock()
        }
    }

    func stop() {
        if available { altimeter.stopRelativeAltitudeUpdates() }
    }

    func latest() -> BaroSample? {
        lock.lock(); defer { lock.unlock() }
        return sample
    }
}
