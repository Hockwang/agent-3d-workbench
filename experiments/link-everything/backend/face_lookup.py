"""Exact face-point lookup with a conservative AABB fast path.

The original all-face test is retained as fallback. It runs whenever the
spatial shortlist does not find a match, so invalid placements and tolerance
edge cases keep precisely the same acceptance semantics.
"""

from __future__ import annotations

from backend.engine import np


def full_scan(mesh, point, normal, opposite, point_in_triangle):
    wanted = -normal if opposite else normal
    centers = mesh.triangles_center
    norms = mesh.face_normals
    candidates = np.where((norms @ wanted > 0.985) & (np.abs((centers - point) @ normal) < 0.16))[0]
    return any(point_in_triangle(point, mesh.triangles[i], wanted) for i in candidates)


def face_at(mesh, point, normal, opposite, point_in_triangle, *, fallback=True):
    point = np.asarray(point, dtype=float)
    normal = np.asarray(normal, dtype=float)
    if point.shape != (3,) or normal.shape != (3,):
        return full_scan(mesh, point, normal, opposite, point_in_triangle) if fallback else False
    bounds = getattr(mesh, "_connection_face_bounds", None)
    if bounds is None:
        triangles = mesh.triangles
        bounds = (np.min(triangles, axis=1) - 0.2, np.max(triangles, axis=1) + 0.2)
        mesh._connection_face_bounds = bounds
    low, high = bounds
    nearby = np.flatnonzero(np.all((low <= point) & (point <= high), axis=1))
    if len(nearby):
        wanted = -normal if opposite else normal
        centers = mesh.triangles_center
        norms = mesh.face_normals
        triangles = mesh.triangles
        for index in nearby:
            if (
                float(norms[index] @ wanted) > 0.985
                and abs(float((centers[index] - point) @ normal)) < 0.16
                and point_in_triangle(point, triangles[index], wanted)
            ):
                return True
    # Suggestions may sample dozens of nearby points. A missed AABB shortlist
    # only makes a proposed size smaller; strict placement validation below
    # still retains the original full scan and acceptance semantics.
    return full_scan(mesh, point, normal, opposite, point_in_triangle) if fallback else False
