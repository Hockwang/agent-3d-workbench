"""Bounded cache for immutable, already validated A/B source STL geometry.

Only the parsed source meshes and their connected shells are cached. Final
Boolean results, exported STL round-trip verification, and report checks must
still run for every edit. ``load`` hashes both current STL byte streams on
every call and rejects stale source metadata before returning a cache hit.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from backend.engine import trimesh


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(source):
    if not isinstance(source, dict) or not isinstance(source.get("id"), str):
        raise ValueError("源模型缺少有效 ID")
    parts = source.get("parts")
    if not isinstance(parts, list) or len(parts) != 2:
        raise ValueError("缓存仅支持两个 A/B 源零件")
    paths = []
    hashes = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or not isinstance(part.get("stl"), str):
            raise ValueError("源零件缺少 STL 路径")
        path = Path(part["stl"])
        if not path.is_file():
            raise ValueError(f"分件 {'AB'[index]} 的源 STL 已丢失")
        current = _sha256(path)
        if current != part.get("sha256"):
            raise RuntimeError(f"分件 {'AB'[index]} 的源 STL 内容已改变，请重新载入")
        paths.append(str(path.resolve()))
        hashes.append(current)
    return (source["id"], tuple(paths), tuple(hashes))


def _copy_geometry(meshes, shells):
    # The copied vertex/face arrays protect the cached originals from a
    # caller's Boolean preparation or visualization transforms. Cached
    # derived arrays are shared only for read-only queries.
    return (
        [mesh.copy(include_cache=True, include_visual=False) for mesh in meshes],
        [[shell.copy(include_cache=True, include_visual=False) for shell in group] for group in shells],
    )


def _estimated_bytes(meshes, shells):
    base = sum(
        mesh.vertices.nbytes + mesh.faces.nbytes for mesh in list(meshes) + [part for group in shells for part in group]
    )
    # Trimesh also retains normals, adjacency, and spatial query arrays.
    return base * 4


class SourceGeometryCache:
    def __init__(self, *, max_bytes=160 * 1024 * 1024, max_faces=600_000):
        if max_bytes <= 0 or max_faces <= 0:
            raise ValueError("缓存预算必须为正")
        self.max_bytes = int(max_bytes)
        self.max_faces = int(max_faces)
        self._lock = threading.RLock()
        self._key = None
        self._value = None
        self._bytes = 0
        self.hits = 0
        self.misses = 0

    def clear(self):
        with self._lock:
            self._key = None
            self._value = None
            self._bytes = 0

    def stats(self):
        with self._lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "cached_bytes_estimate": self._bytes,
                "source_id": self._key[0] if self._key else None,
            }

    def load(self, source, builder):
        """Get detached meshes/shells, building once per frozen source pair.

        ``builder`` is the existing strict parser and shell splitter. It is
        called under the lock only on a miss. Any validation error propagates.
        """
        if not callable(builder):
            raise TypeError("builder must be callable")
        with self._lock:
            key = _fingerprint(source)
            if self._key == key and self._value is not None:
                self.hits += 1
                return _copy_geometry(*self._value)
            # Keep only one active source. A source switch or changed byte
            # stream drops the old immutable geometry before another build.
            self._key = None
            self._value = None
            self._bytes = 0
            self.misses += 1
            meshes, shells = builder()
            if (
                len(meshes) != 2
                or len(shells) != 2
                or any(not group for group in shells)
                or any(not isinstance(mesh, trimesh.Trimesh) for mesh in meshes)
                or any(not isinstance(shell, trimesh.Trimesh) for group in shells for shell in group)
            ):
                raise ValueError("源模型解析器未返回有效的 A/B 网格与壳体")
            if _fingerprint(source) != key:
                raise RuntimeError("源 STL 在解析期间发生变化，请重试")
            faces = sum(len(mesh.faces) for mesh in meshes) + sum(
                len(shell.faces) for group in shells for shell in group
            )
            bytes_estimate = _estimated_bytes(meshes, shells)
            if faces <= self.max_faces and bytes_estimate <= self.max_bytes:
                self._value = _copy_geometry(meshes, shells)
                self._key = key
                self._bytes = bytes_estimate
                return _copy_geometry(*self._value)
            return meshes, shells


CURRENT_SOURCE = SourceGeometryCache()
