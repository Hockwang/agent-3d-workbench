import test from 'node:test';
import assert from 'node:assert/strict';
import { modelArtifacts, modelLabel } from '../studio/web/model-browser.js';

test('all model artifacts remain selectable, including nested models and inspection variants', () => {
  const artifacts = ['one.glb', 'two.GLB', 'inspection/open.glb', 'report.json'].map(name => ({ name }));
  assert.deepEqual(modelArtifacts({ artifacts }).map(a => a.name), ['one.glb', 'two.GLB', 'inspection/open.glb']);
  assert.deepEqual(modelArtifacts({ artifacts, result: { primary: 'inspection/open.glb' } }).map(a => a.name), ['one.glb', 'two.GLB', 'inspection/open.glb']);
  assert.deepEqual(modelArtifacts({ artifacts: [{ name: 'models/a.glb' }] }).map(a => a.name), ['models/a.glb']);
  assert.deepEqual(modelArtifacts({ artifacts: [{ name: 'index.html' }, { name: 'models/a.glb' }, { name: 'models/b.glb' }] }).map(a => a.name), ['models/a.glb', 'models/b.glb']);
});

test('display names use exact saved names and readable filenames without changing the download name', () => {
  const artifact = { name: 'models/robot-walk.glb' };
  assert.equal(modelLabel(artifact, '小机器人'), '小机器人');
  assert.equal(modelLabel(artifact), 'robot walk');
  assert.equal(artifact.name, 'models/robot-walk.glb');
});
