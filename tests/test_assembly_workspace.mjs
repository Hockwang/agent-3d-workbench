import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { supportsAssemblyWorkspace } from '../studio/web/assembly-panel.js';

// Inject workspace children as in test_app_connection.mjs. Drive the real
// controller without creating WebGL renderers or loading a localhost iframe.
const source = await readFile(new URL('../studio/web/workspace.js', import.meta.url), 'utf8');
const controller = source.slice(source.indexOf('export function createWorkspace('))
  .replace(/^export function createWorkspace/, 'function createWorkspace');

function fixture(api = {}) {
  const modes = ['edit', 'motion', 'tasks', 'observe', 'print', 'assembly'];
  const nodes = new Map(), created = [], clearedTimers = [];
  const children = Object.fromEntries(['editor', 'print', 'tasks', 'observe', 'assembly'].map(kind => [kind, []]));
  function node(id = '', tag = 'div') {
    return {
      id, tagName: tag, hidden: id === 'assembly-space', dataset: {}, attributes: {}, children: [],
      setAttribute(name, value) { this.attributes[name] = value; },
      querySelector() { return null; }, insertAdjacentHTML() {},
      before(value) { this.beforeNode = value; },
      append(...values) { this.children.push(...values); },
      replaceWith(value) { this.replacedWith = value; },
    };
  }
  const getNode = id => {
    if (!nodes.has(id)) nodes.set(id, node(id));
    return nodes.get(id);
  };
  const buttons = modes.map(mode => {
    const button = node(); button.dataset.workspaceMode = mode; button.hidden = mode === 'assembly';
    return button;
  });
  const access = {
    modes: [], states: [], disposed: 0,
    setMode(mode) { this.modes.push(mode); }, setState(state) { this.states.push(state); },
    setResults() {}, setError() {}, setPreview() {}, openResults() {},
    dispose() { this.disposed++; },
  };
  const recipes = { disposed: 0 };
  function child(kind, childApi, options) {
    const item = {
      api: childApi, options, ready: Promise.resolve(), states: [], activeValues: [], workspaceModes: [],
      disposed: 0, refreshed: 0,
      setState(state) { this.states.push(state); },
      setActive(value) { this.activeValues.push(value); },
      setWorkspaceMode(mode) { this.workspaceModes.push(mode); },
      refresh() { this.refreshed++; }, dispose() { this.disposed++; },
      fitView() {}, openFile() {}, getMotionContext() { return null; },
    };
    children[kind].push(item); return item;
  }
  const context = {
    supportsAssemblyWorkspace,
    createAssembly: (childApi, options) => child('assembly', childApi, options),
    createEditor: (childApi, options) => child('editor', childApi, options),
    createPrintWorkspace: (childApi, options) => child('print', childApi, options),
    createTasks: (childApi, options) => child('tasks', childApi, options),
    createObserve: childApi => child('observe', childApi),
    createQuickAccess: () => access,
    Recipes: class {
      render() { getNode('recipe').hidden = false; }
      async start() {}
      dispose() { recipes.disposed++; }
    },
    t: key => key, icon: () => '<svg></svg>', recipeStepBaseTool: () => '',
    document: {
      hidden: false,
      createElement(tag) { const item = node('', tag); created.push(item); return item; },
      getElementById: getNode,
      querySelector: () => getNode('brand'),
      querySelectorAll: selector => selector === '[data-workspace-mode]' ? buttons : [],
    },
    setInterval: () => 1,
    clearInterval: timer => clearedTimers.push(timer),
  };
  vm.createContext(context);
  vm.runInContext(`${controller}\nglobalThis.workspaceFactory = createWorkspace;`, context);
  const workspace = context.workspaceFactory(api);
  return {
    workspace, children, access, recipes, buttons, clearedTimers, getNode,
    get workflow() { return created.find(item => item.tagName === 'details'); },
    get mode() { return access.modes.at(-1); },
    get assemblyButton() { return buttons.find(button => button.dataset.workspaceMode === 'assembly'); },
  };
}

test('assembly capability requires the transport to provide assemblyProject', () => {
  for (const api of [null, undefined, {}, { assemblyProject: true }, { capabilities() {} }]) {
    assert.equal(supportsAssemblyWorkspace(api), false);
  }
  assert.equal(supportsAssemblyWorkspace({ assemblyProject() {} }), true);
});

test('MCP transport cannot open assembly through mode changes or restored state', async () => {
  const f = fixture({ getState: async () => ({}) });
  await f.workspace.ready;
  assert.equal(f.assemblyButton.hidden, true);
  f.workspace.setMode('assembly');
  const state = { workspace_mode: 'assembly', workbench: { revision: 7 } };
  f.workspace.setState(state);
  f.assemblyButton.onclick();
  assert.equal(f.mode, 'edit');
  assert.equal(f.children.assembly.length, 0, 'unavailable assembly must never create an iframe child');
  assert.equal(f.getNode('assembly-space').hidden, true);
  assert.equal(f.getNode('editor-space').hidden, false);
  assert.equal(f.children.editor.length, 1);
  assert.equal(f.children.editor[0].states.at(-1), state);
  assert.equal(f.children.editor[0].activeValues.at(-1), true);
  f.workspace.dispose();
});

test('HTTP assembly opens lazily, receives state, and survives return to the editor', async () => {
  const api = { assemblyProject() { throw new Error('controller must not load a project'); } };
  const f = fixture(api);
  await f.workspace.ready;
  assert.equal(f.assemblyButton.hidden, false);
  assert.equal(f.children.assembly.length, 0);
  const state = { workspace_mode: 'assembly', workbench: { revision: 9 } };
  f.workspace.setState(state);
  const assembly = f.children.assembly[0], editor = f.children.editor[0];
  assert.equal(f.children.assembly.length, 1);
  assert.equal(assembly.api, api);
  assert.equal(f.mode, 'assembly');
  assert.equal(assembly.states.at(-1), state);
  assert.equal(assembly.activeValues.at(-1), true);
  assert.equal(editor.activeValues.at(-1), false);
  assert.equal(f.getNode('assembly-space').hidden, false);
  for (const id of ['editor-space', 'print-space', 'task-space', 'observe-space']) assert.equal(f.getNode(id).hidden, true);
  assert.equal(f.workflow.hidden, true, 'the recipe drawer must not cover the assembly panel');
  assert.equal(f.assemblyButton.attributes['aria-pressed'], 'true');
  f.workspace.setMode('edit');
  assert.equal(f.getNode('assembly-space').hidden, true);
  assert.equal(assembly.activeValues.at(-1), false);
  assert.equal(editor.activeValues.at(-1), true);
  assert.equal(f.workflow.hidden, false);
  f.workspace.setMode('assembly');
  assert.equal(f.children.assembly.length, 1, 'mode switches retain the existing assembly child');
  assert.equal(assembly.states.at(-1), state);
  f.workspace.dispose();
});

test('assembly follows host visibility while the other workspace children stay inactive', async () => {
  const f = fixture({ assemblyProject() {} });
  await f.workspace.ready;
  f.workspace.setMode('print');
  f.workspace.setMode('tasks');
  f.workspace.setMode('observe');
  f.workspace.setMode('assembly');
  const assembly = f.children.assembly[0];
  f.workspace.setActive(false);
  assert.equal(assembly.activeValues.at(-1), false);
  const updates = assembly.activeValues.length;
  f.workspace.setActive(false);
  assert.equal(assembly.activeValues.length, updates, 'repeated visibility notifications are no-ops');
  f.workspace.setActive(true);
  assert.equal(assembly.activeValues.at(-1), true);
  for (const kind of ['editor', 'print', 'tasks', 'observe']) {
    assert.equal(f.children[kind][0].activeValues.at(-1), false, `${kind} stays inactive behind assembly`);
  }
  f.workspace.setMode('edit');
  f.workspace.setActive(false); f.workspace.setActive(true);
  assert.equal(assembly.activeValues.at(-1), false);
  assert.equal(f.children.editor[0].activeValues.at(-1), true);
  f.workspace.dispose();
});

test('successful assembly import returns to the editor and refreshes its model', async () => {
  const f = fixture({ assemblyProject() {} });
  await f.workspace.ready;
  f.workspace.setMode('assembly');
  const assembly = f.children.assembly[0], editor = f.children.editor[0];
  assembly.options.onImport();
  assert.equal(f.mode, 'edit');
  assert.equal(editor.refreshed, 1);
  assert.equal(editor.activeValues.at(-1), true);
  assert.equal(assembly.activeValues.at(-1), false);
  assert.equal(f.getNode('editor-space').hidden, false);
  assert.equal(f.getNode('assembly-space').hidden, true);
  f.workspace.dispose();
});

test('workspace disposal releases assembly and preserves existing cleanup', async () => {
  const f = fixture({ assemblyProject() {} });
  await f.workspace.ready;
  for (const mode of ['print', 'tasks', 'observe', 'assembly']) f.workspace.setMode(mode);
  f.workspace.dispose();
  for (const kind of ['editor', 'print', 'tasks', 'observe', 'assembly']) assert.equal(f.children[kind][0].disposed, 1);
  assert.equal(f.access.disposed, 1);
  assert.equal(f.recipes.disposed, 1);
  assert.deepEqual(f.clearedTimers, [1]);
  assert.equal(f.workflow.replacedWith, f.getNode('recipe'));
  for (const button of f.buttons) assert.equal(button.onclick, null);
});
