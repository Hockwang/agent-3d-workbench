import test from 'node:test';
import assert from 'node:assert/strict';
import { createRefreshQueue } from '../studio/web/refresh-queue.js';

test('write completion during an in-flight busy read always fetches the final idle state', async () => {
  let complete, calls = 0, rendered;
  const refresh = createRefreshQueue(async () => {
    if (++calls === 1) { await new Promise(resolve => { complete = resolve; }); rendered = 'busy'; }
    else rendered = 'idle';
  });
  const pending = refresh();
  const completedWrite = refresh(true);
  complete(); await Promise.all([pending, completedWrite]);
  assert.equal(calls, 2); assert.equal(rendered, 'idle');
});

test('polls share a pending read and failures do not permanently block later refreshes', async () => {
  let fail, calls = 0;
  const refresh = createRefreshQueue(async () => { if (++calls === 1) await new Promise((_,reject) => { fail = reject; }); });
  const first = refresh(), shared = refresh();
  assert.equal(first, shared); fail(new Error('offline'));
  await assert.rejects(first, /offline/); await refresh(); assert.equal(calls, 2);
});
