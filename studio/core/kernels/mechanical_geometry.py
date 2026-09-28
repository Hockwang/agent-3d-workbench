"""Millimetre solid tools. No case-specific imports or implicit mesh repair."""

from pathlib import Path
import hashlib
import json
import numpy as np
import manifold3d as mf
import trimesh


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def unit(v):
    v = np.asarray(v, float)
    if v.shape != (3,) or not np.isfinite(v).all() or np.linalg.norm(v) < 1e-8:
        raise ValueError("direction must be a finite nonzero 3-vector")
    return v / np.linalg.norm(v)


def frame(z, x_hint=(1, 0, 0)):
    z = unit(z)
    x = np.asarray(x_hint, float) - z * np.dot(x_hint, z)
    if np.linalg.norm(x) < 1e-6:
        hint = np.eye(3)[np.argmin(abs(z))]
        x = hint - z * np.dot(hint, z)
    x = unit(x)
    return np.column_stack([x, np.cross(z, x), z])


def transform(s, R, center=(0, 0, 0)):
    return s.transform(np.c_[R, center])


def rotation(axis, angle, center=(0, 0, 0)):
    return trimesh.transformations.rotation_matrix(np.deg2rad(angle), unit(axis), center)


def mesh(s):
    if s.status() != mf.Error.NoError or s.is_empty() or s.volume() <= 0:
        raise ValueError(f"invalid solid: {s.status()} / {s.volume()}")
    m = s.to_mesh64()
    return trimesh.Trimesh(m.vert_properties[:, :3], m.tri_verts, process=False)


def solid(m):
    v, inv = np.unique(np.asarray(m.vertices), axis=0, return_inverse=True)
    s = mf.Manifold(mf.Mesh64(np.array(v, dtype=float, order="C"), np.array(inv[m.faces], dtype=np.uint64, order="C")))
    mesh(s)
    return s


def box(lo, hi):
    return mf.Manifold.cube(np.asarray(hi) - lo).translate(lo)


def cyl(r, lo, hi):
    return mf.Manifold.cylinder(hi - lo, r, r, 64).translate([0, 0, lo])


def cx(r, lo, hi):
    return cyl(r, lo, hi).rotate([0, 90, 0])


def ball(r):
    return mf.Manifold.sphere(r, 64)


def keyed(r, lo, hi, clearance=0):
    return cyl(r + clearance, lo, hi) ^ box(
        [-r - 0.5 - clearance, -r - 0.5 - clearance, lo - 0.1], [r * 0.72 + clearance, r + 0.5 + clearance, hi + 0.1]
    )


def union(items):
    return mf.Manifold.batch_boolean(list(items), mf.OpType.Add)


def overlap(a, b):
    aa, bb = np.array(a.bounding_box()).reshape(2, 3), np.array(b.bounding_box()).reshape(2, 3)
    if np.any(aa[1] <= bb[0]) or np.any(bb[1] <= aa[0]):
        return 0.0
    q = a ^ b
    if q.status() != mf.Error.NoError:
        raise ValueError("intersection failed")
    return max(0.0, q.volume())
