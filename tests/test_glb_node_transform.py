"""SPEC.md §5 第 5 条：带节点平移的 GLB 场景载入后包围盒位置正确（验证没有丢变换）。

trimesh 4.12.2 的已知行为：`Scene.geometry.values()` 只给几何在自己局部系里的
样子，不带节点变换；必须按 `scene.graph` 逐节点取世界变换再应用。
"""

from __future__ import annotations

import numpy as np
import trimesh

from print_prep import mesh_io


def test_translated_node_keeps_world_position(tmp_path):
    scene = trimesh.Scene()
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    translation = np.array([100.0, 50.0, 25.0])
    transform = trimesh.transformations.translation_matrix(translation)
    scene.add_geometry(box, node_name="part_a", geom_name="box_geom", transform=transform)

    glb_path = tmp_path / "translated.glb"
    scene.export(glb_path, file_type="glb")

    parts = mesh_io.load_raw_parts(glb_path)
    assert len(parts) == 1
    name, mesh = parts[0]
    assert name == "part_a"

    expected_min = translation - 5.0
    expected_max = translation + 5.0
    assert np.allclose(mesh.bounds[0], expected_min, atol=1e-6)
    assert np.allclose(mesh.bounds[1], expected_max, atol=1e-6)
    assert np.allclose(mesh.centroid, translation, atol=1e-6)


def test_naive_scene_geometry_values_would_lose_the_transform(tmp_path):
    """反证：如果直接用 `scene.geometry.values()`（不按 graph 取变换），
    包围盒会错误地停在原点附近——证明我们绕开这个坑是必要的，不是多此一举。"""
    scene = trimesh.Scene()
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    transform = trimesh.transformations.translation_matrix([100.0, 50.0, 25.0])
    scene.add_geometry(box, node_name="part_a", geom_name="box_geom", transform=transform)

    glb_path = tmp_path / "translated2.glb"
    scene.export(glb_path, file_type="glb")

    naive = trimesh.load(glb_path, process=False, force=None)
    naive_geom = next(iter(naive.geometry.values()))
    assert np.allclose(naive_geom.bounds[0], [-5.0, -5.0, -5.0], atol=1e-6), (
        "这条断言本身就是在记录 trimesh 的坑：如果哪天这个断言失败了，说明"
        "trimesh 自己修好了，我们的 workaround 可以简化"
    )


def test_translated_node_via_inspect_command(tmp_path, run):
    scene = trimesh.Scene()
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    transform = trimesh.transformations.translation_matrix([100.0, 50.0, 25.0])
    scene.add_geometry(box, node_name="part_a", geom_name="box_geom", transform=transform)
    glb_path = tmp_path / "translated3.glb"
    scene.export(glb_path, file_type="glb")

    job_dir = tmp_path / "job"
    exit_code, payload, _ = run(["inspect", "--job", str(job_dir), str(glb_path)])
    assert exit_code == 0
    part = payload["parts"][0]
    # extents 不受平移影响，但如果变换丢了，watertight/connectivity 也会体现出来；
    # 这里主要靠上面两条单元测试锁住机制，这里再确认整条 inspect 流程走得通。
    assert part["extents_mm"] == [10.0, 10.0, 10.0]
