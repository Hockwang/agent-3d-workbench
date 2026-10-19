import test from 'node:test';
import assert from 'node:assert/strict';
import { createQuickAccess } from '../studio/web/quick-access.js';

class Element {
  children = []; dataset = {}; attributes = {}; value = ''; open = false; hidden = false;
  className = ''; textContent = ''; disabled = false;
  constructor(tag) { this.tagName = tag.toUpperCase(); }
  append(...nodes) { this.children.push(...nodes); for (const node of nodes) node.parent = this; }
  after(...nodes) { this.parent?.append(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener() {}
  focus() {}
  remove() {}
  click() { if (!this.disabled) return this.onclick?.(); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  get classList() { return { toggle: () => {} }; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...((selector.startsWith('.') ? child.className.split(' ').includes(selector.slice(1)) : selector === '[data-result-id]' && child.dataset.resultId) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0]; }
}

function setup(t, onPrintTask, onOpenResult = () => {}) {
  const original = globalThis.document, root = new Element('main'), nav = new Element('nav');
  nav.parent = root;
  globalThis.document = { createElement: tag => new Element(tag), getElementById: id => id === 'wb' ? root : nav };
  t.after(() => { globalThis.document = original; });
  const access = createQuickAccess({ api: {}, onPrintTask, onOpenResult });
  t.after(() => access.dispose());
  return { access, root };
}

const task = (id, artifacts) => ({ id, status: 'completed', title: id, created: 1, artifacts });
const model = (id, extra = {}) => ({ id, name: `${id}.glb`, ...extra });

for (const mode of ['edit', 'motion', 'tasks', 'observe', 'print']) {
  test(`task overview can load a print copy when opened from ${mode}`, async t => {
    const calls = [];
    const { access, root } = setup(t, async (taskId, artifactId) => {
      calls.push([taskId, artifactId]);
      access.setMode('print');
    });
    access.setResults([task('cup', [model('body')])]);
    access.setMode(mode);
    access.openResults();
    const dialog = root.querySelector('.quick-results');
    const button = dialog.querySelector('.result-print-load');
    assert.ok(button, 'the dialog action must not depend on the workspace it was opened from');
    assert.equal(button.disabled, false);
    await button.click();
    assert.deepEqual(calls, [['cup', 'body']]);
    assert.equal(dialog.open, false);
    assert.equal(root.querySelector('.result-shelf').hidden, false);
  });
}

test('print preparation displays the same saved models and updates controls across modes', t => {
  const { access, root } = setup(t, () => {});
  access.setResults([task('static', [model('body')]), task('animated', [model('walk', { animations: 1 })])]);
  access.setMode('print');
  const shelf = root.querySelector('.result-shelf');
  assert.equal(shelf.hidden, false);
  assert.equal(shelf.querySelectorAll('.result-card').length, 2);
  const buttons = shelf.querySelectorAll('.result-print-load');
  assert.deepEqual(buttons.map(button => button.disabled), [false, false]);
  access.setState({ busy: { op: 'load' } });
  assert.ok(buttons.every(button => button.disabled));
  access.setState({ busy: null });
  assert.equal(buttons[0].disabled, false);
  access.setMode('edit');
  assert.equal(shelf.hidden, true);
  assert.equal(root.querySelectorAll('.result-print-load').length, 0);
  access.setMode('print');
  assert.equal(shelf.hidden, false);
});

test('printing card loads the primary model, not an inspection proxy or HTML viewer', async t => {
  const loaded = [], viewed = [];
  const { access, root } = setup(t, (...args) => loaded.push(args), (...args) => viewed.push(args));
  access.setResults([task('kit', [model('proxy', { name: 'inspection/head.glb' }), model('main', { name: 'scene.glb' }), { id: 'html', name: 'index.html' }])]);
  access.setMode('print');
  await root.querySelector('.result-card').querySelector('.result-open').click();
  assert.deepEqual(loaded, [['kit', 'main']]);
  assert.deepEqual(viewed, []);
});

test('animated artifact opens the exact selected model to choose a print pose', async t => {
  const loaded = [], viewed = [];
  const { access, root } = setup(t, (...args) => loaded.push(args), (...args) => viewed.push(args));
  access.setResults([task('walk', [model('a', { skins: 1 }), model('b', { animations: 1 })])]);
  access.setMode('print'); access.openResults();
  const [picker, button] = root.querySelector('.quick-results').querySelector('.result-print-controls').children;
  picker.value = 'b'; picker.onchange(); await button.click();
  assert.deepEqual(viewed, [['walk', false, 'b']]);
  assert.deepEqual(loaded, []);
});

test('multi-model task passes the explicitly chosen artifact once and keeps failures visible', async t => {
  let calls = [], rejectLoad;
  const { access, root } = setup(t, (taskId, artifactId) => {
    calls.push([taskId, artifactId]);
    access.setMode('print');
    return new Promise((_, reject) => { rejectLoad = reject; });
  });
  access.setResults([task('kit', [model('front'), model('back')])]);
  access.setMode('edit'); access.openResults();
  const dialog = root.querySelector('.quick-results');
  const controls = dialog.querySelector('.result-print-controls');
  const [select, button, note] = controls.children;
  assert.equal(select.hidden, false);
  select.value = 'back'; select.onchange();
  const pending = button.click(); button.click();
  assert.deepEqual(calls, [['kit', 'back']]);
  assert.ok(root.querySelectorAll('.result-print-load').every(item => item.disabled));
  rejectLoad(new Error('Source model changed'));
  await pending;
  assert.equal(dialog.open, true);
  assert.equal(dialog.querySelector('.result-print-controls').children[2], note);
  assert.equal(note.textContent, 'Source model changed');
  assert.equal(button.disabled, false);
});
