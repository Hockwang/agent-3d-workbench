import test from 'node:test';
import assert from 'node:assert/strict';
import { createPartChatController, operationId } from '../studio/web/part-chat.js';

test('sandboxed hosts without randomUUID still generate valid v4 operation identities', () => {
  const id = operationId({getRandomValues: a => a.fill(42)});
  assert.match(id, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
});

test('duplicate clicks share request; rejected transport retains operation ID for retry', async () => {
  const calls = []; let fail = true, reject;
  const controller = createPartChatController({partChat: body => {
    calls.push(body); return fail ? new Promise((_, no) => { reject = no; }) : Promise.resolve({status:'bound'});
  }}, () => 'operation-1');
  const first = controller.create({id:'a'}, 3);
  assert.equal(controller.create({id:'a'}, 3), first);
  reject(new Error('timeout')); await assert.rejects(first, /timeout/); fail = false;
  await controller.create({id:'a'}, 4);
  assert.equal(calls.length, 2); assert.equal(calls[0].operation_id, calls[1].operation_id);
  assert.equal(calls[1].expected_revision, 4);
});

test('permission is explicit and recovered operation is reused after a reload', async () => {
  const calls=[]; const controller=createPartChatController({partChat:async body=>{calls.push(body);return {};}});
  await controller.status(); await controller.permission(false); await controller.permission(true);
  await controller.create({id:'a'},2,'persisted-op');
  assert.deepEqual(calls.slice(0,3),[{action:'status'},{action:'deny'},{action:'allow'}]);
  assert.equal(calls[3].operation_id,'persisted-op');
});
