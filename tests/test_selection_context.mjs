import test from 'node:test';
import assert from 'node:assert/strict';
import { selectionContext, createSelectionContextSync } from '../studio/app/selection-context.js';

const object = (id, name) => ({ id, name, faces: 12, extents_mm: [10, 20, 30], asset: 'large-asset', transform: [] });
test('scene selection carries instance identity and version without mesh payloads', () => {
  const s=state(['a']),o=s.workbench.objects[0];o.version=4;
  o.scene={asset:'version-a',family:'source-a',kind:'skin',bones:34,clips:1};
  const item=selectionContext('edit',s).structuredContent.selectedObjects[0];
  assert.deepEqual(item.instance,{asset:'version-a',family:'source-a',kind:'skin',version:4,transform:[],bones:34,clips:1});
});
function state(ids = [], revision = 1) {
  return { job: '/job', rev: 3, workbench: { revision, selection: ids, objects: [object('a', '底座'), object('b', '机械臂')] },
    selection: { parts: ['body'] }, parts: [{ name: 'body', extents_mm: [40, 50, 60], faces: 24 }] };
}
function host() {
  const calls = [];
  return { calls, sync: createSelectionContextSync({ updateModelContext: async p => { calls.push(p); } }) };
}

test('restoring a selection in two panels does not attach anything without a user action', async () => {
  const a = host(), b = host();
  await a.sync.update({ mode: 'edit', state: state(['a', 'b']) });
  await b.sync.update({ mode: 'edit', state: state(['a', 'b']) });
  assert.ok([...a.calls, ...b.calls].every(p => !p.content?.length && !p.structuredContent));
});

test('a recreated empty panel clears its own previously persisted host context', async () => {
  const { calls, sync } = host();
  await sync.update({ mode: 'edit', state: state() });
  assert.deepEqual(calls, [{ content: [] }]);
});

test('opening an empty workspace never creates an attachment', async () => {
  const { calls, sync } = host();
  await sync.update({ mode: 'edit', state: state() });
  await sync.update({ mode: 'edit', state: state([], 2) });
  assert.deepEqual(calls, [{ content: [] }]);
});

test('only selected objects are included, in selection order, with a readable title', () => {
  const payload = selectionContext('edit', state(['b', 'a']));
  assert.equal(payload.presentation.composerLabel, '已选 2 件：机械臂、底座');
  assert.deepEqual(payload.structuredContent.selectedObjects.map(o => o.id), ['b', 'a']);
  assert.deepEqual(payload.structuredContent.selectedObjects[0], { id: 'b', name: '机械臂', faces: 12, extents_mm: [10, 20, 30] });
  assert.equal(payload.structuredContent.revision, 1);
  assert.match(payload.content[0].text, /studio_get_state/);
  assert.ok(!JSON.stringify(payload).includes('large-asset'));
  assert.equal(selectionContext('edit', state(['missing'])), null);
});

test('only an explicit click attaches; polls and model changes never restore a dismissed card', async () => {
  const { calls, sync } = host();
  const s = state(['a']);
  await sync.update({ mode: 'edit', state: s });
  await sync.attach();
  await sync.update({ mode: 'edit', state: structuredClone(s) });
  assert.equal(calls.length, 2);
  s.workbench.objects[0].name = '新底座';
  s.workbench.objects[0].extents_mm = [20, 20, 30];
  s.workbench.revision++;
  await sync.update({ mode: 'edit', state: s });
  assert.deepEqual(calls[2], { content: [] });
  await sync.update({ mode: 'edit', state: s });
  assert.equal(calls.length, 3);
  await sync.attach();
  assert.equal(calls[3].presentation.composerLabel, '已选 1 件：新底座');
  assert.deepEqual(calls[1].structuredContent.selectedObjects[0].extents_mm, [10, 20, 30]);
  await sync.attach();
  assert.equal(calls.length, 5, 'explicit reattach works after a user dismisses the card');
});

test('deselection removes the previous attachment using an empty request, not empty structured data', async () => {
  const { calls, sync } = host();
  await sync.update({ mode: 'edit', state: state(['a']) });
  await sync.attach();
  await sync.update({ mode: 'edit', state: state() });
  await sync.update({ mode: 'edit', state: state() });
  await sync.attach();
  assert.deepEqual(calls[2], { content: [] });
  assert.equal(calls.length, 3, 'attaching an empty selection does nothing');
});

test('switching modes clears context without automatically attaching another selection', async () => {
  const { calls, sync } = host();
  const s = state(['a']);
  await sync.update({ mode: 'edit', state: s });
  await sync.attach();
  await sync.update({ mode: 'print', state: s });
  assert.deepEqual(calls[2], { content: [] });
  await sync.attach();
  assert.equal(calls[3].structuredContent.source, 'Print Prep selection');
  assert.deepEqual(calls[3].structuredContent.selectedParts.map(p => p.name), ['body']);
  assert.equal(calls[3].structuredContent.selectedObjects, undefined);
  await sync.update({ mode: 'tasks', state: s });
  assert.deepEqual(calls[4], { content: [] });
  await sync.update({ mode: 'observe', state: s });
  assert.equal(calls.length, 5);
  await sync.update({ mode: 'edit', state: s });
  assert.equal(calls.length, 5);
});

test('deselection during an in-flight attachment clears it after the request completes', async () => {
  const calls = []; let release;
  const sync = createSelectionContextSync({ updateModelContext: async p => {
    calls.push(p);
    if (p.structuredContent) await new Promise(resolve => { release = resolve; });
  }});
  await sync.update({ mode: 'edit', state: state(['a']) });
  const first = sync.attach();
  const second = sync.update({ mode: 'edit', state: state(['b']) });
  const third = sync.update({ mode: 'edit', state: state() });
  assert.equal(calls.length, 2);
  release(); await Promise.all([first, second, third]);
  assert.deepEqual(calls, [{ content: [] }, selectionContext('edit', state(['a'])), { content: [] }]);
});

test('failed requests retry only the requested attachment and yield to a later deselection', async () => {
  const calls = []; let reject;
  const sync = createSelectionContextSync({ updateModelContext: async p => {
    calls.push(p);
    if (p.structuredContent) await new Promise((resolve, fail) => { reject = fail; });
  }});
  await sync.update({ mode: 'edit', state: state(['a']) });
  const first = sync.attach();
  const second = sync.update({ mode: 'edit', state: state(['b']) });
  reject(new Error('temporary host error'));
  await Promise.all([first, second]);
  assert.deepEqual(calls.at(-1), { content: [] });
  let attempts = 0;
  const retry = createSelectionContextSync({ updateModelContext: async () => { if (++attempts === 1) throw new Error('offline'); } });
  await retry.update({ mode: 'edit', state: state(['a']) });
  await retry.update({ mode: 'edit', state: state(['a']) });
  assert.equal(attempts, 2);
});

test('long names keep the card compact without truncating object identities', () => {
  const s = state(['a', 'b']); s.workbench.objects[0].name = '很长的零件名称\n'.repeat(30);
  const p = selectionContext('edit', s);
  assert.ok([...p.presentation.composerLabel].length <= 72);
  assert.ok(!p.presentation.composerLabel.includes('\n'));
  assert.equal(p.structuredContent.selectedObjects[0].name, s.workbench.objects[0].name);
});

test('disposing stops pending updates without changing shared backend state', async () => {
  const { calls, sync } = host();
  const s = state(['a']), before = structuredClone(s);
  await sync.update({ mode: 'edit', state: s });
  await sync.attach();
  await sync.dispose(); await sync.update({ mode: 'edit', state: s });
  await sync.attach();
  assert.equal(calls.length, 3);
  assert.deepEqual(calls.at(-1), { content: [] });
  assert.deepEqual(s, before);
});

test('teardown waits for a pending attachment then removes it', async () => {
  const calls = []; let release;
  const sync = createSelectionContextSync({ updateModelContext: async p => {
    calls.push(p);
    if (p.structuredContent) await new Promise(resolve => { release = resolve; });
  }});
  await sync.update({ mode: 'edit', state: state(['a']) });
  const attaching = sync.attach(), closing = sync.dispose();
  release(); await Promise.all([attaching, closing]);
  assert.deepEqual(calls.at(-1), { content: [] });
});
