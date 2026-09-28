// Apply v0.4's camera insets while the canvas still fills the entire stage.
// Pointer picking continues to use that same canvas and projection matrix.
export class ViewportFrame {
  constructor(element, camera, changed, { top = 0, bottom = 64 } = {}) {
    this.element = element; this.camera = camera; this.changed = changed;
    this.verticalInsets = { top, bottom };
    this.stage = element.closest('.v04-stage') || element;
    this.observer = new ResizeObserver(() => this.update());
    this.observer.observe(element);
    for (const card of this.stage.querySelectorAll('.float-card')) this.observer.observe(card);
    this.update();
  }
  update() {
    const rect = this.element.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    let left = 0, right = 0;
    for (const card of this.stage.querySelectorAll('.float-card:not(.collapsed)')) {
      const r = card.getBoundingClientRect();
      if (r.height < 80 || r.width > rect.width * .8) continue;
      if (card.classList.contains('v04-library')) left = Math.max(left, r.right - rect.left + 12);
      else right = Math.max(right, rect.right - r.left + 12);
    }
    const key = [rect.width, rect.height, left, right].join('|');
    this.insets = { left, right, ...this.verticalInsets };
    this.apply();
    if (key !== this.key) { this.key = key; this.changed?.(); }
  }
  apply() {
    const { width, height } = this.element.getBoundingClientRect();
    if (!width || !height) return;
    const { left = 0, right = 0, top = 0, bottom = 64 } = this.insets || {};
    const dx = Math.max(-width / 4, Math.min(width / 4, (right - left) / 2));
    this.camera.setViewOffset(width, height, dx, Math.max(-height / 4, Math.min(height / 4, (bottom - top) / 2)), width, height);
  }
  distance(radius) {
    const { width, height } = this.element.getBoundingClientRect();
    const { left = 0, right = 0, top = 0, bottom = 64 } = this.insets || {};
    const w = Math.max(width - left - right, width * .35, 1);
    const h = Math.max(height - top - bottom, height * .35, 1);
    const half = Math.atan(Math.tan(this.camera.fov * Math.PI / 360) * Math.min(w, h) / Math.max(height, 1));
    return radius / Math.sin(Math.max(half, .05)) * 1.04;
  }
  dispose() { this.observer.disconnect(); }
}
