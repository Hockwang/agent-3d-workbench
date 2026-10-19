import test from 'node:test';
import assert from 'node:assert/strict';
import { fitRecovery, createFitNotice } from '../studio/web/print-fit.js';
import { cutSource, cutIds, cutView, trackCut, replacementFiles } from '../studio/web/print-cut.js';
import { Panel } from '../studio/web/panel.js';

const printState = () => ({ printer: { name: 'P1S' },
  parts: [{name: 'ear', stl_url: 'ear?v=1'}, {name: 'shell', stl_url: 'shell?v=2'}],
  print_sources: ['/parts/ear.stl', '/parts/shell.stl'] });

test('cutting isolates the target and descendants in the view without changing the original scene', () => {
  const state = { revision: 7, objects: [
    { id: 'desk', visible: true }, { id: 'old-hidden', visible: false },
    { id: 'shell', visible: true },
  ], selection: ['desk', 'shell'] };
  const snapshot = structuredClone(state);
  const context = { knownIds: ['shell', 'left', 'right'] };
  assert.deepEqual(cutView(context, state).objects.map(o => o.id), ['shell']);
  assert.deepEqual(cutView(context, state).selection, ['shell']);
  const split = { ...state, objects: [state.objects[0], { id: 'left' }, { id: 'right' }], selection: ['left', 'right'] };
  assert.deepEqual(cutView(context, split).objects.map(o => o.id), ['left', 'right']);
  assert.deepEqual(cutView({ knownIds: [] }, state).objects, [], 'pending import must not show unrelated scene');
  assert.equal(cutView(null, state), state, 'ending the cut restores the original scene view');
  assert.deepEqual(state, snapshot, 'view filtering must not persist visibility changes');
});

test('multi-plate recovery overrides a local single choice even when the last saved mode was already auto', t => {
  const original = globalThis.document;
  const nodes = {
    'mode-select': { tagName: 'SELECT', options: ['auto', 'single', 'per_part'].map(value => ({ value })), value: 'auto' },
    'gap-input': { value: '60' },
  };
  globalThis.document = { getElementById: id => nodes[id] };
  t.after(() => { globalThis.document = original; });
  const panel = Object.create(Panel.prototype);
  let checked;
  panel._modeChoice = { refresh() { checked = nodes['mode-select'].value; } };
  panel._syncControl('mode-select', 'auto');
  nodes['mode-select'].value = 'single'; panel._modeChoice.refresh();
  panel._syncControl('mode-select', 'auto');
  assert.equal(checked, 'single', 'ordinary polling preserves the user’s unsent choice');
  assert.deepEqual(panel.useAutomaticArrangement(), { mode: 'auto', gap: 60 });
  panel._syncControl('mode-select', 'auto');
  assert.equal(checked, 'auto', 'explicit recovery updates the visible radio even for an unchanged backend mode');
  nodes['gap-input'].value = '0';
  assert.deepEqual(panel.bodyFor('arrange'), { mode: 'auto', gap: 0 });
});

test('single oversized part and plate crowding offer distinct recoveries', () => {
  const state = printState();
  const large = fitRecovery({code:'part_too_large',payload:{part:'shell',dims_mm:[300,150,300],available_mm:[246,246,245]}}, state);
  assert.equal(large.canCut, true);
  assert.equal(large.part, 'shell');
  assert.deepEqual(large.dims, [300,150,300]);
  const crowded = fitRecovery({code:'single_plate_overflow',payload:{needed_plates_with_auto:3}}, state);
  assert.equal(crowded.plates, 3);
  assert.equal(crowded.canCut, false);
  assert.equal(fitRecovery({code:'network_error'}, state), null);
  assert.equal(fitRecovery({code:'part_too_large',payload:{part:'missing'}}, state).canCut, false);
  const failed = fitRecovery({code:'auto_cut_closed', message:'Repair first', payload:{part:'shell'}}, state);
  assert.equal(failed.automaticFailed, true);
  assert.equal(failed.canCut, true);
  assert.equal(failed.message, 'Repair first');
});

test('repeated cuts, undo and redo retain the recovery group and exclude unrelated scene objects', () => {
  const context = cutSource(printState(), 'shell'); context.knownIds = ['copy'];
  const before = {objects:[{id:'unrelated'},{id:'copy'}],selection:['copy']};
  const split = {objects:[{id:'unrelated'},{id:'half1'},{id:'half2'}],selection:['half1','half2']};
  trackCut(context,before,split,'plane_cut');
  assert.deepEqual(cutIds(context,split), ['half1','half2']);
  const splitAgain = {objects:[{id:'unrelated'},{id:'half2'},{id:'quarter1'},{id:'quarter2'}]};
  trackCut(context,{...split,selection:['half1']},splitAgain,'plane_cut');
  assert.deepEqual(cutIds(context,splitAgain), ['half2','quarter1','quarter2']);
  assert.deepEqual(cutIds(context,before), ['copy'], 'undo can restore the imported object');
  assert.deepEqual(cutIds(context,split), ['half1','half2'], 'redo restores the cut objects');
  trackCut(context,split,{objects:[...split.objects,{id:'new-unrelated'}]},'import');
  assert.equal(context.knownIds.includes('new-unrelated'),false);
});

test('returning cut pieces replaces only the target and never silently overwrites a changed print job', () => {
  const state = printState(), context = cutSource(state,'shell');
  assert.deepEqual(replacementFiles(context,state,['/cut/a.stl','/cut/b.stl']),['/parts/ear.stl','/cut/a.stl','/cut/b.stl']);
  assert.throws(()=>replacementFiles(context,{...state,printer:{name:'A1'}},['/cut/a.stl']),/已改变/);
  assert.throws(()=>replacementFiles(context,{...state,parts:[state.parts[0],{...state.parts[1],stl_url:'shell?v=3'}]},['/cut/a.stl']),/已改变/);
  assert.throws(()=>replacementFiles(context,state,[]),/没有可返回/);
  assert.throws(()=>cutSource(state,'absent'),/找不到/);
});

test('a notice hidden by a workspace switch can reopen, while a dismissed notice stays dismissed', t => {
  const original = globalThis.document;
  const nodes = [];
  globalThis.document = { getElementById: () => ({ append() {} }), createElement(tag) {
    const node = { tag, children: [], open: false, append(...items) { this.children.push(...items); },
      replaceChildren() { this.children = []; }, setAttribute() {}, addEventListener() {},
      showModal() { this.open = true; }, close() { this.open = false; }, remove() {} };
    nodes.push(node); return node;
  }};
  t.after(() => { globalThis.document = original; });
  const notice = createFitNotice({}), state = printState();
  const failure = { code: 'part_too_large', payload: { part: 'shell' } };
  const dialog = nodes.find(n => n.tag === 'dialog');
  notice.update(failure, state, true); assert.equal(dialog.open, true);
  notice.update(failure, state, false); assert.equal(dialog.open, false);
  notice.update(failure, state, true); assert.equal(dialog.open, true);
  dialog.close(); notice.update(failure, state, true); assert.equal(dialog.open, false);
  notice.reset(); notice.update(failure, state, true); assert.equal(dialog.open, true);
});

test('automatic recovery invokes the whole-copy action and leaves manual cutting as a separate choice', async t => {
  const original = globalThis.document, nodes = [], calls = [];
  globalThis.document = { getElementById: () => ({ append() {} }), createElement(tag) {
    const node = { tag, children: [], open: false, append(...items) { this.children.push(...items); },
      replaceChildren() { this.children = []; }, setAttribute() {}, addEventListener() {},
      showModal() { this.open = true; }, close() { this.open = false; }, remove() {} };
    nodes.push(node); return node;
  }};
  t.after(() => { globalThis.document = original; });
  const notice = createFitNotice({ onCut: name => calls.push(name), onAutoCut: () => calls.push('all') });
  notice.update({code:'part_too_large',payload:{part:'shell'}}, printState(), true);
  const buttons = nodes.filter(n=>n.tag==='button');
  assert.equal(buttons[0].textContent, '自动切割并摆盘');
  assert.equal(buttons[1].textContent, '手动切割');
  await buttons[0].onclick();
  assert.deepEqual(calls, ['all']);
  assert.equal(nodes.find(n=>n.tag==='dialog').open, false);
});
