// Render on changes, then sleep. During native window resizing the compositor
// scales the last frame. Reallocate and redraw only after layout has settled:
// even a 30 Hz resize loop repeatedly reallocates WebGL/MSAA backing storage.
export class RenderLoop {
  constructor(draw, clock = {}) {
    this.draw = draw;
    this.raf = clock.raf || ((fn) => requestAnimationFrame(fn));
    this.cancel = clock.cancel || ((id) => cancelAnimationFrame(id));
    this.later = clock.later || ((fn, ms) => setTimeout(fn, ms));
    this.clear = clock.clear || ((id) => clearTimeout(id));
    this.frame = null; this.timer = null; this.active = true; this.disposed = false;
    this.dirty = false; this.sizeDirty = false; this.resizing = false; this.last = -Infinity;
  }
  invalidate() {
    if (this.disposed) return;
    this.dirty = true;
    if (this.active && !this.resizing && this.frame === null) this.frame = this.raf((time) => this.tick(time));
  }
  resize() {
    if (this.disposed) return;
    this.sizeDirty = true; this.resizing = true;
    this.cancel(this.frame); this.frame = null;
    this.clear(this.timer);
    this.timer = this.later(() => {
      this.timer = null; this.resizing = false; this.sizeDirty = true; this.invalidate();
    }, 150);
    this.invalidate();
  }
  tick(time) {
    this.frame = null;
    if (!this.active || this.resizing || this.disposed || !this.dirty) return;
    if (time - this.last < 1000 / 60) { this.invalidate(); return; }
    this.last = time; this.dirty = false;
    const resize = this.sizeDirty; this.sizeDirty = false;
    if (this.draw({ resize, resizing: this.resizing })) this.invalidate();
  }
  setActive(value) {
    if (this.active === value || this.disposed) return;
    this.active = value;
    if (value) this.resize();
    else { this.cancel(this.frame); this.frame = null; }
  }
  dispose() {
    this.disposed = true; this.cancel(this.frame); this.clear(this.timer);
    this.frame = null; this.timer = null;
  }
}

export function resizeDrawingBuffer(renderer, camera, element, resizing) {
  // Preserve the previous frame's proportions while CSS dimensions change.
  // At rest the buffer and CSS aspect ratios coincide, so no bars remain.
  if (renderer.domElement) renderer.domElement.style.objectFit = 'contain';
  const width = Math.round(element.clientWidth), height = Math.round(element.clientHeight);
  if (width < 1 || height < 1) return false;
  const ratio = Math.min(globalThis.devicePixelRatio || 1, resizing ? 1 : 2);
  const key = `${width}:${height}:${ratio}`;
  if (renderer.userData?.viewportSize === key) return false;
  renderer.userData = { ...renderer.userData, viewportSize: key };
  // CSS owns the canvas size, avoiding a layout / ResizeObserver feedback loop.
  renderer.setDrawingBufferSize(width, height, ratio);
  camera.aspect = width / height; camera.updateProjectionMatrix();
  return true;
}
