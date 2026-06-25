// MeshExporter.swift — accumulates ARKit scene-reconstruction anchors into one fused OBJ.
//
// ARKit hands us LiDAR mesh as a set of ARMeshAnchors that grow/refine over the session. We keep the
// latest geometry per anchor and, at stop, bake every vertex into ARKit world space and write a single
// OBJ (manifest.mesh.frame = "arkit_world"). That fused mesh is the seed for later prop extraction.

import ARKit
import simd

final class MeshExporter {
    private var anchors: [UUID: ARMeshAnchor] = [:]
    private let lock = NSLock()

    /// Add/replace anchors as ARKit adds or updates them.
    func update(_ meshAnchors: [ARMeshAnchor]) {
        lock.lock(); for a in meshAnchors { anchors[a.identifier] = a }; lock.unlock()
    }

    func remove(_ ids: [UUID]) {
        lock.lock(); for id in ids { anchors[id] = nil }; lock.unlock()
    }

    var anchorCount: Int { lock.lock(); defer { lock.unlock() }; return anchors.count }

    /// Bake all anchors to world space and write one OBJ. Returns (vertexCount, faceCount).
    @discardableResult
    func export(to url: URL) -> (vertices: Int, faces: Int) {
        lock.lock(); let snapshot = Array(anchors.values); lock.unlock()

        var obj = "o prodrive_scan_mesh\n"
        var vTotal = 0, fTotal = 0, vBase = 0

        for anchor in snapshot {
            let geom = anchor.geometry
            let verts = geom.vertices
            let vptr = verts.buffer.contents()
            let xform = anchor.transform

            for i in 0..<verts.count {
                let p = vptr.advanced(by: verts.offset + verts.stride * i)
                    .assumingMemoryBound(to: Float.self)
                let world = xform * simd_float4(p[0], p[1], p[2], 1)
                obj += "v \(world.x) \(world.y) \(world.z)\n"
            }

            let faces = geom.faces
            // ARKit indexes triangles with UInt32; skip anything else rather than misread bytes.
            if faces.bytesPerIndex == MemoryLayout<UInt32>.size && faces.indexCountPerPrimitive == 3 {
                let fptr = faces.buffer.contents()
                for f in 0..<faces.count {
                    let a = fptr.load(fromByteOffset: (f * 3 + 0) * 4, as: UInt32.self)
                    let b = fptr.load(fromByteOffset: (f * 3 + 1) * 4, as: UInt32.self)
                    let c = fptr.load(fromByteOffset: (f * 3 + 2) * 4, as: UInt32.self)
                    obj += "f \(Int(a) + 1 + vBase) \(Int(b) + 1 + vBase) \(Int(c) + 1 + vBase)\n"
                    fTotal += 1
                }
            }
            vBase += verts.count
            vTotal += verts.count
        }

        try? obj.write(to: url, atomically: true, encoding: .utf8)
        return (vTotal, fTotal)
    }
}
