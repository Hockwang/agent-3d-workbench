import os

import numpy as np
import trimesh

from studio.shell.server import StudioBackend


def test_reloading_same_part_paths_updates_centers_after_scaling(tmp_path):
    backend = StudioBackend(tmp_path / 'job', 'test')
    path = tmp_path / 'part.stl'
    mesh = trimesh.creation.box([20, 20, 20])
    mesh.apply_translation([100, 0, 0])
    mesh.export(path)
    parts = [{'name': 'part', 'stl_path': str(path)}]
    np.testing.assert_allclose(backend._source_centers(parts)['part'], [100, 0, 0])
    before = path.stat().st_mtime_ns
    mesh.apply_scale(0.5)
    mesh.export(path)
    os.utime(path, ns=(before + 1000000, before + 1000000))
    np.testing.assert_allclose(backend._source_centers(parts)['part'], [50, 0, 0])
