"""Approximate watertight proxy for visual-only GLB imports.

This is an explicit fallback for interactive *experimentation*. Voxel remeshing
changes the shape and can fill intentional openings, so the returned solid is
never a manufacturing or fit-verified replacement for the original GLB.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from backend.engine import mesh_solid, np, trimesh

MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_SOURCE_FACES = 1_500_000
MAX_MESHES = 128
MAX_PROXY_FACES = 250_000
TARGET_PROXY_FACES = 220_000
MAX_TOTAL_SECONDS = 180
ATTEMPT_PLAN = (("voxel", 1.0), ("voxel", 1.5), ("solidify", 1.0), ("voxel", 2.25), ("solidify", 1.5), ("voxel", 3.375))
BLENDER_SCRIPT = Path(__file__).with_name("voxel_proxy_blender.py")


def _blender_executable() -> Path:
    configured = os.environ.get("CONNECTION_DEMO_BLENDER")
    path = Path(configured) if configured else Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
    if path.is_file():
        return path
    found = shutil.which("blender")
    if found:
        return Path(found)
    raise RuntimeError("未找到 Blender；无法生成体素切割代理")


def _basis(input_units: str, input_up_axis: str):
    if input_units not in ("m", "mm"):
        raise ValueError("GLB 输入单位只能是 m 或 mm")
    if input_up_axis not in ("Y", "Z"):
        raise ValueError("GLB 上方向只能是 Y 或 Z")
    scale = 1000.0 if input_units == "m" else 1.0
    basis = np.eye(4)
    basis[:3, :3] = (
        [[scale, 0, 0], [0, 0, -scale], [0, scale, 0]]
        if input_up_axis == "Y"
        else [[scale, 0, 0], [0, scale, 0], [0, 0, scale]]
    )
    return basis, scale


def _scene_stats(path: Path, basis):
    try:
        scene = trimesh.load(path, file_type="glb", force="scene", process=False)
    except Exception as exc:
        raise ValueError("原始 GLB 无法读取") from exc
    if not isinstance(scene, trimesh.Scene) or not scene.graph.nodes_geometry:
        raise ValueError("原始 GLB 没有三角网格")
    if len(scene.graph.nodes_geometry) > MAX_MESHES:
        raise ValueError("GLB 网格实例超过安全上限")
    lower, upper = np.full(3, np.inf), np.full(3, -np.inf)
    face_count, mesh_count = 0, 0
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph.get(node)
        geometry = scene.geometry[name]
        if not isinstance(geometry, trimesh.Trimesh) or not len(geometry.faces):
            continue
        face_count += len(geometry.faces)
        mesh_count += 1
        if face_count > MAX_SOURCE_FACES:
            raise ValueError("原始 GLB 三角面数超过展示安全上限")
        transform = np.asarray(transform, dtype=float)
        if (
            transform.shape != (4, 4)
            or not np.isfinite(transform).all()
            or abs(np.linalg.det(transform[:3, :3])) < 1e-12
        ):
            raise ValueError("原始 GLB 存在无效节点变换")
        vertices = np.asarray(geometry.vertices, dtype=float)
        if not len(vertices) or not np.isfinite(vertices).all():
            raise ValueError("原始 GLB 存在无效顶点")
        world = basis @ transform
        points = vertices @ world[:3, :3].T + world[:3, 3]
        if not np.isfinite(points).all():
            raise ValueError("原始 GLB 变换后的坐标无效")
        lower = np.minimum(lower, points.min(axis=0))
        upper = np.maximum(upper, points.max(axis=0))
    if not mesh_count:
        raise ValueError("原始 GLB 没有三角网格")
    extent = upper - lower
    if max(extent) > 10000 or max(extent) < 0.01:
        raise ValueError("模型尺寸异常；请核对 GLB 单位")
    return dict(
        bounds_mm=[lower.tolist(), upper.tolist()],
        face_count=face_count,
        mesh_count=mesh_count,
        max_extent_mm=float(max(extent)),
    )


def _validated_proxy(path: Path, basis):
    try:
        scene = trimesh.load(path, file_type="glb", force="scene", process=False)
    except Exception as exc:
        raise ValueError("Blender 代理 GLB 无法读取") from exc
    meshes = []
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph.get(node)
        geometry = scene.geometry[name]
        if not isinstance(geometry, trimesh.Trimesh) or not len(geometry.faces):
            continue
        mesh = geometry.copy()
        mesh.apply_transform(basis @ np.asarray(transform, dtype=float))
        meshes.append(mesh)
    if not meshes:
        raise ValueError("Blender 代理没有三角面")
    proxy = trimesh.util.concatenate(meshes)
    # GLB duplicates vertices at normal seams. Weld matching coordinates
    # conservatively: a 1 µm rounded weld can incorrectly join distinct
    # voxel edges (observed on the turbo badcase).
    proxy.merge_vertices(merge_tex=True, merge_norm=True, digits_vertex=8)
    proxy.remove_unreferenced_vertices()
    if len(proxy.faces) > MAX_PROXY_FACES:
        raise ValueError("代理超过 25 万三角面切割预算")
    if not np.isfinite(proxy.vertices).all() or not proxy.is_watertight:
        raise ValueError("代理仍有开放或非流形边")
    if not proxy.is_winding_consistent or proxy.volume < 0:
        trimesh.repair.fix_normals(proxy, multibody=True)
    if not proxy.is_winding_consistent or proxy.volume <= 1:
        raise ValueError("代理不是正体积的闭合实体")
    try:
        solid = mesh_solid(proxy)
        if solid.is_empty() or solid.volume() <= 1:
            raise ValueError("代理无法转为可切割实体")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("代理无法转为可切割实体") from exc
    return proxy


def make_proxy(
    original_glb_path: str | Path,
    input_units: str,
    input_up_axis: str,
    *,
    blender_path: str | Path | None = None,
    max_total_seconds: int = MAX_TOTAL_SECONDS,
):
    """Return `(mesh, provenance)` with mesh in mm/Z-up coordinates.

    The original GLB remains untouched. Failed remeshes are retried at a
    coarser pitch. For open sheets and large holes, a separate shallow-shell
    attempt is allowed and recorded explicitly as a more approximate result.
    All Blender processes share one bounded wall-time cap.
    """
    if not 5 <= max_total_seconds <= MAX_TOTAL_SECONDS:
        raise ValueError("代理生成时间上限必须在 5 到 180 秒之间")
    source = Path(original_glb_path).resolve()
    if not source.is_file() or not 80 <= source.stat().st_size <= MAX_SOURCE_BYTES:
        raise ValueError("原始 GLB 不存在或超过 50 MB")
    with source.open("rb") as stream:
        header = stream.read(12)
    if (
        header[:4] != b"glTF"
        or len(header) < 12
        or int.from_bytes(header[4:8], "little") != 2
        or int.from_bytes(header[8:12], "little") != source.stat().st_size
    ):
        raise ValueError("原始文件不是有效的 glTF 2.0 GLB")
    basis, scale = _basis(input_units, input_up_axis)
    source_stats = _scene_stats(source, basis)
    with source.open("rb") as stream:
        source_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    executable = Path(blender_path) if blender_path is not None else _blender_executable()
    if not executable.is_file():
        raise RuntimeError("Blender 可执行文件不存在")
    started = time.perf_counter()
    pitch_mm = max(0.5, source_stats["max_extent_mm"] / 150.0)
    attempts = []
    with tempfile.TemporaryDirectory(prefix="connection-voxel-proxy-") as temporary:
        for index, (mode, pitch_factor) in enumerate(ATTEMPT_PLAN):
            remaining = max_total_seconds - (time.perf_counter() - started)
            if remaining < 5:
                break
            current_pitch_mm = pitch_mm * pitch_factor
            output = Path(temporary) / f"proxy-{index}.glb"
            command = [
                str(executable),
                "--background",
                "--factory-startup",
                "--python",
                str(BLENDER_SCRIPT),
                "--",
                str(source),
                str(output),
                str(current_pitch_mm / scale),
                str(TARGET_PROXY_FACES),
                mode,
            ]
            attempt = dict(mode=mode, pitch_mm=round(current_pitch_mm, 4))
            attempt_started = time.perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=min(75.0, remaining),
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                attempt["duration_s"] = round(time.perf_counter() - attempt_started, 3)
                for line in completed.stdout.splitlines():
                    if line.startswith("PROXY_METRICS "):
                        try:
                            attempt["blender_metrics"] = json.loads(line[len("PROXY_METRICS ") :])
                        except ValueError:
                            pass
                if completed.returncode != 0 or not output.is_file():
                    attempt["error"] = "Blender 体素化失败或生成了非流形代理"
                    attempts.append(attempt)
                    continue
                proxy = _validated_proxy(output, basis)
            except subprocess.TimeoutExpired:
                attempt["duration_s"] = round(time.perf_counter() - attempt_started, 3)
                attempt["error"] = "Blender 处理超时"
                attempts.append(attempt)
                continue
            except (ValueError, OSError) as exc:
                attempt["duration_s"] = round(time.perf_counter() - attempt_started, 3)
                attempt["error"] = str(exc)
                attempts.append(attempt)
                continue
            attempt.update(faces=len(proxy.faces), watertight=True)
            attempts.append(attempt)
            bounds = proxy.bounds.tolist()
            source_bounds = np.asarray(source_stats["bounds_mm"])
            warning = (
                f"开放表面已加厚约 {2.5 * current_pitch_mm:.2f} mm 再体素化；"
                if mode == "solidify"
                else "模型已体素化；"
            )
            warning += "代理可能改变外形、开口、薄壁及体积，仅供分件交互试验，不能作为制造或配合公差依据。"
            metrics = dict(
                method="blender-voxel-remesh",
                approximate=True,
                warning=warning,
                fidelity_note="包围盒差值只衡量外边界，不能证明内部形状、开口或体积与原件一致。",
                proxy_mode=mode,
                solidify_thickness_mm=(round(2.5 * current_pitch_mm, 4) if mode == "solidify" else 0),
                source_sha256=source_sha256,
                source_faces=source_stats["face_count"],
                source_meshes=source_stats["mesh_count"],
                source_bounds_mm=source_stats["bounds_mm"],
                pitch_mm=round(current_pitch_mm, 4),
                proxy_faces=len(proxy.faces),
                proxy_volume_mm3=float(proxy.volume),
                proxy_bounds_mm=bounds,
                max_bound_shift_mm=float(np.max(np.abs(np.asarray(bounds) - source_bounds))),
                elapsed_s=round(time.perf_counter() - started, 3),
                attempts=attempts,
            )
            return proxy, metrics
    raise ValueError(
        "无法在时间和面数限制内生成闭合切割代理；尝试记录："
        + "; ".join(f"{item['pitch_mm']} mm: {item.get('error', 'unknown')}" for item in attempts)
    )
