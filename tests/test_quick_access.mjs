import test from 'node:test';
import assert from 'node:assert/strict';
import { recentResults, primaryArtifact, orderedArtifacts, browserEntry, resultDate, selectionCount } from '../studio/web/quick-access.js';

test('attach button counts only existing selections in the active editing or print mode', () => {
  const state = { workbench: { objects: [{ id: 'a' }, { id: 'b' }], selection: ['a', 'a', 'gone'] }, parts: [{ name: 'part' }], selection: { parts: ['part'] } };
  assert.equal(selectionCount('edit', state), 1);
  assert.equal(selectionCount('motion', state), 1);
  assert.equal(selectionCount('print', state), 1);
  assert.equal(selectionCount('tasks', state), 0);
  assert.equal(selectionCount('observe', state), 0);
  assert.equal(selectionCount('edit', null), 0);
  state.workbench.selection = [];
  assert.equal(selectionCount('edit', state), 0);
});

test('recent results omit failed, running and observation jobs and keep newest first', () => {
  const task = (id, extra = {}) => ({ id, status: 'completed', created: 1790568000, artifacts: [{ name: 'scene.glb' }], ...extra });
  const source = [task('old'), task('failed', { status: 'failed' }), task('new', { created: 1790568100 }), task('empty', { artifacts: [] }), task('observation', { category: 'observation' }), task('review', { template: 'a8-review' }), task('running', { status: 'running' })];
  assert.deepEqual(recentResults(source).map(t => t.id), ['new', 'old']);
  assert.equal(source[0].id, 'old', 'sorting does not mutate the task list');
  assert.deepEqual(recentResults(), []);
});

test('delivery HTML wins over nested inspection meshes, assembled scene wins over both', () => {
  const artifacts = [{ name: 'open-shell/scene.glb' }, { name: 'models/02-exploded.glb' }, { name: 'index.html' }];
  assert.equal(primaryArtifact(artifacts).name, 'index.html');
  artifacts.push({ name: 'scene.glb' });
  assert.equal(primaryArtifact(artifacts).name, 'scene.glb');
  assert.equal(primaryArtifact([{ name: 'report.json' }]).name, 'report.json');
  assert.equal(primaryArtifact([]), undefined);
});

test('browser entry preserves exact task identity and validates workspace mode', () => {
  assert.deepEqual(browserEntry('?workspace=test&mode=tasks&task=abc123'), { mode: 'tasks', taskId: 'abc123' });
  assert.deepEqual(browserEntry('?mode=print'), { mode: 'print', taskId: null });
  assert.deepEqual(browserEntry('?mode=invalid'), { mode: 'edit', taskId: null });
  assert.deepEqual(browserEntry(), { mode: 'edit', taskId: null });
});

test('task timestamps are Unix seconds, not milliseconds', () => {
  assert.equal(resultDate(1790568000).getUTCFullYear(), 2026);
  assert.equal(resultDate('2026-09-28T03:00:00Z').toISOString(), '2026-09-28T03:00:00.000Z');
  assert.equal(resultDate('bad'), null);
  assert.equal(resultDate(undefined), null);
});

test('output files put the assembled model and package before audit internals', () => {
  const artifacts = ['audit/report.json', 'back_shell.stl', 'scene.glb', 'kit.zip'].map(name => ({ name }));
  assert.deepEqual(orderedArtifacts(artifacts).map(a => a.name), ['scene.glb', 'kit.zip', 'back_shell.stl', 'audit/report.json']);
  assert.equal(artifacts[0].name, 'audit/report.json');
});

test('model browser hides probes/reports and ranks by completion instead of submission', () => {
  const task = (id, created, finished, name) => ({ id, created, finished, status: 'completed', artifacts: [{ name }] });
  const tasks = [task('lateFinish', 1, 9, 'scene.glb'), task('earlyFinish', 4, 5, 'model.glb'), task('probe', 10, 11, 'probe.json'), task('report', 11, 12, 'index.html')];
  assert.deepEqual(recentResults(tasks).map(t => t.id), ['lateFinish', 'earlyFinish']);
});
