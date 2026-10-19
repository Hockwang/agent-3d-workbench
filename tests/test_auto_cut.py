import json

import numpy as np
import pytest
import trimesh

from print_prep import arrange, job, orient
from studio.core import print_state
from studio.core.auto_cut import CutPlanner, prepare_copy


BED = dict(bed_mm=[256, 256, 250], bed_origin_mm=[0, 0],
           exclude_areas=[[0, 0, 18, 28]], margin_mm=5)


def test_rotation_before_cutting_and_no_scale():
    mesh = trimesh.creation.box([240, 50, 246])
    plan = CutPlanner(BED).plan(mesh, 'tall', preferred=[0, 0, 1])
    assert len(plan['pieces']) == 1
    assert plan['cuts'] == []
    assert np.allclose(plan['pieces'][0]['mesh'].bounds, mesh.bounds)
    arrange.arrange([dict(name='tall', **plan['pieces'][0])], **BED)


def test_recursive_cut_is_closed_preserves_volume_coordinates_and_all_parts():
    mesh = trimesh.creation.box([600, 300, 290])
    mesh.apply_translation([111, -23, 700])
    plan = CutPlanner(BED).plan(mesh, 'large')
    assert 1 < len(plan['pieces']) <= 32
    assert all(p['mesh'].is_volume for p in plan['pieces'])
    assert all(orient.base_contact_area(p['mesh'], p['print_up']) >= orient.STABLE_CONTACT_MM2 for p in plan['pieces'])
    assert sum(p['mesh'].volume for p in plan['pieces']) == pytest.approx(mesh.volume, rel=1e-5)
    bounds = np.array([p['mesh'].bounds for p in plan['pieces']])
    assert np.allclose([bounds[:, 0].min(0), bounds[:, 1].max(0)], mesh.bounds)
    parts = [dict(name=f'p{i}', **p) for i, p in enumerate(plan['pieces'])]
    plates = arrange.arrange(parts, **BED)
    assert sorted(n for plate in plates for n in plate['parts']) == sorted(p['name'] for p in parts)


def test_non_volume_and_budget_fail_closed():
    open_mesh = trimesh.creation.box([300, 300, 300])
    open_mesh.update_faces(np.arange(len(open_mesh.faces) - 1))
    with pytest.raises(Exception, match='水密|closed'):
        CutPlanner(BED).plan(open_mesh, 'open')
    with pytest.raises(Exception, match='上限|limit'):
        CutPlanner(BED, max_pieces=2).plan(trimesh.creation.box([700, 700, 700]), 'huge')


def test_transaction_preserves_original_on_export_failure(tmp_path, monkeypatch):
    source = tmp_path / 'source.stl'
    trimesh.creation.box([300, 150, 300]).export(source)
    root = tmp_path / 'job'
    print_state.api_load(root, {'files': [str(source)]})
    before = job.job_json_path(root).read_bytes()
    original_stl = source.read_bytes()
    def fail(*args, **kwargs):
        raise RuntimeError('export unavailable')
    monkeypatch.setattr(print_state, 'api_export', fail)
    with pytest.raises(RuntimeError, match='export unavailable'):
        prepare_copy(root, {})
    assert job.job_json_path(root).read_bytes() == before
    assert source.read_bytes() == original_stl
    assert not list((root / 'print-inputs').glob('auto-cut-*'))


def test_api_swaps_only_after_verified_arrangement_and_rejects_stale_source(studio_env, tmp_path, monkeypatch):
    client, backend = studio_env['client'], studio_env['backend']
    source = tmp_path / 'shell.stl'
    other = tmp_path / 'ear.stl'
    trimesh.creation.box([300, 150, 300]).export(source)
    trimesh.creation.box([20, 30, 40]).export(other)
    assert client.post('/api/load', {'files': [str(source), str(other)]})[0] == 200
    _, before = client.get('/api/state')
    editor_before = backend.editor.state()
    monkeypatch.setattr(print_state, 'api_export', lambda *a, **k: {'ok': True, 'print_submitted': False})
    code, response = client.post('/api/prepare', {'auto_cut': True, 'expected_inspect_rev': before['inspect_rev'] + 1})
    assert code == 400 and response['error']['code'] == 'print_source_changed'
    code, response = client.post('/api/prepare', {'auto_cut': True, 'expected_inspect_rev': before['inspect_rev']})
    assert code == 200, response
    _, after = client.get('/api/state')
    assert len(after['parts']) > 2 and after['plates']
    assert 'ear' in [p['name'] for p in after['parts']]
    assert backend.editor.state() == editor_before
    assert response['print_submitted'] is False
    assert after['auto_cut']['cut_count'] > 0
    assert after['auto_cut']['input_parts'] == 2
    assert json.loads(job.job_json_path(backend.job_dir).read_text())['inspect']['scale_applied'] == 1


def test_check_uses_profiles_bound_to_export_instead_of_old_job_settings(tmp_path, monkeypatch):
    from print_prep import bambu
    root = tmp_path / 'job'
    profiles = root / 'print-inputs' / 'copy' / 'profiles'
    profiles.mkdir(parents=True)
    for name in ('machine.json', 'process.json', 'filament-0.json'):
        (profiles / name).write_text('{}')
    job.save_job(root, {'export': {'profiles_dir': str(profiles), 'plates': [
        {'index': 1, 'geometry_3mf': str(root / 'copy.3mf')}]} })
    seen = []
    def slice_copy(geometry, output, machine, process, filaments, **kwargs):
        seen.extend([machine, process, *filaments])
        return dict(grams=1, seconds=5, warnings=[], returncode=0, wall_seconds=.1, error=None)
    monkeypatch.setattr(bambu, 'check_slice', slice_copy)
    assert print_state.api_check(root, {})['ok']
    assert all(p.parent == profiles for p in seen)


def test_excluded_bed_region_forces_a_cut_even_when_dimensions_fit():
    mesh = trimesh.creation.box([245, 245, 245])
    plan = CutPlanner(BED).plan(mesh, 'blocked')
    assert plan['cuts']
    arrange.arrange([dict(name=f'p{i}', **p) for i, p in enumerate(plan['pieces'])], **BED)
