import test from 'node:test';
import assert from 'node:assert/strict';
import { Panel } from '../studio/web/panel.js';

function fixture(t) {
  const original = globalThis.document;
  const nodes = Object.fromEntries([
    'model-paths', 'model-scale', 'model-target-max', 'model-merge', 'printer-select',
    'shape-select', 'strategy-select', 'mode-select', 'gap-input', 'no-project-check',
    'process-input', 'filament-input',
  ].map(id => [id, { value: '', checked: false }]));
  globalThis.document = { getElementById: id => nodes[id] };
  t.after(() => { globalThis.document = original; });
  const panel = Object.create(Panel.prototype);
  // Exercise the real state-render and submit paths without the unrelated cards.
  for (const name of Object.getOwnPropertyNames(Panel.prototype)) {
    if (name.startsWith('_render')) panel[name] = () => {};
  }
  panel._syncControl = panel._setButtonsDisabled = panel._applyCardDefaults = () => {};
  panel._collectOverrides = () => ({});
  const submissions = [], errors = [];
  panel.opts = { onPrepare: body => submissions.push(body), onLocalError: message => errors.push(message) };
  return { panel, nodes, submissions, errors };
}

const sources = Array.from({ length: 13 }, (_, i) => `/job/parts/part${i}.stl`);
const state = (extra = {}) => ({ job: '/job', inspect_rev: 4, rev: 8,
  print_sources: sources, parts: sources.map((_, i) => ({ name: `part${i}` })), ...extra });

test('reopening an existing print job restores all model paths before one-click prepare', t => {
  const { panel, nodes, submissions, errors } = fixture(t);
  panel.render(null);
  panel.render(state());
  assert.equal(nodes['model-paths'].value, sources.join('\n'));
  panel._handlePrepare();
  assert.deepEqual(errors, []);
  assert.deepEqual(submissions[0].files, sources);
  assert.equal(submissions[0].scale, undefined, 'restored STL copies already have their current scale');
});

test('ordinary refresh preserves unsubmitted paths and dimensions, including a deliberate empty input', t => {
  const { panel, nodes } = fixture(t);
  panel.render(state());
  nodes['model-paths'].value = '/new/model.stl';
  nodes['model-scale'].value = '0.5';
  nodes['model-merge'].checked = true;
  panel.render(state({ rev: 9, busy: { op: 'orient' } }));
  assert.equal(nodes['model-paths'].value, '/new/model.stl');
  assert.equal(nodes['model-scale'].value, '0.5');
  assert.equal(nodes['model-merge'].checked, true);
  nodes['model-paths'].value = '';
  panel.render(state({ rev: 10 }));
  assert.equal(nodes['model-paths'].value, '');
});

test('a reloaded model resets consumed scaling even when the STL paths are unchanged', t => {
  const { panel, nodes } = fixture(t);
  panel.render(state());
  nodes['model-scale'].value = '0.5';
  nodes['model-target-max'].value = '180';
  nodes['model-merge'].checked = true;
  panel.render(state({ inspect_rev: 11, rev: 12 }));
  assert.equal(nodes['model-scale'].value, '');
  assert.equal(nodes['model-target-max'].value, '');
  assert.equal(nodes['model-merge'].checked, false);
  assert.equal(nodes['model-paths'].value, sources.join('\n'));
});

test('first state does not replace a path entered while connecting, but a new model does', t => {
  const { panel, nodes } = fixture(t);
  nodes['model-paths'].value = '/new/model.stl';
  nodes['model-target-max'].value = '180';
  panel.render(state());
  assert.equal(nodes['model-paths'].value, '/new/model.stl');
  assert.equal(nodes['model-target-max'].value, '180');
  panel.render(state({ print_sources: ['/job/parts/cut.stl'] }));
  assert.equal(nodes['model-paths'].value, '/job/parts/cut.stl');
  assert.equal(nodes['model-target-max'].value, '');
});

test('switching to an empty job clears the old inputs and still rejects preparing no model', t => {
  const { panel, nodes, submissions, errors } = fixture(t);
  panel.render(state());
  panel.render(state({ job: '/empty', inspect_rev: null, print_sources: [], parts: [] }));
  assert.equal(nodes['model-paths'].value, '');
  panel._handlePrepare();
  assert.equal(submissions.length, 0);
  assert.equal(errors.length, 1);
});
