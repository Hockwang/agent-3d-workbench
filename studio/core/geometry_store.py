"""Keep float64 editing geometry inside a standard, viewable GLB asset.

glTF renders its usual float32 POSITION accessor. An application-specific extras
entry points to unused buffer views containing the authoritative geometry. Other
viewers ignore these views; old workbench GLBs without them remain readable.
"""

import json
import struct

import numpy as np
import trimesh

KEY = "workbench_geometry64"


def encode(mesh):
    raw = trimesh.Scene(mesh).export(file_type="glb")
    if np.array_equal(mesh.vertices, np.asarray(mesh.vertices, dtype=np.float32)):
        return raw
    size = struct.unpack_from("<I", raw, 12)[0]
    document = json.loads(raw[20 : 20 + size])
    binary = bytearray(raw[28 + size :])
    binary.extend(b"\0" * (-len(binary) % 8))
    views = document.setdefault("bufferViews", [])
    refs = []
    for array in (np.asarray(mesh.vertices, dtype="<f8"), np.asarray(mesh.faces, dtype="<u4")):
        refs.append(len(views))
        data = array.tobytes()
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
        binary.extend(data)
    document.setdefault("extras", {})[KEY] = {
        "version": 1,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "positionsView": refs[0],
        "trianglesView": refs[1],
    }
    document["buffers"][0]["byteLength"] = len(binary)
    encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary.extend(b"\0" * (-len(binary) % 4))
    return (
        struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def restore(raw, mesh):
    size = struct.unpack_from("<I", raw, 12)[0]
    document = json.loads(raw[20 : 20 + size])
    record = document.get("extras", {}).get(KEY)
    if record is None:
        return mesh
    if record.get("version") != 1:
        raise ValueError("Unsupported exact geometry version")
    binary = memoryview(raw)[28 + size :]
    arrays = []
    for count_key, view_key, dtype in [("vertices", "positionsView", "<f8"), ("faces", "trianglesView", "<u4")]:
        count = record[count_key]
        if type(count) is not int or not 0 < count <= 15_000_000:
            raise ValueError("Invalid exact geometry count")
        index = record[view_key]
        if type(index) is not int or not 0 <= index < len(document["bufferViews"]):
            raise ValueError("Invalid exact geometry view index")
        view = document["bufferViews"][index]
        offset, length = view.get("byteOffset", 0), view["byteLength"]
        if (
            type(offset) is not int
            or type(length) is not int
            or view["buffer"] != 0
            or offset < 0
            or length != count * 3 * np.dtype(dtype).itemsize
            or offset + length > len(binary)
        ):
            raise ValueError("Invalid exact geometry buffer")
        arrays.append(np.frombuffer(binary[offset : offset + length], dtype=dtype).reshape(-1, 3).copy())
    vertices, faces = arrays
    if not np.isfinite(vertices).all() or faces.max() >= len(vertices):
        raise ValueError("Invalid exact geometry indices or positions")
    if len(vertices) != len(mesh.vertices) or len(faces) != len(mesh.faces):
        raise ValueError("Exact geometry does not match preview vertex/face counts")
    # Restoring precision keeps vertex/face order; retain the GLB's shading.
    # Assigning geometry invalidates Trimesh's imported-normal cache.
    normals = mesh.vertex_normals.copy() if "vertex_normals" in mesh._cache else None
    mesh.vertices = vertices
    mesh.faces = faces
    if normals is not None:
        mesh.vertex_normals = normals
    return mesh


def stl_bytes(mesh):
    """Use binary when it preserves distinct positions, ASCII when it cannot."""
    vertices = np.asarray(mesh.vertices)
    if np.array_equal(vertices, vertices.astype(np.float32)):
        return mesh.export(file_type="stl")
    source_unique = len(np.unique(vertices, axis=0))
    float32_unique = len(np.unique(vertices.astype(np.float32), axis=0))
    if float32_unique < source_unique:
        return mesh.export(file_type="stl_ascii").encode("utf-8")
    return mesh.export(file_type="stl")
