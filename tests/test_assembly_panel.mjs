import test from 'node:test';
import assert from 'node:assert/strict';
import { createAssembly, assemblyBackendOrigin } from '../studio/web/assembly-panel.js';
import { createApi, ApiError } from '../studio/web/api.js';
import { t as text, getLocale } from '../studio/web/i18n.js';

const savedGlobals = (t, names) => {
  const previous = names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]);
  t.after(() => { for (const [name, descriptor] of previous) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor);
    else delete globalThis[name];
  } });
};

function panelFixture(t, api = {}) {
  savedGlobals(t, ['document', 'window', 'location']);
  const listeners = new Map();
  const make = tag => ({
    tag, children: [], style: {}, attributes: {}, disabled: false,
    ...(tag === 'iframe' ? { contentWindow: {} } : {}),
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this.attributes[name] = value; },
  });
  const root = make('div'); root.id = 'assembly-space';
  globalThis.document = { getElementById: () => root, createElement: make };
  globalThis.location = { search: '?assemblyBackendPort=8886' };
  globalThis.window = {
    addEventListener(name, callback) { listeners.set(name, callback); },
    removeEventListener(name, callback) { if (listeners.get(name) === callback) listeners.delete(name); },
  };
  const calls = [];
  const transport = {
    async assemblyProject(source) { calls.push(['project', source]); return { import_file: '/tmp/generated/assembly.glb', units: 'm', revision: 7 }; },
    async getState() { calls.push(['state']); return { workbench: { revision: 19 } }; },
    async edit(body) { calls.push(['edit', body]); },
    ...api,
  };
  let imports = 0;
  const component = createAssembly(transport, { onImport: () => { imports++; } });
  const find = (id, element = root) => element.id === id ? element : element.children.map(child => find(id, child)).find(Boolean);
  return { root, calls, component, find, listeners, transport, get imports() { return imports; },
    message(data, source = find('assembly-frame').contentWindow, origin = 'http://127.0.0.1:8886') { listeners.get('message')?.({ data, source, origin }); },
  };
}

test('assembly backend port is local, bounded and cannot become an arbitrary URL', () => {
  assert.equal(assemblyBackendOrigin(), 'http://127.0.0.1:8766');
  assert.equal(assemblyBackendOrigin('?assemblyBackendPort=65535'), 'http://127.0.0.1:65535');
  for (const value of ['0', '1023', '65536', '8766.5', 'https://other.invalid', 'Infinity']) {
    assert.equal(assemblyBackendOrigin('?assemblyBackendPort=' + encodeURIComponent(value)), 'http://127.0.0.1:8766');
  }
});

test('unsupported transports cannot construct an iframe or touch the document', t => {
  savedGlobals(t, ['document']);
  globalThis.document = { getElementById() { assert.fail('unsupported transport touched the DOM'); } };
  assert.throws(() => createAssembly({ init() {}, edit() {} }), new RegExp(text('assembly.error.unavailable')));
});

test('connector messages require the exact iframe and origin and never reload its unsaved view', t => {
  const f = panelFixture(t), frame = f.find('assembly-frame'), workflow = f.find('assembly-workflow');
  const initial = frame.src;
  const event = { type: 'assembly:connector-flow', flow: 'parametric' };
  f.message(event, {}, 'http://127.0.0.1:8886');
  f.message(event, frame.contentWindow, 'http://127.0.0.1:9999');
  f.message({ ...event, type: 'other' });
  f.message({ ...event, flow: 'presets' });
  assert.equal(workflow.value, 'manual');
  f.message(event);
  assert.equal(workflow.value, 'parametric');
  assert.equal(frame.src, initial, 'message synchronization must preserve iframe form state');
  assert.equal(f.find('assembly-independent').href, 'http://127.0.0.1:8886/manual.html?mode=parametric');
  f.component.dispose();
});

test('workflow navigation and parametric import use the saved manual project and current editor revision', async t => {
  const f = panelFixture(t), workflow = f.find('assembly-workflow');
  workflow.value = 'presets'; workflow.onchange();
  assert.equal(f.find('assembly-frame').src, 'http://127.0.0.1:8886/presets.html?embed=1');
  workflow.value = 'legacy'; workflow.onchange();
  assert.equal(f.find('assembly-frame').src, 'http://127.0.0.1:8886/index.html?embed=1');
  workflow.value = 'parametric'; workflow.onchange();
  assert.equal(f.find('assembly-frame').src, 'http://127.0.0.1:8886/manual.html?embed=1&mode=parametric');
  await f.find('assembly-import').onclick();
  assert.deepEqual(f.calls, [
    ['project', 'manual'], ['state'],
    ['edit', { action: 'import', params: { files: ['/tmp/generated/assembly.glb'], units: 'm' }, expected_revision: 19 }],
  ]);
  assert.equal(f.imports, 1);
  assert.equal(f.find('assembly-import').disabled, false);
  assert.equal(workflow.disabled, false);
  f.component.setActive(false); assert.equal(f.find('assembly-frame').style.visibility, 'hidden');
  f.component.setActive(true); assert.equal(f.find('assembly-frame').style.visibility, 'visible');
  f.component.dispose(); assert.equal(f.listeners.size, 0); assert.deepEqual(f.root.children, []);
});

test('missing service gives an actionable message and preserves the current editor', async t => {
  const f = panelFixture(t, { async assemblyProject() { throw new ApiError('not_found', 'missing route'); } });
  await f.find('assembly-import').onclick();
  assert.equal(f.find('assembly-bridge-status').textContent, text('assembly.error.serviceUnavailable', { origin: 'http://127.0.0.1:8886' }));
  assert.equal(f.imports, 0); assert.deepEqual(f.calls, []);
  assert.equal(f.find('assembly-import').disabled, false);
  f.component.dispose();
});

test('invalid units or a missing generated file never reach the native edit API', async t => {
  const f = panelFixture(t, { async assemblyProject() { return { import_file: '/tmp/generated/assembly.glb', units: 'mm' }; } });
  await f.find('assembly-import').onclick();
  assert.match(f.find('assembly-bridge-status').textContent, new RegExp(text('assembly.error.invalidProject')));
  assert.deepEqual(f.calls, []); assert.equal(f.imports, 0);
  f.transport.assemblyProject = async () => ({ units: 'm', revision: 1 });
  await f.find('assembly-import').onclick();
  assert.deepEqual(f.calls, []); assert.equal(f.imports, 0);
  f.component.dispose();
});

test('disposing while the saved project is loading prevents a later editor mutation', async t => {
  let complete;
  const f = panelFixture(t, { assemblyProject() { return new Promise(resolve => { complete = resolve; }); } });
  const pending = f.find('assembly-import').onclick();
  f.component.dispose();
  complete({ import_file: '/tmp/generated/assembly.glb', units: 'm', revision: 1 });
  await pending;
  assert.deepEqual(f.calls, []); assert.equal(f.imports, 0);
});

const response = (status, value) => ({ ok: status >= 200 && status < 300, status, statusText: '', text: async () => JSON.stringify(value) });
test('HTTP assembly bridge scopes requests and recovers a changed session token once', async t => {
  savedGlobals(t, ['fetch', 'location']);
  globalThis.location = { search: '?workspace=task-a' };
  const requests = []; let sessions = 0, projects = 0;
  globalThis.fetch = async (path, options) => {
    requests.push({ path, ...options });
    if (path === '/api/session') return response(200, { token: `session-${++sessions}`, job: 'local-project' });
    if (++projects === 1) return response(403, { error: { code: 'forbidden', message: 'stale session' } });
    return response(200, { source: 'manual', units: 'm', import_file: '/tmp/generated/assembly.glb' });
  };
  const api = createApi();
  const result = await api.assemblyProject('manual');
  assert.equal(result.units, 'm');
  assert.deepEqual(requests.map(r => r.path), ['/api/session', '/api/assembly/project?source=manual', '/api/session', '/api/assembly/project?source=manual']);
  const projectRequests = requests.filter(r => r.path.startsWith('/api/assembly/'));
  assert.deepEqual(projectRequests.map(r => r.headers['X-Studio-Token']), ['session-1', 'session-2']);
  assert.ok(projectRequests.every(r => r.method === 'GET' && r.headers['X-Studio-Workspace'] === 'task-a' && r.headers['Accept-Language'] === getLocale()));
  assert.ok(projectRequests.every(r => r.body === undefined && !r.headers['X-Studio-Actor']));
});

test('HTTP bridge rejects unsupported sources locally and does not retry an unfinished project', async t => {
  savedGlobals(t, ['fetch', 'location']);
  globalThis.location = { search: '' };
  const paths = [];
  globalThis.fetch = async path => {
    paths.push(path);
    return path === '/api/session' ? response(200, { token: 'test-session', job: 'local-project' })
      : response(409, { error: { code: 'project_not_ready', message: 'generate first' } });
  };
  const api = createApi();
  await assert.rejects(api.assemblyProject('parametric'), { code: 'invalid_source' });
  assert.deepEqual(paths, []);
  await assert.rejects(api.assemblyProject('presets'), { code: 'project_not_ready', message: 'generate first' });
  assert.deepEqual(paths, ['/api/session', '/api/assembly/project?source=presets']);
});
