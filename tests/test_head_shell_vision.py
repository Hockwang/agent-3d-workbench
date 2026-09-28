import numpy as np
import pytest

from studio.core.head_shell_vision import eye_screen, smile_vents
from studio.core.kernels.mechanical_geometry import box, mesh, overlap


def test_eye_grid_has_real_through_holes_thin_skin_and_connected_rim():
    source = box([-20, -25, 25], [20, -19, 75])
    screen, opening, frame, body_opening, r = eye_screen(source, source, [], {})
    m = mesh(screen)
    assert m.is_volume and len(m.split(only_watertight=False, repair=False)) == 1
    assert r["hole_count"] > 100 and 0.3 < r["projected_open_fraction"] < 0.6
    # A hole at (1.5,49.5), a grid bar at (0,49.5), and the solid rim.
    origins = np.array([[1.5, -30, 49.5], [0, -30, 49.5], [-19, -30, 49.5]])
    assert m.ray.intersects_any(origins, np.tile([0, 1, 0], (3, 1))).tolist() == [False, True, True]
    assert overlap(screen, box([-0.1, -23, 49.3], [0.1, -19.1, 49.7])) < 1e-6
    assert overlap(frame, opening) < 1e-6
    # GLB float32 quantization is explicit; test a bounded relative loss,
    # while the solid-rim ray above tests the physical feature itself.
    assert (frame - screen).volume() < frame.volume() * 1e-6


def test_protected_highlight_remains_solid_and_invalid_grid_rejected():
    source = box([-20, -25, 25], [20, -19, 75])
    highlight = box([-3, -26, 55], [3, -18, 63])
    screen, opening, frame, body_opening, r = eye_screen(source, source, [highlight], {})
    assert overlap(opening, highlight) < 1e-6
    assert overlap(screen, highlight) > 0
    # Host opening is continuous behind the highlight; only the insert owns
    # the support collar, so no disconnected host islands can be left there.
    assert overlap(body_opening, highlight) > 0
    for config in [{"bar_mm": 3}, {"pitch_mm": float("nan")}, {"thickness_mm": 0.1}]:
        with pytest.raises(ValueError):
            eye_screen(source, source, [], config)


def test_smile_follows_declared_curve_without_extra_lower_mouth():
    vent, r = smile_vents([{"points_xz_mm": [[-20, 120], [0, 125], [20, 120]], "width_mm": 1.4}])
    assert mesh(vent).is_volume and r["projected_area_mm2"] > 50
    assert overlap(vent, box([-0.2, -150, 124.8], [0.2, -140, 125.2])) > 0
    assert overlap(vent, box([-25, -150, 108], [25, -140, 112])) == 0
    with pytest.raises(ValueError):
        smile_vents([{"points_xz_mm": [[0, 0], [1, 1]], "width_mm": -1}])


def test_sight_reports_nearest_forward_blocker_and_clear_side_ray():
    from studio.core.head_shell_sight import rays_at, angular_directions

    m = mesh(box([-2, -12, -2], [2, -10, 2]))
    pairs, ds = angular_directions([0, 60], [0])
    assert np.allclose(ds[0], [0, -1, 0])
    distances = rays_at(m, np.array([0, 0, 0]), ds)
    assert distances[0] == pytest.approx(10)
    assert np.isinf(distances[1])


def test_curved_grid_survives_stl_float32_roundtrip():
    import io
    import manifold3d as mf
    import trimesh

    source = mf.Manifold.sphere(30, 64).scale([1, 0.65, 1]).translate([0, -60, 70])
    part = source - source.translate([0, 5, 0])
    screen, opening, frame, *_ = eye_screen(part, source, [], {})
    # Shared lazy CSG branches must not erase the structural inspection rim.
    assert mesh(frame).is_volume and frame.volume() > 0
    assert overlap(frame, opening) < 1e-6
    read = trimesh.load_mesh(io.BytesIO(mesh(screen).export(file_type="stl")), file_type="stl", process=True)
    assert read.is_volume
    assert len(read.split(only_watertight=False, repair=False)) == 1
    preview = mesh(screen)
    preview.apply_scale(0.001)
    glb = trimesh.load(io.BytesIO(preview.export(file_type="glb")), file_type="glb", force="mesh", process=True)
    vertices, inverse = np.unique(glb.vertices, axis=0, return_inverse=True)
    welded = trimesh.Trimesh(vertices, inverse[glb.faces], process=False)
    assert welded.is_volume and np.all(np.bincount(welded.edges_unique_inverse) == 2)


def test_projection_retains_concave_corner_instead_of_cutting_across_it():
    from shapely.geometry import Point
    from studio.core.head_shell_vision import projection

    part = box([0, -10, 0], [20, -5, 5]) + box([0, -10, 0], [5, -5, 20])
    outline = projection(part)
    assert outline.area == pytest.approx(175)
    assert not outline.contains(Point(10, 10))


def test_sight_gate_uses_actual_lattice_not_only_aperture(tmp_path):
    from studio.core.head_shell_sight import audit
    from studio.core.task_operations import deliver
    import trimesh

    actual = trimesh.creation.box([20, 2, 20])
    actual.apply_translation([0, -10, 10])
    frame = trimesh.creation.box([2, 2, 20])
    frame.apply_translation([8, -10, 10])
    source = tmp_path / "source"
    source.mkdir()
    aperture = source / "inspection/without-eye-lattice"
    aperture.mkdir(parents=True)
    deliver({"eye": actual}, source, {}, stl=False)
    deliver({"eye": frame}, aperture, {}, stl=False)
    report = audit(source, tmp_path / "result", [[-1, 0, 10], [1, 0, 10]])
    assert all(e["forward_clear"] for e in report["results"]["aperture_envelope"]["eyes"])
    assert not any(e["forward_clear"] for e in report["results"]["actual_grid"]["eyes"])
    assert report["status"] == "forward_blocked"
