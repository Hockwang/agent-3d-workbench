import assert from "node:assert/strict";
import test from "node:test";
import { RenderLoop, resizeDrawingBuffer } from "../studio/web/render-loop.js";

function harness() {
  let id = 0, now = 0;
  const frames = new Map(), timers = new Map(), draws = [];
  const clock = { raf: fn => { frames.set(++id, fn); return id; }, cancel: id => frames.delete(id),
    later: (fn, ms) => { timers.set(++id, { fn, due: now + ms }); return id; }, clear: id => timers.delete(id) };
  const loop = new RenderLoop(args => { draws.push(args); }, clock);
  const advance = ms => { now += ms; for (const [key, task] of timers) if (task.due <= now) { timers.delete(key); task.fn(); }
    const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn(now)); };
  return { loop, draws, frames, advance };
}
test("idle scenes sleep; repeated invalidations coalesce and wake again", () => {
  const h = harness();
  for (let i = 0; i < 100; i++) h.loop.invalidate();
  assert.equal(h.frames.size, 1);
  h.advance(17); assert.equal(h.draws.length, 1); assert.equal(h.frames.size, 0);
  h.advance(1000); assert.equal(h.draws.length, 1);
  h.loop.invalidate(); h.advance(17); assert.equal(h.draws.length, 2);
});
test("144 Hz window resizing reuses the last frame and draws once after settling", () => {
  const h = harness();
  h.loop.invalidate(); h.advance(17);
  h.draws.length = 0;
  for (let i = 0; i < 144; i++) { h.loop.resize(); h.advance(1000 / 144); }
  assert.equal(h.draws.length, 0);
  assert.equal(h.frames.size, 0);
  h.advance(160); assert.deepEqual(h.draws.at(-1), { resize: true, resizing: false });
  assert.equal(h.draws.length, 1);
  assert.equal(h.frames.size, 0);
});
test("pending animation or model changes cannot redraw during live window resizing", () => {
  const h = harness();
  h.loop.invalidate(); h.loop.resize();
  for (let i = 0; i < 100; i++) { h.loop.invalidate(); h.loop.resize(); h.advance(8); }
  assert.equal(h.draws.length, 0);
  assert.equal(h.frames.size, 0);
  h.advance(160); assert.equal(h.draws.length, 1);
  h.loop.invalidate(); h.advance(17); assert.equal(h.draws.length, 2);
});
test("hidden and disposed viewports never render; reopening redraws the current scene", () => {
  const h = harness(); h.loop.invalidate(); h.loop.setActive(false); h.advance(100);
  h.loop.resize(); h.advance(200); assert.equal(h.draws.length, 0);
  h.loop.setActive(true); h.advance(40); assert.equal(h.draws.length, 0);
  h.advance(160); assert.equal(h.draws.length, 1);
  h.loop.dispose(); h.loop.invalidate(); h.loop.resize(); h.advance(200);
  assert.equal(h.draws.length, 1); assert.equal(h.frames.size, 0);
});
test("drawing buffers only reallocate for a changed size or resolution", () => {
  const sizes = [], renderer = { domElement: { style: {} }, setDrawingBufferSize: (...args) => sizes.push(args) };
  const camera = { updateProjectionMatrix() {} }, element = { clientWidth: 800, clientHeight: 600 };
  const original = globalThis.devicePixelRatio; globalThis.devicePixelRatio = 2;
  try {
    resizeDrawingBuffer(renderer, camera, element, true);
    for (let i = 0; i < 100; i++) resizeDrawingBuffer(renderer, camera, element, true);
    resizeDrawingBuffer(renderer, camera, element, false);
    assert.deepEqual(sizes, [[800,600,1],[800,600,2]]);
    assert.equal(camera.aspect, 4/3);
    assert.equal(renderer.domElement.style.objectFit, 'contain');
  } finally { if (original === undefined) delete globalThis.devicePixelRatio; else globalThis.devicePixelRatio = original; }
});
