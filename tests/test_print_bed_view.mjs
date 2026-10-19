import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { Viewport } from '../studio/web/viewport.js';

const printer = { bed_mm: [256, 256, 250], bed_origin_mm: [0, 0], margin_mm: 5, exclude_areas: [] };
function viewport(parts) {
  const view = Object.create(Viewport.prototype);
  Object.assign(view, { viewMode: 'assembly', plateIndex: 0, bedGroup: new THREE.Group(), partsGroup: new THREE.Group(), _meshes: new Map() });
  for (const [name, size, center] of parts) {
    const geometry = new THREE.BoxGeometry(...size);
    geometry.translate(...center); geometry.computeBoundingBox();
    const mesh = new THREE.Mesh(geometry); mesh.matrixAutoUpdate = false;
    view._meshes.set(name, { mesh }); view.partsGroup.add(mesh);
  }
  view._lastState = { printer, parts: parts.map(([name]) => ({ name })), plates: [] };
  view._syncBed(printer); view._applyTransforms(view._lastState);
  return view;
}
const close = (actual, expected) => actual.forEach((value, i) => assert.ok(Math.abs(value - expected[i]) < 1e-6, `${actual} != ${expected}`));

test('unarranged assembly sits on the real bed without shrinking or changing part spacing', () => {
  const view = viewport([['body', [400, 600, 1000], [400, -200, 800]], ['tip', [20, 20, 64], [400, -200, 1332]]]);
  assert.equal(view.bedGroup.visible, true);
  const box = new THREE.Box3().setFromObject(view.partsGroup);
  close(box.getCenter(new THREE.Vector3()).toArray().slice(0, 2), [128, 128]);
  assert.equal(box.min.z, 0);
  close(box.getSize(new THREE.Vector3()).toArray(), [400, 600, 1064]);
  assert.ok(box.min.x < 0 && box.max.x > 256, 'oversized geometry remains visibly outside the bed');
  for (const [name, entry] of view._meshes) {
    assert.equal(entry.mesh.matrix.equals(new THREE.Matrix4()), true, name);
  }
  close(view._meshes.get('body').mesh.geometry.boundingBox.getCenter(new THREE.Vector3()).toArray(), [400, -200, 800]);
});

test('arranged placement keeps its exact matrix; switching back restores the assembly bed reference', () => {
  const view = viewport([['part', [20, 40, 60], [-80, -50, 130]], ['other', [10, 10, 10], [50, 50, 50]]]);
  const T = [[1, 0, 0, 110], [0, 1, 0, 100], [0, 0, 1, -100], [0, 0, 0, 1]];
  view._lastState.plates = [{ placements: [{ part: 'part', T }] }];
  view.setView('plate');
  close(view.partsGroup.position.toArray(), [0, 0, 0]);
  close(new THREE.Box3().setFromObject(view._meshes.get('part').mesh).min.toArray(), [20, 30, 0]);
  assert.equal(view._meshes.get('other').mesh.visible, false);
  view.setView('assembly');
  assert.equal(view.bedGroup.visible, true);
  assert.equal(view._meshes.get('other').mesh.visible, true);
  assert.equal(new THREE.Box3().setFromObject(view.partsGroup).min.z, 0);
});

test('bed changes honor nonzero machine origin and clear an unavailable printer', () => {
  const view = viewport([['part', [10, 20, 30], [0, 0, 0]]]);
  const other = { ...printer, bed_mm: [400, 300, 500], bed_origin_mm: [-200, -150] };
  view._lastState.printer = other; view._syncBed(other); view._applyTransforms(view._lastState);
  close(new THREE.Box3().setFromObject(view.partsGroup).getCenter(new THREE.Vector3()).toArray(), [0, 0, 15]);
  view._syncBed({ bed_mm: null });
  assert.equal(view.bedGroup.visible, false);
  view._syncBed(printer);
  assert.equal(view.bedGroup.visible, true);
});
