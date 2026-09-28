import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { TaskPreview } from '../studio/web/task-preview.js';

function previewFixture(parseAsync) {
  const preview = Object.create(TaskPreview.prototype);
  preview.root = new THREE.Group();
  preview.scene = new THREE.Scene(); preview.scene.add(preview.root);
  preview.loader = { parseAsync }; preview.loop = { invalidate() {} }; preview.fit = () => {};
  preview.released = []; preview.release = root => preview.released.push(root);
  return preview;
}

test('a failed replacement preserves the last visible model', async () => {
  const preview = previewFixture(async () => { throw new Error('invalid GLB'); });
  const original = preview.root;
  await assert.rejects(preview.load(new ArrayBuffer(1)), /invalid GLB/);
  assert.equal(preview.root, original);
  assert.ok(preview.scene.children.includes(original));
  assert.deepEqual(preview.released, []);
});

test('late loads cannot replace a newer result or a different selected artifact', async () => {
  const pending = [];
  const preview = previewFixture(() => new Promise(resolve => pending.push(resolve)));
  const old = preview.root, first = new THREE.Group(), second = new THREE.Group();
  const loadA = preview.load(new ArrayBuffer(1));
  const loadB = preview.load(new ArrayBuffer(2));
  pending[1]({ scene: second, animations: [] }); await loadB;
  pending[0]({ scene: first, animations: [] }); await loadA;
  assert.equal(preview.root, second);
  assert.deepEqual(preview.released, [old, first]);
  const loadC = preview.load(new ArrayBuffer(3), { isCurrent: () => false });
  const stale = new THREE.Group(); pending[2]({ scene: stale, animations: [] }); await loadC;
  assert.equal(preview.root, second);
});

test('animation speed changes playback without changing the meaning of seek seconds', () => {
  const root = new THREE.Object3D();
  const mixer = new THREE.AnimationMixer(root);
  mixer.clipAction(new THREE.AnimationClip('move', 10, [
    new THREE.NumberKeyframeTrack('.position[x]', [0, 10], [0, 10]),
  ])).play();
  const preview = { mixer, loop: { invalidate() {} } };
  TaskPreview.prototype.setSpeed.call(preview, 2);
  mixer.update(1);
  assert.equal(root.position.x, 2);
  TaskPreview.prototype.seek.call(preview, 3);
  assert.equal(root.position.x, 3);
  assert.equal(mixer.timeScale, 2);
  TaskPreview.prototype.setSpeed.call(preview, -1);
  assert.equal(mixer.timeScale, 2);
});
