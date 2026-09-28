import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { EditorViewport } from '../studio/web/editor-viewport.js';
import { toStudio } from '../studio/web/motion-engine.js';

const close = (a, b) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 1e-8, `${a} != ${b}`));
function fixture() {
  const view = Object.create(EditorViewport.prototype);
  view.scene = new THREE.Scene(); view.helpers = []; view.pivot = new THREE.Object3D(); view.scene.add(view.pivot);
  const root = new THREE.Group(); root.userData.editorId = 'part'; root.matrixAutoUpdate = false;
  root.add(new THREE.Mesh(new THREE.BoxGeometry(4, 6, 8).translate(20, 30, 40), new THREE.MeshBasicMaterial()));
  view.scene.add(root); view.entries = new Map([['part', { root }]]);
  view.state = { revision: 5, selection: ['part'] }; view.mode = 'translate';
  view.transform = { detach() { this.object = null; }, attach(obj) { this.object = obj; } };
  view.orbit = { enabled: true }; view.loop = { invalidate() {} };
  view.onTransform = (...args) => { view.submitted = args; };
  return { view, root };
}

test('gizmo follows offset geometry center without moving the model', () => {
  const { view, root } = fixture(); const before = root.matrix.clone(); view.selection();
  close(view.transform.object.getWorldPosition(new THREE.Vector3()).toArray(), [20, 30, 40]);
  close(root.matrix.elements, before.elements); assert.equal(root.matrixAutoUpdate, false);
});
for (const mode of ['translate', 'rotate', 'scale']) test(`${mode} transforms about part center and submits original root coordinates`, () => {
  const { view, root } = fixture();
  root.matrix.makeTranslation(7, -3, 2); root.updateMatrixWorld(true); view.selection(); view.beginTransform();
  if (mode === 'translate') view.pivot.position.x += 9;
  if (mode === 'rotate') view.pivot.rotation.z = Math.PI / 2;
  if (mode === 'scale') view.pivot.scale.set(2, 3, 4);
  view.changeTransform(); view.endTransform();
  close(new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3()).toArray(), mode === 'translate' ? [36, 27, 42] : [27, 27, 42]);
  assert.equal(view.submitted[0], 'part'); assert.equal(view.submitted[2], 5);
  close(new THREE.Matrix4().set(...view.submitted[1].flat()).elements, root.matrix.elements);
});
test('successive drags rebase at the current part center', () => {
  const { view, root } = fixture(); view.selection();
  for (let n = 0; n < 2; n++) { view.beginTransform(); view.pivot.position.y += 10; view.changeTransform(); view.endTransform(); }
  close(new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3()).toArray(), [20, 50, 40]);
});

test('replacement still loading cannot transform the stale preview', () => {
  const {view} = fixture(); view.entries.get('part').loading = true; view.selection();
  assert.equal(view.transform.object, null);
});

test('world delta respects transformed parent coordinates', () => {
  const {view, root} = fixture(); const parent = new THREE.Group(); parent.rotation.z = Math.PI / 3;
  parent.position.set(5, 7, 9); view.scene.add(parent); parent.add(root); parent.updateMatrixWorld(true);
  const center = new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3());
  view.selection(); view.beginTransform(); view.pivot.position.z += 13; view.changeTransform(); view.endTransform();
  close(new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3()).toArray(), center.add(new THREE.Vector3(0,0,13)).toArray());
});

test('raw GLB gizmo submits workspace placement without baking unit conversion twice', () => {
  const {view, root}=fixture();root.userData.editorSkin=true;
  root.matrix.makeTranslation(300,0,0).multiply(toStudio);root.updateMatrixWorld(true);
  view.selection();view.beginTransform();view.pivot.position.x+=200;view.endTransform();
  const submitted=new THREE.Matrix4().set(...view.submitted[1].flat());
  close(submitted.elements,new THREE.Matrix4().makeTranslation(500,0,0).elements);
});

test('city world gizmo converts metre Y-up translation back to millimetre Z-up',()=>{
  const {view,root}=fixture();view.city={};root.userData.editorSkin=true;
  root.matrix.makeTranslation(4,0,0);root.updateMatrixWorld(true);
  view.selection();view.beginTransform();view.pivot.position.y+=2;view.endTransform();
  const submitted=new THREE.Matrix4().set(...view.submitted[1].flat());
  close(submitted.elements,new THREE.Matrix4().makeTranslation(4000,0,2000).elements);
});

test('focusing a city part preserves the city depth range for subsequent orbiting', () => {
  const {view,root}=fixture();
  view.city={};view.camera=new THREE.PerspectiveCamera(60,1,.35,15000);
  view.orbit={target:new THREE.Vector3(),update(){}};
  view.grid=new THREE.Object3D();
  const center=new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3());
  for(let i=0;i<3;i++){
    view.fit(['part']);
    assert.equal(view.camera.near,.35,'a metre-scale part must not reset the city near plane');
    assert.equal(view.camera.far,15000);
    close(view.orbit.target.toArray(),center.toArray());
    assert.ok(view.camera.position.distanceTo(center)>0);
  }
});
