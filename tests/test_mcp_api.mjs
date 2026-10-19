import test from "node:test";
import assert from "node:assert/strict";
import { createMcpApi, payload } from "../studio/app/api.js";
import { downloadFile } from '../studio/web/download.js';

test('shared export delivers exact binary bytes and a safe filename through the MCP host', async () => {
  const calls = [];
  const api = createMcpApi({ downloadFile: async request => { calls.push(request); return {}; } });
  const bytes = Uint8Array.from([0, 255, 1, 128]);
  await downloadFile(api, bytes.subarray(1, 3), 'artifacts/蘑菇 sample.glb', 'model/gltf-binary');
  const resource = calls[0].contents[0].resource;
  assert.equal(calls[0].contents[0].type, 'resource');
  assert.equal(resource.uri, 'file:///%E8%98%91%E8%8F%87%20sample.glb');
  assert.equal(resource.mimeType, 'model/gltf-binary');
  assert.deepEqual(Buffer.from(resource.blob, 'base64'), Buffer.from([255, 1]));
});

test('host download denial and transport failure are reported, never silently retried in the iframe', async () => {
  await assert.rejects(downloadFile(createMcpApi({ downloadFile: async () => ({isError:true}) }), 'report', 'report.json'), /取消|拒绝/);
  await assert.rejects(downloadFile(createMcpApi({ downloadFile: async () => { throw new Error('host disconnected'); } }), '', 'file'), /host disconnected/);
  await assert.rejects(downloadFile(createMcpApi({}), '', 'file'), /不支持下载/);
});

test('older hosts open a workspace-scoped download page without exposing binary data or tokens in the URL', async () => {
  const opened = [], calls = [];
  const api = createMcpApi({
    downloadFile: async () => { throw Object.assign(new Error('Method not found'), {code:-32601}); },
    callServerTool: async request => { calls.push(request); return {structuredContent:{url:'http://127.0.0.1:55606/?workspace=task-a'}}; },
    openLink: async request => { opened.push(request.url); return {}; },
  }, 'task-a');
  await downloadFile(api, 'test', 'file.svg', 'image/svg+xml', {kind:'laser',id:'flow',artifact:'nest/sheet-01.svg'});
  assert.equal(calls[0].arguments.presentation, 'browser');
  assert.equal(calls[0].arguments.workspace_id, 'task-a');
  const url = new URL(opened[0]);
  assert.equal(url.pathname, '/download.html');
  assert.deepEqual(Object.fromEntries(url.searchParams), {workspace:'task-a',kind:'laser',id:'flow',artifact:'nest/sheet-01.svg'});
});

test('download compatibility path rejects nonlocal targets and respects host denial', async () => {
  const api = createMcpApi({
    callServerTool: async () => ({structuredContent:{url:'https://example.com'}}),
    openLink: async () => assert.fail('must not open a remote target'),
  }, 'task-a');
  await assert.rejects(downloadFile(api, '', 'file', '', {kind:'task',id:'t',artifact:'a'}), /不支持下载/);
  let called = false;
  const denied = createMcpApi({downloadFile:async()=>({isError:true}),callServerTool:async()=>{called=true;}}, 'task-a');
  await assert.rejects(downloadFile(denied, '', 'file', '', {kind:'task',id:'t',artifact:'a'}), /取消|拒绝/);
  assert.equal(called,false);
});

test('workspace binding scopes tool calls and every asset resource and cannot drift', async () => {
  const calls = [], reads = [];
  const api = createMcpApi({
    callServerTool: async request => { calls.push(request); return { structuredContent: { ok: true } }; },
    readServerResource: async request => { reads.push(request.uri); return { contents: [{ blob: '', text: '{}' }] }; },
  }, 'task-a');
  await api.edit({ action: 'inspect' }); await api.getState();
  await api.editorAsset({ asset: 'abc' }); await api.taskAsset('task', { id: 'file' }, { presentation: true }); await api.getShapes();
  assert.ok(calls.every(call => call.arguments.workspace_id === 'task-a'));
  assert.deepEqual(reads, ['print-prep://editor/abc?workspace=task-a', 'print-prep://task/task/file?presentation=studio&workspace=task-a', 'print-prep://catalog/shapes?workspace=task-a']);
  assert.throws(() => api.bindWorkspace('task-b'), /另一个任务/);
});

test("workspace writes keep their human attribution across the MCP transport", async () => {
  const calls = [];
  const api = createMcpApi({ callServerTool: async (request) => {
    calls.push(request);
    return { structuredContent: { ok: true } };
  }});
  await api.getState();
  await api.select(["body"]);
  await api.undo(12);
  await api.send({ dry_run: true });
  await api.evaluation({ action: 'review', id: 'cr-1', expected_sha256: 'evidence' });
  assert.deepEqual(calls, [
    { name: "studio_get_state", arguments: {} },
    { name: "studio_ui_action", arguments: { name: "studio_select", arguments: { parts: ["body"] } } },
    { name: "studio_ui_action", arguments: { name: "studio_undo", arguments: { id: 12 } } },
    { name: "studio_ui_action", arguments: { name: "studio_send_to_slicer", arguments: { dry_run: true } } },
    { name: "studio_ui_action", arguments: { name: "studio_evaluation", arguments: { action: 'review', id: 'cr-1', expected_sha256: 'evidence' } } },
  ]);
});

test('setUiNonce attaches ui_nonce to studio_ui_action and studio_part_chat calls, omitted until set', async () => {
  const calls = [];
  const api = createMcpApi({ callServerTool: async (request) => {
    calls.push(request);
    return { structuredContent: { ok: true } };
  }}, 'task-a');
  await api.select(["body"]);
  assert.deepEqual(calls[0], {
    name: "studio_ui_action",
    arguments: { name: "studio_select", arguments: { parts: ["body"], workspace_id: "task-a" }, workspace_id: "task-a" },
  });
  api.setUiNonce("nonce-1");
  await api.select(["body"]);
  await api.partChat({ action: "status" });
  assert.deepEqual(calls[1], {
    name: "studio_ui_action",
    arguments: {
      name: "studio_select",
      arguments: { parts: ["body"], workspace_id: "task-a" },
      ui_nonce: "nonce-1",
      workspace_id: "task-a",
    },
  });
  assert.deepEqual(calls[2], {
    name: "studio_part_chat",
    arguments: { action: "status", ui_nonce: "nonce-1", workspace_id: "task-a" },
  });
});

test('a human_required write refreshes the nonce via one studio_open call and retries the same write once', async () => {
  const calls = [];
  let uiActionAttempts = 0;
  const api = createMcpApi({
    callServerTool: async (request) => {
      calls.push(request);
      if (request.name === 'studio_open') {
        return { _meta: { 'studio/uiNonce': 'nonce-2' }, structuredContent: { ok: true } };
      }
      uiActionAttempts += 1;
      if (uiActionAttempts === 1) {
        return { isError: true, content: [{ type: 'text', text: JSON.stringify({ ok: false, error: { code: 'human_required', message: 'sign in' } }) }] };
      }
      return { structuredContent: { ok: true } };
    },
  }, 'task-a');
  api.setUiNonce('nonce-1');
  await api.select(['body']);
  assert.deepEqual(calls.map((c) => c.name), ['studio_ui_action', 'studio_open', 'studio_ui_action']);
  assert.equal(calls[0].arguments.ui_nonce, 'nonce-1');
  assert.equal(calls[1].arguments.workspace_id, 'task-a');
  assert.equal(calls[2].arguments.ui_nonce, 'nonce-2');
});

test('a second human_required after the refreshed retry is surfaced, not looped', async () => {
  const calls = [];
  const api = createMcpApi({
    callServerTool: async (request) => {
      calls.push(request);
      if (request.name === 'studio_open') {
        return { _meta: { 'studio/uiNonce': 'nonce-2' }, structuredContent: { ok: true } };
      }
      return { isError: true, content: [{ type: 'text', text: JSON.stringify({ ok: false, error: { code: 'human_required', message: 'still no' } }) }] };
    },
  }, 'task-a');
  api.setUiNonce('nonce-1');
  await assert.rejects(api.select(['body']), (error) => error.code === 'human_required');
  assert.deepEqual(calls.map((c) => c.name), ['studio_ui_action', 'studio_open', 'studio_ui_action']);
});

test('part chat recovers from human_required through the same one-shot nonce refresh', async () => {
  const calls = [];
  let attempts = 0;
  const api = createMcpApi({
    callServerTool: async (request) => {
      calls.push(request);
      if (request.name === 'studio_open') {
        return { _meta: { 'studio/uiNonce': 'nonce-2' }, structuredContent: { ok: true } };
      }
      attempts += 1;
      if (attempts === 1) {
        return { isError: true, content: [{ type: 'text', text: JSON.stringify({ ok: false, error: { code: 'human_required', message: 'sign in' } }) }] };
      }
      return { structuredContent: { ok: true, status: 'bound' } };
    },
  }, 'task-a');
  api.setUiNonce('nonce-1');
  await api.partChat({ action: 'status' });
  assert.deepEqual(calls.map((c) => c.name), ['studio_part_chat', 'studio_open', 'studio_part_chat']);
  assert.equal(calls[2].arguments.ui_nonce, 'nonce-2');
});

test("MCP errors retain codes for the workspace busy and error states", () => {
  assert.throws(() => payload({ isError: true, content: [{ type: "text", text: JSON.stringify({ ok: false, error: { code: "busy", message: "Please wait" } }) }] }),
    (error) => error.code === "busy" && error.message === "Please wait");
});

test('MCP fit errors preserve structured recovery data instead of only message text', () => {
  const value = { ok: false, error: { code: 'part_too_large', message: 'too large' }, part: 'shell', dims_mm: [300, 150, 300], available_mm: [246, 246, 245] };
  assert.throws(() => payload({ structuredContent: value }), error => error.payload === value);
});

test('part chat calls a scoped app-only tool and never sends a parent message', async () => {
  const calls = [], links = [];
  const api = createMcpApi({sendMessage: async () => { throw new Error('must not send'); },
    openLink: async request => { links.push(request); return {}; },
    callServerTool: async request => { calls.push(request); return {structuredContent:{ok:true,status:'bound'}}; }}, 'owner');
  await api.partChat({action:'create',object_id:'part-a',expected_revision:7,operation_id:'op-1'});
  assert.deepEqual(calls[0], {name:'studio_part_chat',arguments:{workspace_id:'owner',action:'create',object_id:'part-a',expected_revision:7,operation_id:'op-1'}});
  const url = 'codex://threads/22222222-2222-4222-8222-222222222222';
  await api.openPartChat(url); assert.deepEqual(links, [{url}]);
  await assert.rejects(api.openPartChat('javascript:bad'), /无效/);
});
