import test from 'node:test';
import assert from 'node:assert/strict';
import { ViewportFrame } from '../studio/web/viewport-frame.js';
import { Flow, derivePlanFeedback } from '../studio/web/flow.js';
import { recipeStepBaseTool } from '../studio/web/workspace.js';

// A recipe step's `tool` may carry a `#action`/`#template`/`#operation` suffix
// (recipes/README.md); every place that routes on it must compare the base tool
// name, not the whole string, or a suffixed step falls through to the wrong
// workspace (cut-to-fit's `studio_edit#plane_cut`, split-glue-kit's
// `studio_edit#split_components` / `studio_task#assembly-audit`, etc.).
test('recipeStepBaseTool strips the #action/#template/#operation suffix before routing', () => {
  assert.equal(recipeStepBaseTool({ tool: 'studio_edit#plane_cut' }), 'studio_edit');
  assert.equal(recipeStepBaseTool({ tool: 'studio_edit#split_components' }), 'studio_edit');
  assert.equal(recipeStepBaseTool({ tool: 'studio_task#assembly-audit' }), 'studio_task');
  assert.equal(recipeStepBaseTool({ tool: 'studio_task#image-to-3d' }), 'studio_task');
  assert.equal(recipeStepBaseTool({ tool: 'studio_edit' }), 'studio_edit');
  assert.equal(recipeStepBaseTool({ tool: 'studio_orient' }), 'studio_orient');
  assert.equal(recipeStepBaseTool(null), '');
  assert.equal(recipeStepBaseTool(undefined), '');
  assert.equal(recipeStepBaseTool({}), '');
});

test('full-canvas framing reserves expanded cards and releases that space on collapse', t => {
  let observer, cards = [], changed = 0;
  const rect = { left: 0, right: 1000, width: 1000, height: 600 };
  const stage = { querySelectorAll: () => cards };
  const element = { closest: () => stage, getBoundingClientRect: () => rect };
  const original = globalThis.ResizeObserver;
  globalThis.ResizeObserver = class { constructor(fn) { this.fn = fn; observer = this; } observe() {} disconnect() { this.disconnected = true; } };
  t.after(() => { globalThis.ResizeObserver = original; });
  const camera = { fov: 42, setViewOffset(...args) { this.offset = args; } };
  const frame = new ViewportFrame(element, camera, () => changed++);
  const clearDistance = frame.distance(100);
  cards = [{ getBoundingClientRect: () => ({ left: 500, right: 988, height: 400 }), classList: { contains: () => false } }];
  observer.fn();
  assert.ok(frame.distance(100) > clearDistance, 'fit must use the visible area, not hide the object behind settings');
  assert.equal(camera.offset[2], 250, 'projection moves the model into the clear half of the full canvas');
  assert.deepEqual(camera.offset.slice(0, 2), [1000, 600]);
  const count = changed; observer.fn(); assert.equal(changed, count, 'unchanged layout must not reset an orbit');
  cards = []; observer.fn();
  assert.equal(camera.offset[2], 0);
  assert.equal(frame.distance(100), clearDistance);
  rect.width = 0; rect.height = 0; observer.fn();
  assert.ok(Number.isFinite(frame.distance(100)), 'hidden workspaces must not yield an invalid camera distance');
  frame.dispose(); assert.equal(observer.disconnected, true);
});

test('v0.4 cards retain stale-step redo when the v0.5 accordion is absent', t => {
  const nodes = new Map();
  for (const id of ['ready-pill', 'btn-redo', 'stale-banner', 'stale-text']) {
    nodes.set(id, { addEventListener(type, fn) { this[type] = fn; } });
  }
  const original = globalThis.document;
  globalThis.document = { querySelectorAll: () => [], getElementById: id => nodes.get(id) || null };
  t.after(() => { globalThis.document = original; });
  let redone;
  const flow = new Flow({ onRedo: steps => { redone = steps; } });
  for (const method of ['_renderCtx', '_renderOrientParts', '_renderSelection', '_renderHistory']) flow[method] = () => {};
  flow.render({ stale: { arrange: {}, export: {}, check: {} }, steps: { inspect: true, orient: true } });
  assert.equal(nodes.get('stale-banner').hidden, false);
  nodes.get('btn-redo').click();
  assert.deepEqual(redone, ['arrange', 'export', 'check']);
  flow.render({ stale: {}, steps: {} });
  assert.equal(nodes.get('stale-banner').hidden, true);
});

test('review framing reserves playback and ignores full-width overlay panels', t => {
  const original = globalThis.ResizeObserver;
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  t.after(() => { globalThis.ResizeObserver = original; });
  const rect = { left: 0, right: 380, width: 380, height: 700 };
  const overlay = { getBoundingClientRect: () => ({ left: 12, right: 368, width: 356, height: 360 }), classList: { contains: () => false } };
  const stage = { querySelectorAll: () => [overlay] };
  const element = { closest: () => stage, getBoundingClientRect: () => rect };
  const camera = { fov: 42, setViewOffset(...args) { this.offset = args; } };
  const frame = new ViewportFrame(element, camera, null, { top: 80, bottom: 130 });
  assert.deepEqual(frame.insets, { left: 0, right: 0, top: 80, bottom: 130 });
  assert.equal(camera.offset[2], 0, 'mobile overlay must not push the model off-centre');
  assert.equal(camera.offset[3], 25);
  assert.ok(Number.isFinite(frame.distance(1)));
  frame.dispose();
});

const readyState = () => ({
  parts: [{ name: 'part', watertight: true }],
  steps: { inspect: true, orient: true, arrange: true, export: true, check: true },
  readiness: { items: ['model', 'orient', 'arrange', 'export', 'check', 'deliver'].map(key => ({ key, status: 'pass' })) },
});

test('plan guidance waits for state, then routes empty and partially completed jobs', () => {
  assert.equal(derivePlanFeedback(null).key, null);
  assert.equal(derivePlanFeedback({}).key, 'model');
  const state = { parts: [{ watertight: true }], steps: { inspect: true, orient: true, arrange: true } };
  const feedback = derivePlanFeedback(state);
  assert.equal(feedback.key, 'export');
  assert.equal(feedback.passed, 3);
  assert.equal(feedback.label, '下一步');
});

test('invalidated results override an old pass and do not count toward readiness', () => {
  const state = readyState(); state.stale = { export: {}, check: {} };
  const feedback = derivePlanFeedback(state);
  assert.equal(feedback.key, 'export');
  assert.equal(feedback.tone, 'stale');
  assert.equal(feedback.passed, 4);
  assert.deepEqual(feedback.items.filter(item => item.status === 'stale').map(item => item.src), ['export', 'check']);
});

test('warnings stay actionable and an active operation does not offer another next action', () => {
  const state = readyState(); state.readiness.items[0] = { key: 'model', status: 'warn', detail: '1 件不水密' };
  assert.equal(derivePlanFeedback(state).key, 'model');
  assert.equal(derivePlanFeedback(state).detail, '1 件不水密');
  state.busy = { op: 'arrange' };
  const feedback = derivePlanFeedback(state);
  assert.equal(feedback.key, null);
  assert.equal(feedback.tone, 'run');
  assert.equal(feedback.items.find(item => item.key === 'arrange').status, 'run');
});

test('finished flow still asks for checking the actual Bambu Studio project', () => {
  const feedback = derivePlanFeedback(readyState());
  assert.equal(feedback.key, null);
  assert.equal(feedback.passed, 6);
  assert.match(feedback.detail, /核对工程/);
});
