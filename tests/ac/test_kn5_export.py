"""Bpy-free kn5 exporter units — proven by round-tripping through the extract_kn5 reader.

The reader (scripts.modkit.extract_kn5) is the format's other half, so a written kn5 that parses
back to the same geometry/materials/textures is byte-format-correct. Pure-Python (tempfile), runs
under tests/run_tests.py and pytest. In-AC *visual* correctness (UV V, lighting) is a Mac step.
"""

import json
import struct
import tempfile
from pathlib import Path

from scripts.ac import kn5_export
from scripts.modkit import extract_kn5


# --- helpers -------------------------------------------------------------------

def _project(tmp: Path, *, track_obj: str, dummies: dict | None = None, capture: dict | None = None,
             slug: str = "t") -> Path:
    proj = tmp / "proj"
    (proj / "data").mkdir(parents=True)
    (proj / "track.config.json").write_text(json.dumps({"slug": slug, "name": slug}))
    (proj / "data" / "track.obj").write_text(track_obj)
    if dummies is not None:
        (proj / "data" / "dummies.json").write_text(json.dumps(dummies))
    if capture is not None:
        (proj / "source").mkdir(parents=True, exist_ok=True)
        (proj / "source" / "realworld_capture.json").write_text(json.dumps(capture))
    return proj


# a single quad named 1ROAD_x (so it maps to the asphalt material in pbr.TEXTURES)
_QUAD = """\
o 1ROAD_x
v 0 0 0
v 1 0 0
v 1 0 1
v 0 0 1
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 1 0
vn 0 1 0
vn 0 1 0
vn 0 1 0
f 1/1/1 2/2/2 3/3/3 4/4/4
"""


# --- OBJ parsing ---------------------------------------------------------------

def test_parse_obj_fan_triangulates_quad():
    obj = kn5_export.parse_obj(_QUAD)
    assert len(obj.objects) == 1
    assert obj.objects[0].name == "1ROAD_x"
    assert len(obj.objects[0].tris) == 2  # quad -> 2 triangles
    assert len(obj.positions) == 4 and len(obj.uvs) == 4 and len(obj.normals) == 4


def test_parse_obj_groups_split_objects():
    text = "o a\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\no b\nv 0 0 1\nv 1 0 1\nv 0 1 1\nf 4 5 6\n"
    obj = kn5_export.parse_obj(text)
    assert [o.name for o in obj.objects] == ["a", "b"]
    assert all(len(o.tris) == 1 for o in obj.objects)


# --- vertex assembly -----------------------------------------------------------

def test_build_mesh_dedups_shared_corners():
    obj = kn5_export.parse_obj(_QUAD)
    meshes = kn5_export.build_mesh(obj.objects[0], obj, material_id=0)
    assert len(meshes) == 1
    # quad shares 4 unique corners; 2 tris -> 6 indices but only 4 vertices
    assert len(meshes[0].vertices) == 4
    assert len(meshes[0].indices) == 6


def test_build_mesh_flips_uv_v_by_default():
    obj = kn5_export.parse_obj(_QUAD)
    flipped = kn5_export.build_mesh(obj.objects[0], obj, 0, flip_uv_v=True)[0]
    plain = kn5_export.build_mesh(obj.objects[0], obj, 0, flip_uv_v=False)[0]
    assert {round(v.uv[1], 5) for v in flipped.vertices} == {0.0, -1.0}
    assert {round(v.uv[1], 5) for v in plain.vertices} == {0.0, 1.0}


def test_build_mesh_computes_face_normal_without_vn():
    text = "o a\nv 0 0 0\nv 1 0 0\nv 0 0 1\nf 1 2 3\n"  # CW/CCW in XZ plane, no vn
    obj = kn5_export.parse_obj(text)
    mesh = kn5_export.build_mesh(obj.objects[0], obj, 0)[0]
    # all normals should be unit-length and parallel to Y (the triangle lies in the XZ plane)
    for v in mesh.vertices:
        assert abs(abs(v.normal[1]) - 1.0) < 1e-5


def test_split_for_vertex_limit(monkeypatch=None):
    # synthetic mesh over a tiny limit -> multiple sub-meshes, indices re-based per sub-mesh
    orig = kn5_export.VERTEX_LIMIT
    kn5_export.VERTEX_LIMIT = 6
    try:
        verts = [kn5_export.Vertex((float(i), 0, 0), (0, 1, 0), (0, 0)) for i in range(12)]
        idx = []
        for i in range(0, 12, 3):
            idx += [i, i + 1, i + 2]
        mesh = kn5_export.Mesh("big", 0, verts, idx)
        parts = kn5_export._split_for_vertex_limit(mesh)
        assert len(parts) > 1
        for p in parts:
            assert len(p.vertices) <= kn5_export.VERTEX_LIMIT
            assert max(p.indices) < len(p.vertices)  # re-indexed within the sub-mesh
    finally:
        kn5_export.VERTEX_LIMIT = orig


# --- materials -----------------------------------------------------------------

def test_material_for_road_prefix():
    mat, sources = kn5_export.material_for("1ROAD_main", overrides={})
    assert mat.name == "1ROAD_main_mat"
    assert mat.shader == "ksPerPixelMultiMap"  # has a normal map
    assert mat.alpha_tested is False
    assert "txDiffuse" in mat.texture_mapping and "txNormal" in mat.texture_mapping


def test_material_for_billboard_is_alpha_tested():
    mat, _ = kn5_export.material_for("TREES_01", overrides={})
    assert mat.shader == "ksTree"
    assert mat.alpha_tested is True
    assert mat.alpha_blend == kn5_export.BLEND_MODE["AlphaToCoverage"]


def test_material_for_override_swaps_texture(tmp_path=None):
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "captured_road.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        mat, sources = kn5_export.material_for(
            "1ROAD_x", overrides={"1ROAD": {"diffuse": str(png)}})
        assert mat.texture_mapping["txDiffuse"] == "captured_road.png"
        assert sources["captured_road.png"] == str(png)


# --- full write -> read round-trip --------------------------------------------

def test_roundtrip_geometry_and_material():
    with tempfile.TemporaryDirectory() as td:
        proj = _project(Path(td), track_obj=_QUAD)
        out = kn5_export.export(proj)
        assert out.read_bytes()[:6] == kn5_export.KN5_MAGIC

        parsed = extract_kn5.parse(out)
        assert parsed["version"] == 5
        assert len(parsed["meshes"]) == 1
        mesh = parsed["meshes"][0]
        assert mesh["name"] == "1ROAD_x"
        assert len(mesh["verts"]) == 4
        assert len(mesh["idx"]) == 6
        # positions survive unchanged (net OBJ->kn5 transform is identity)
        got = {(round(x, 4), round(y, 4), round(z, 4)) for (x, y, z, _u, _v) in mesh["verts"]}
        assert got == {(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)}
        # material assigned and named by prefix
        mat = parsed["materials"][mesh["matid"]]
        assert mat["name"] == "1ROAD_x_mat"
        assert mat["shader"] == "ksPerPixelMultiMap"


def test_roundtrip_embeds_real_textures():
    # 1ROAD maps to assets/textures/asphalt_cracked_{diffuse,normal} which exist in-repo
    with tempfile.TemporaryDirectory() as td:
        proj = _project(Path(td), track_obj=_QUAD)
        out = kn5_export.export(proj)
        parsed = extract_kn5.parse(out)
        names = set(parsed["textures"])
        assert "asphalt_cracked_diffuse.jpg" in names
        assert "asphalt_cracked_normal.jpg" in names
        # embedded bytes equal the on-disk source
        src = (Path(kn5_export.pbr.texture_dir()) / "asphalt_cracked_diffuse.jpg").read_bytes()
        assert parsed["textures"]["asphalt_cracked_diffuse.jpg"] == src


def test_roundtrip_override_texture_embedded():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        png = tmp / "cap.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"ROADDATA" * 8)
        capture = {"texture_overrides": [{"material": "1ROAD", "diffuse": "cap.png"}]}
        # capture paths resolve relative to the project, so place cap.png in the project root
        proj = _project(tmp, track_obj=_QUAD, capture=capture)
        (proj / "cap.png").write_bytes(png.read_bytes())
        out = kn5_export.export(proj)
        parsed = extract_kn5.parse(out)
        assert "cap.png" in parsed["textures"]
        assert parsed["textures"]["cap.png"] == png.read_bytes()


def test_roundtrip_dummies_become_nodes():
    with tempfile.TemporaryDirectory() as td:
        dummies = {"AC_START_0": [3.0, 0.5, -2.0], "AC_PIT_0": [4.0, 0.5, -2.0]}
        proj = _project(Path(td), track_obj=_QUAD, dummies=dummies)
        out = kn5_export.export(proj)
        parsed = extract_kn5.parse(out)
        names = {m["name"] for m in parsed["meshes"]}
        assert {"AC_START_0", "AC_PIT_0"} <= names
        # dummy position written straight through (no conversion), within the tri's first vertex
        start = next(m for m in parsed["meshes"] if m["name"] == "AC_START_0")
        x, y, z, _u, _v = start["verts"][0]
        assert (round(x, 3), round(y, 3), round(z, 3)) == (3.0, 0.5, -2.0)


def test_header_and_version_bytes():
    with tempfile.TemporaryDirectory() as td:
        proj = _project(Path(td), track_obj=_QUAD)
        payload = kn5_export.build_kn5_bytes(proj)[0]
        assert payload[:6] == b"sc6969"
        assert struct.unpack_from("<I", payload, 6)[0] == 5
