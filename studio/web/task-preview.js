import { ViewportFrame } from "./viewport-frame.js";
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createGLTFLoader } from './gltf-loader.js';
import { RenderLoop, resizeDrawingBuffer } from './render-loop.js';
import { t } from './i18n.js';

export class TaskPreview {
  constructor(element, { insets } = {}) {
    this.element = element; this.scene = new THREE.Scene(); this.playing = false;
    this.camera = new THREE.PerspectiveCamera(42, 1, .001, 10000);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    element.append(this.renderer.domElement);
    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.enableDamping = true;
    this.orbit.addEventListener("start", () => { this.userMoved = true; });
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x33445c, 2.5));
    for (const position of [[2, 3, 4], [-2, 1, -3]]) {
      const light = new THREE.DirectionalLight(0xffffff, 2); light.position.set(...position); this.scene.add(light);
    }
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((url) => {
      if (!url.startsWith('blob:') && !url.startsWith('data:')) throw new Error(t('taskPreview.error.modelMissingTextures'));
      return url;
    });
    this.loader = createGLTFLoader(this.renderer, manager);
    this.loop = new RenderLoop(({ resize, resizing }) => {
      if (resize) { resizeDrawingBuffer(this.renderer, this.camera, element, resizing); this.frame?.apply(); }
      const now = performance.now();
      if (this.playing && this.mixer) this.mixer.update(Math.min((now - (this.last || now)) / 1000, .1));
      this.last = now;
      this.orbit.update(); this.renderer.render(this.scene, this.camera);
      if (this.playing) this.onTime?.(this.action?.time || 0);
      return this.playing;
    });
    this.frame = new ViewportFrame(element, this.camera, () => { if (!this.userMoved) this.fit(); this.loop.invalidate(); }, insets);
    this.orbit.addEventListener('change', () => this.loop.invalidate());
    this.observer = new ResizeObserver(() => this.loop.resize()); this.observer.observe(element);
    this.loop.resize();
  }
  clear() {
    this.mixer?.stopAllAction();
    if (this.root) {
      this.mixer?.uncacheRoot(this.root); this.scene.remove(this.root);
      this.release(this.root);
    }
    this.root = null; this.mixer = null; this.action = null; this.clips = []; this.playing = false;
  }
  release(root) {
      root.traverse((obj) => {
        obj.geometry?.dispose();
        for (const material of (Array.isArray(obj.material) ? obj.material : [obj.material])) if (material) {
          Object.values(material).forEach((value) => { if (value?.isTexture) value.dispose(); }); material.dispose();
        }
      });
  }
  async load(bytes, options = {}) {
    const version = this.version = (this.version || 0) + 1;
    const gltf = await this.loader.parseAsync(bytes, '');
    if (this.disposed || version !== this.version || options.isCurrent?.() === false) { this.release(gltf.scene); return; }
    this.clear(); this.root = gltf.scene; this.scene.add(this.root);
    if (!options.preserveCamera) this.fit();
    if (gltf.animations.length) {
      this.mixer = new THREE.AnimationMixer(this.root);
      this.clips = gltf.animations;
      this.selectClip(0);
    }
    this.loop.invalidate();
    return gltf.animations.map((clip, index) => ({ index, name: clip.name || t('taskPreview.clipNameFallback', { n: index + 1 }), duration: clip.duration }));
  }
  fit() {
    this.userMoved = false;
    if (!this.root) return;
    const box = new THREE.Box3().setFromObject(this.root), center = box.getCenter(new THREE.Vector3());
    const size = this.reference?.diameter_m || Math.max(box.getSize(new THREE.Vector3()).length(), .001);
    if (this.reference?.center_m) center.fromArray(this.reference.center_m);
    this.camera.position.copy(center).add(new THREE.Vector3(.8, .6, 1).normalize().multiplyScalar(this.frame?.distance(size / 2) || size * 1.7));
    this.camera.near = size / 10000; this.camera.far = size * 100;
    this.camera.updateProjectionMatrix(); this.orbit.target.copy(center); this.orbit.update();
    this.loop.invalidate();
  }
  snapshot() {
    resizeDrawingBuffer(this.renderer, this.camera, this.element, false);
    this.fit(); this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/webp', .75);
  }
  selectClip(index) { this.mixer?.stopAllAction(); this.action = null; if (this.clips?.[index]) this.action = this.mixer.clipAction(this.clips[index]).reset().play(); this.mixer?.update(0); this.onTime?.(0); this.loop.invalidate(); }
  play(value) { this.playing = value && !!this.mixer; this.last = performance.now(); this.loop.invalidate(); }
  setSpeed(value) { if (this.mixer && Number.isFinite(value) && value > 0 && value <= 4) this.mixer.timeScale = value; }
  seek(seconds) { if (this.mixer) { const speed = this.mixer.timeScale; this.mixer.timeScale = 1; this.mixer.setTime(seconds); this.mixer.timeScale = speed; } this.loop.invalidate(); }
  setActive(value) { this.last = performance.now(); this.loop.setActive(value); }
  dispose() { this.disposed = true; this.clear(); this.loader.disposeCodecs(); this.observer.disconnect(); this.frame.dispose(); this.loop.dispose(); this.orbit.dispose(); this.renderer.dispose(); this.renderer.domElement.remove(); }
}
