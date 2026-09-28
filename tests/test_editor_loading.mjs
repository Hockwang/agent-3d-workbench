import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { EditorViewport } from '../studio/web/editor-viewport.js';

function loadingView(loadAsset) {
  const view = Object.create(EditorViewport.prototype);
  view.scene = new THREE.Scene(); view.entries = new Map();
  view.loop = { invalidate() {} }; view.apply = view.selection = view.fit = () => {};
  view.onError = () => {}; view.release = () => {}; view.loadAsset = loadAsset;
  view.loader = { parseAsync: async () => ({ scene: new THREE.Group() }) };
  return view;
}

test('large editor projects bound asset requests and recover after one failure', async () => {
  let active = 0, peak = 0;
  const loaded = [], errors = [];
  const view = loadingView(async obj => {
    peak = Math.max(peak, ++active); loaded.push(obj.id);
    await new Promise(resolve => setImmediate(resolve));
    active--;
    if (obj.id === '0') throw new Error('unavailable asset');
    return new ArrayBuffer(1);
  });
  view.onError = error => errors.push(error.message);
  const objects = Array.from({ length: 47 }, (_, i) => ({ id: String(i), asset: String(i), visible: true }));
  await view.update({ objects });
  for (let i = 0; i < 100 && loaded.length < objects.length; i++) await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(peak, 1, 'editor assets must not flood the host request queue');
  assert.equal(loaded.length, 47);
  assert.deepEqual(errors, ['unavailable asset']);
  assert.ok(view.entries.get('46').root);
});

test('hidden history is lazy-loaded when made visible', async () => {
  const loaded = [];
  const view = loadingView(async obj => { loaded.push(obj.id); return new ArrayBuffer(1); });
  const hidden = { id: 'history', asset: 'old', visible: false };
  const visible = { id: 'current', asset: 'new', visible: true };
  await view.update({ objects: [hidden, visible] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(loaded, ['current']);
  await view.update({ objects: [{ ...hidden, visible: true }, visible] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(loaded, ['current', 'history']);
});

test('editor keeps prior mesh on load failure and supports explicit retry', async () => {
  const view = Object.create(EditorViewport.prototype);
  const previous = new THREE.Group(), replacement = new THREE.Group(), failures = [];
  view.scene = new THREE.Scene(); view.scene.add(previous);
  view.entries = new Map([['part', { asset: 'old', root: previous }]]);
  view.loop = { invalidate() {} }; view.apply = view.selection = view.fit = () => {};
  view.onError = error => failures.push(error.message);
  view.release = () => {}; view.loadAsset = async () => new ArrayBuffer(1);
  let reject = true;
  view.loader = { parseAsync: async () => { if (reject) throw new Error('GLB failed'); return { scene: replacement }; } };
  await view.update({ objects: [{ id: 'part', asset: 'new' }] });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(failures, ['GLB failed']);
  assert.equal(view.entries.get('part').root, previous);
  assert.ok(view.scene.children.includes(previous));
  reject = false; view.retryFailed();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(view.entries.get('part').root, replacement);
  assert.ok(!view.scene.children.includes(previous));
});

test('queued objects hidden, removed or replaced are skipped and can be shown again', async () => {
  let finishFirst;
  const loaded = [], parsed = [];
  const view = loadingView(async obj => { loaded.push(obj.asset); return obj.asset; });
  view.loader.parseAsync = async asset => {
    parsed.push(asset);
    if (asset === 'first') await new Promise(resolve => { finishFirst = resolve; });
    return { scene: new THREE.Group() };
  };
  const objects = ['first', 'hidden', 'removed', 'replaced'].map(id => ({ id, asset: id, visible: true }));
  await view.update({ objects });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(loaded, ['first'], 'parsing must also hold the queue slot');
  const current = [objects[0], { ...objects[1], visible: false }, { ...objects[3], asset: 'new' }];
  await view.update({ objects: current });
  finishFirst();
  await view.assetQueue;
  assert.deepEqual(loaded, ['first', 'new']);
  assert.deepEqual(parsed, ['first', 'new']);
  await view.update({ objects: current.map(obj => ({ ...obj, visible: true })) });
  await view.assetQueue;
  assert.deepEqual(loaded, ['first', 'new', 'hidden']);
  assert.ok(view.entries.get('hidden').root);
});

test('disposed viewport drops queued reads and releases the in-flight scene', async () => {
  let finish;
  const loaded = [], released = [], scene = new THREE.Group();
  const view = loadingView(async obj => { loaded.push(obj.id); return new ArrayBuffer(1); });
  view.loader.parseAsync = () => new Promise(resolve => { finish = () => resolve({ scene }); });
  view.release = root => released.push(root);
  await view.update({ objects: ['first', 'queued'].map(id => ({ id, asset: id, visible: true })) });
  await new Promise(resolve => setImmediate(resolve));
  view.disposed = true;
  finish();
  await view.assetQueue;
  assert.deepEqual(loaded, ['first']);
  assert.deepEqual(released, [scene]);
  assert.deepEqual(view.scene.children, []);
});

test('changing preview mode retains old mesh units until replacement arrives', () => {
  const view=Object.create(EditorViewport.prototype);view.motionMode=true;
  const root=new THREE.Group(),obj={transform:[[1,0,0,20],[0,1,0,0],[0,0,1,0],[0,0,0,1]],visible:true,motion:{kind:'skin'}};
  view.apply(root,obj);assert.equal(root.scale.x,1);assert.equal(root.position.x,20);
  root.userData.editorSkin=true;view.apply(root,obj);assert.ok(Math.abs(root.scale.x-1000)<1e-9);
  view.motionMode=false;view.apply(root,obj);assert.ok(Math.abs(root.scale.x-1000)<1e-9,'old rig retains raw GLB conversion while static proxy loads');
});

test('scene rigs stay loaded across edit and motion mode switches and placement edits', async () => {
  const loaded=[];const view=loadingView(async obj=>{loaded.push(obj.asset);return new ArrayBuffer(1);});
  const obj={id:'person',asset:'proxy',scene:{asset:'raw'},motion:{kind:'skin',asset:'raw'},visible:true};
  await view.update({objects:[obj]});await view.assetQueue;
  view.motionMode=true;await view.update({objects:[obj]});await view.assetQueue;
  view.motionMode=false;await view.update({objects:[{...obj,transform:[]} ]});await view.assetQueue;
  assert.deepEqual(loaded,['raw']);assert.equal(view.entries.get('person').root.userData.editorSkin,true);
});
