import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { printPoseFiles } from '../studio/web/print-pose.js';

function triangle() {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute([0,0,0, .02,0,0, 0,.03,0], 3));
  return g;
}
const positions = file => Array.from(new STLLoader().parse(file.bytes.buffer).attributes.position.array);

test('print pose bakes morphs and transforms in mm Z-up without changing source geometry', () => {
  const root = new THREE.Group(), geometry = triangle();
  geometry.morphAttributes.position = [new THREE.Float32BufferAttribute([0,0,.01, .02,0,.01, 0,.03,.01], 3)];
  const mesh = new THREE.Mesh(geometry); mesh.name = 'head'; mesh.position.y = .1; mesh.morphTargetInfluences[0] = 1; root.add(mesh);
  const hidden = new THREE.Mesh(triangle()); hidden.visible = false; root.add(hidden);
  const before = Array.from(geometry.attributes.position.array);
  const files = printPoseFiles(root), actual = positions(files[0]);
  assert.equal(files.length, 1); assert.equal(files[0].name, '01-head.stl');
  [0,-10,100, 20,-10,100, 0,-10,130].forEach((value,i) => assert.ok(Math.abs(actual[i]-value)<.001));
  assert.deepEqual(Array.from(geometry.attributes.position.array), before);
  assert.equal(mesh.morphTargetInfluences[0], 1);
});

test('print pose freezes the displayed bone transform and preserves separate mesh parts', () => {
  const root = new THREE.Group(), geometry = triangle();
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Array(12).fill(0), 4));
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1,0,0,0,1,0,0,0,1,0,0,0], 4));
  const mesh = new THREE.SkinnedMesh(geometry), bone = new THREE.Bone(); mesh.add(bone); root.add(mesh);
  mesh.bind(new THREE.Skeleton([bone])); bone.position.y = .04;
  root.add(new THREE.Mesh(triangle()));
  const files = printPoseFiles(root);
  assert.equal(files.length, 2);
  assert.ok(Math.abs(positions(files[0])[2] - 40) < .001);
  assert.equal(positions(files[1])[2], 0);
  assert.equal(bone.position.y, .04);
});
