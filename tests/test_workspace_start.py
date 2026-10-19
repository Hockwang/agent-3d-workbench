"""Opening a new model must not merge it into the previous saved scene."""
import copy
import json
import zipfile

import pytest
import trimesh

from studio.core.editor import EditorError, Workspace
from tests.helpers import act


def test_new_model_archives_previous_scene_and_can_undo(tmp_path):
    ws = Workspace(tmp_path / 'workbench')
    act(ws, 'primitive', kind='box')
    previous = copy.deepcopy(ws.doc['objects'])
    source = tmp_path / 'chosen.stl'
    trimesh.creation.icosphere(subdivisions=1).export(source)
    result = act(ws, 'import', files=[str(source)], new_scene=True)
    assert len(ws.doc['objects']) == 1
    assert ws.doc['objects'][0]['id'] != previous[0]['id']
    with zipfile.ZipFile(result['previous_project']) as archive:
        saved = json.loads(archive.read('manifest.json'))
        assert saved['objects'] == previous
        assert archive.testzip() is None
    act(ws, 'undo')
    assert ws.doc['objects'] == previous
    act(ws, 'redo')
    assert len(ws.doc['objects']) == 1
    restored = Workspace(tmp_path / 'restored')
    act(restored, 'open', path=result['previous_project'])
    assert restored.doc['objects'] == previous


def test_bad_new_model_preserves_previous_project_and_no_archive(tmp_path):
    ws = Workspace(tmp_path / 'workbench')
    act(ws, 'primitive', kind='box')
    previous = ws.path.read_bytes()
    with pytest.raises(EditorError):
        act(ws, 'import', files=[str(tmp_path / 'missing.stl')], new_scene=True)
    assert ws.path.read_bytes() == previous
    assert not list((ws.root / 'exports').glob('*.3dworkbench'))


def test_ordinary_import_still_appends(tmp_path):
    ws = Workspace(tmp_path / 'workbench')
    act(ws, 'primitive', kind='box')
    source = tmp_path / 'chosen.stl'
    trimesh.creation.box().export(source)
    act(ws, 'import', files=[str(source)])
    assert len(ws.doc['objects']) == 2


def test_failed_archive_never_replaces_scene(tmp_path, monkeypatch):
    from studio.core import editor_actions
    ws = Workspace(tmp_path / 'workbench')
    act(ws, 'primitive', kind='box')
    previous = ws.path.read_bytes()
    source = tmp_path / 'chosen.stl'
    trimesh.creation.box().export(source)
    def unavailable(*args):
        raise OSError('Cannot save previous scene')
    monkeypatch.setattr(editor_actions, 'save', unavailable)
    with pytest.raises(OSError):
        act(ws, 'import', files=[str(source)], new_scene=True)
    assert ws.path.read_bytes() == previous


def test_new_scene_does_not_clear_shared_objects(tmp_path):
    ws = Workspace(tmp_path / 'workbench')
    act(ws, 'primitive', kind='box')
    ws.doc['collaboration'] = {}
    previous = copy.deepcopy(ws.doc)
    with pytest.raises(EditorError, match='共享|shared'):
        ws.execute({'action': 'import', 'expected_revision': 1, 'params': {'files': [], 'new_scene': True}})
    assert ws.doc == previous


def test_task_import_supports_new_scene_without_changing_task_or_print_job(studio_env, tmp_path, monkeypatch):
    client, backend = studio_env['client'], studio_env['backend']
    act(backend.editor, 'primitive', kind='box')
    source = tmp_path / 'task-model.glb'
    trimesh.Scene(trimesh.creation.box()).export(source)
    original = source.read_bytes()
    monkeypatch.setattr(backend.tasks, 'artifact', lambda *args: (source, {}))
    job_path = studio_env['job_dir'] / 'job.json'
    before_job = job_path.read_bytes() if job_path.exists() else None
    body = {'action': 'import', 'id': 'example', 'artifact_id': 'model', 'new_scene': True, 'expected_revision': 1}
    code, result = client.post('/api/task', body)
    assert code == 200, result
    assert len(backend.editor.doc['objects']) == 1
    assert result['previous_project']
    assert source.read_bytes() == original
    assert (job_path.read_bytes() if job_path.exists() else None) == before_job
    assert client.post('/api/task', body)[0] == 409
    assert client.post('/api/task', {**body, 'replace_ids': ['old']})[0] == 400
