// SampleLog.swift — buffered writer for samples.jsonl (one compact JSON object per ARFrame).
//
// Writes happen on a private serial queue so the AR delegate thread is never blocked on disk I/O.
// Lines are flushed in batches to keep a 30–60 fps capture cheap.

import Foundation

final class SampleLog {
    private let handle: FileHandle
    private let queue = DispatchQueue(label: "prodrive-scan.samplelog")
    private let encoder: JSONEncoder
    private var buffer = Data()
    private var pending = 0
    private let flushEvery = 30          // ~once per second at 30 fps

    private(set) var count = 0          // total appended (read after stop on the writer queue)

    init(url: URL) throws {
        FileManager.default.createFile(atPath: url.path, contents: nil)
        self.handle = try FileHandle(forWritingTo: url)
        self.encoder = JSONEncoder()
        self.encoder.outputFormatting = [.withoutEscapingSlashes]
    }

    /// Encode + enqueue one sample. Non-blocking for the caller.
    func append(_ sample: FrameSample) {
        let line: Data
        do {
            var d = try encoder.encode(sample)
            d.append(0x0A)              // '\n'
            line = d
        } catch {
            return                      // a single un-encodable frame should never abort a capture
        }
        queue.async {
            self.buffer.append(line)
            self.count += 1
            self.pending += 1
            if self.pending >= self.flushEvery {
                self.flushLocked()
            }
        }
    }

    /// Flush everything and close. Returns the final line count (blocks until drained).
    @discardableResult
    func finish() -> Int {
        var total = 0
        queue.sync {
            self.flushLocked()
            try? self.handle.close()
            total = self.count
        }
        return total
    }

    private func flushLocked() {
        guard !buffer.isEmpty else { return }
        handle.write(buffer)
        buffer.removeAll(keepingCapacity: true)
        pending = 0
    }
}
