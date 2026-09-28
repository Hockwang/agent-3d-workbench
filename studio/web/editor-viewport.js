import { toStudio, toGltf } from './motion-engine.js';
import { ViewportFrame } from "./viewport-frame.js";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { createGLTFLoader } from './gltf-loader.js';
import { RenderLoop, resizeDrawingBuffer } from "./render-loop.js";
import { t } from './i18n.js';

export class EditorViewport {
  constructor(element, { loadAsset, onSelect, onTransform, onError, onRegion, onContext }) {
    this.element = element; this.loadAsset = loadAsset;
    this.onSelect = onSelect; this.onTransform = onTransform; this.onError = onError;
    this.entries = new Map(); this.helpers = []; this.active = true; this.disposed = false;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, .01, 1000000);
    this.camera.up.set(0, 0, 1); this.camera.position.set(70, -90, 65);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    element.appendChild(this.renderer.domElement);
    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.enableDamping = true;
    this.orbit.addEventListener("start", () => { this.userMoved = true; });
    this.orbit.addEventListener("change", () => this.loop?.invalidate());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x313747, 2.5));
    for (const [position, intensity] of [[[1, -2, 3], 3], [[-2, 1, 1], 1.5]]) {
      const light = new THREE.DirectionalLight(0xffffff, intensity);
      light.position.set(...position); this.scene.add(light);
    }
    this.grid = new THREE.GridHelper(200, 20, 0x444448, 0x2a2a2e);
    this.grid.rotation.x = Math.PI / 2; this.scene.add(this.grid);
    this.transform = new TransformControls(this.camera, this.renderer.domElement);
    this.transform.setSpace("world"); this.transform.setSize(.85);
    this.scene.add(this.transform.getHelper());
    this.pivot = new THREE.Object3D(); this.scene.add(this.pivot);
    this.transform.addEventListener("dragging-changed", (e) => {
      this.dragging = e.value; this.orbit.enabled = !e.value;
      if (e.value) this.beginTransform(); else this.endTransform();
    });
    this.transform.addEventListener("change", () => this.loop?.invalidate());
    this.transform.addEventListener("objectChange", () => this.changeTransform());
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((url) => {
      if (!url.startsWith("blob:") && !url.startsWith("data:")) throw new Error(t('editor.error.previewRestrictedAssets'));
      return url;
    });
    this.loader = createGLTFLoader(this.renderer, manager);
    this.raycaster = new THREE.Raycaster();
    this.pointerDown = (event) => { this.start = [event.clientX, event.clientY]; if(this.city)this.renderer.domElement.focus(); };
    this.click = (event) => {
      if (this.transform.axis || this.dragging || !this.start || Math.hypot(event.clientX - this.start[0], event.clientY - this.start[1]) > 4) return;
      const rect = this.renderer.domElement.getBoundingClientRect();
      this.raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
        -(event.clientY - rect.top) / rect.height * 2 + 1), this.camera);
      if(this.city?.running)return;
      const roots = [...this.entries.values()].filter((x) => x.root?.visible).map((x) => x.root);
      const hit = this.raycaster.intersectObjects(roots, true)[0];
      let object = hit?.object;
      while (object && !object.userData.editorId) object = object.parent;
      if(!object&&this.city){const id=this.city.pick(this.raycaster);if(id){this.onCityPick?.(id);return;}}
      if (this.regionPicking && hit && object) { onRegion?.(object.userData.editorId, hit.point.toArray()); return; }
      this.onSelect(object?.userData.editorId || null, event.shiftKey || event.metaKey || event.ctrlKey);
    };
    element.addEventListener("pointerdown", this.pointerDown);
    element.addEventListener("click", this.click);
    this.contextMenu = (event) => {
      if (this.dragging) return;
      const rect = this.renderer.domElement.getBoundingClientRect();
      this.raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
        -(event.clientY - rect.top) / rect.height * 2 + 1), this.camera);
      const roots = [...this.entries.values()].filter(x => x.root?.visible).map(x => x.root);
      let object = this.raycaster.intersectObjects(roots, true)[0]?.object;
      while (object && !object.userData.editorId) object = object.parent;
      if (object) { event.preventDefault(); onContext?.(object.userData.editorId, event); }
    };
    element.addEventListener('contextmenu', this.contextMenu);
    this.loop = new RenderLoop(({ resize, resizing }) => {
      if (resize) { resizeDrawingBuffer(this.renderer, this.camera, element, resizing); if(!this.city)this.frame?.apply(); }
      if(this.city){const playing=this.city.frame();if(!playing)this.orbit.update();this.city.setEditing?.(this.state?.objects||[]);for(const obj of this.state?.objects||[]){const e=this.entries.get(obj.id);if(e?.root)e.root.visible=!playing&&!!obj.city_link&&obj.visible;}this.helpers.forEach(h=>h.visible=!playing);this.renderer.render(this.scene,this.camera);return playing;}
      const playing = this.motionPlayer?.tick();
      this.orbit.update(); this.renderer.render(this.scene, this.camera);
      return playing;
    });
    this.frame = new ViewportFrame(element, this.camera, () => { if (!this.userMoved&&!this.city) this.fit(); this.loop.invalidate(); });
    this.resize = () => this.loop.resize();
    this.observer = new ResizeObserver(this.resize); this.observer.observe(element);
    window.addEventListener("resize", this.resize);
    this.resize();
  }
  setActive(active) {
    if (this.active === active) return;
    this.active = active;
    this.loop.setActive(active);
  }
  setMotionMode(value) {
    if (this.motionMode === value) return;
    this.motionMode = value; this.setMode("select");
    if (this.state) this.update(this.state);
  }
  setMode(mode) {
    this.mode = mode;
    if (mode !== "select") this.transform.setMode(mode);
    this.selection();
    this.loop?.invalidate();
  }
  async update(state) {
    this.state = state;
    if (this.dragging || this.disposed) return;
    const ids = new Set(state.objects.map((o) => o.id));
    for (const [id, entry] of this.entries) {
      if (!ids.has(id)) { this.remove(entry); this.entries.delete(id); }
    }
    const stamp = state.objects.map((o) => o.id).join();
    const fit = this.objectStamp !== stamp;
    this.objectStamp = stamp;
    for (const obj of state.objects) {
      if(obj.city)continue;
      const skin = Boolean(obj.scene || ['skin','gltf'].includes(obj.motion?.kind));
      const asset = obj.scene?.asset || (skin ? obj.motion.asset : obj.asset);
      let entry = this.entries.get(obj.id);
      // Hidden history remains editable without consuming preview requests.
      if (obj.visible === false) {
        if (entry?.root) this.apply(entry.root, obj);
        continue;
      }
      if (!entry || entry.asset !== asset) {
        // Retain the previous mesh while its replacement downloads/parses.
        entry = { asset, skin, root: entry?.root, loading: true }; this.entries.set(obj.id, entry);
        // MCP hosts have bounded request queues. Include parsing in the queue
        // so large scenes do not also accumulate decoded GLBs in memory.
        this.assetQueue = (this.assetQueue || Promise.resolve()).then(async () => {
          if (this.disposed || this.entries.get(obj.id) !== entry) return;
          // A queued part may become hidden before its turn. Reset the asset
          // marker so showing it later schedules a fresh load.
          if (this.state.objects.find(o => o.id === obj.id)?.visible === false) {
            entry.asset = ''; entry.loading = false; return;
          }
          const gltf = await this.loader.parseAsync(await this.loadAsset({...obj,asset,asset_url:`/api/editor-asset/${asset}.glb`}), "");
          if (this.disposed || this.entries.get(obj.id) !== entry) { this.release(gltf.scene); return; }
          this.remove(entry);
          entry.gltf = gltf; entry.root = skin ? new THREE.Group() : gltf.scene; if (skin) entry.root.add(gltf.scene); entry.loading = false; entry.root.userData.editorId = obj.id; entry.root.userData.editorSkin = Boolean(skin);
          this.scene.add(entry.root);
          const current = this.state.objects.find((o) => o.id === obj.id);
          if (current) this.apply(entry.root, current);
          if(!this.city)this.motionPlayer?.draw(); this.selection(); if (fit&&!this.city) this.fit();
          this.loop.invalidate();
        }).catch((error) => { if (!this.disposed && this.entries.get(obj.id) === entry) { entry.failed = true; this.onError(error); } });
      }
      if (entry.root) this.apply(entry.root, obj);
    }
    if(!this.city)this.motionPlayer?.draw(); this.selection();
    this.loop.invalidate();
  }
  retryFailed() {
    for (const entry of this.entries.values()) if (entry.failed) entry.asset = '';
    if (this.state) this.update(this.state);
  }
  apply(root, obj) {
    root.matrixAutoUpdate = false;
    root.matrix.set(...obj.transform.flat());
    if (root.userData.editorSkin) root.matrix.multiply(toStudio);
    if(this.city)root.matrix.premultiply(toGltf);
    root.matrix.decompose(root.position, root.quaternion, root.scale);
    root.visible = obj.visible && (!this.city || (!this.city.running && !!obj.city_link)); root.updateMatrixWorld(true);
  }
  selection() {
    if (this.dragging) return;
    this.transform.detach();
    this.transformRoot = null;
    for (const helper of this.helpers) { this.scene.remove(helper); helper.dispose(); }
    this.helpers = [];
    for (const id of this.state?.selection || []) {
      const entry = this.entries.get(id), root = entry?.root;
      if (!root?.visible) continue;
      const helper = new THREE.BoxHelper(root, 0x79b7ff);
      this.scene.add(helper); this.helpers.push(helper);
      if (this.showSkeleton && entry.gltf) {
        const skeleton = new THREE.SkeletonHelper(entry.gltf.scene);
        skeleton.material.depthTest = false; skeleton.renderOrder = 10;
        this.scene.add(skeleton); this.helpers.push(skeleton);
      }
      const rotation = new THREE.Matrix4().extractRotation(root.matrix);
      const x = new THREE.Vector3().setFromMatrixColumn(rotation, 0), y = new THREE.Vector3().setFromMatrixColumn(rotation, 1), z = new THREE.Vector3().setFromMatrixColumn(rotation, 2);
      const hasShear = Math.max(Math.abs(x.dot(y)), Math.abs(y.dot(z)), Math.abs(z.dot(x))) > 1e-6;
      if (this.state.selection.length === 1 && this.mode && this.mode !== "select" && !hasShear && !entry.loading && !entry.failed) {
        // Imported vertices can already be in assembly coordinates while the
        // GLB root remains at zero. Move a proxy, never recenter the actual mesh.
        this.transformRoot = root;
        new THREE.Box3().setFromObject(root).getCenter(this.pivot.position);
        this.pivot.quaternion.identity(); this.pivot.scale.setScalar(1);
        this.pivot.updateMatrixWorld(true); this.transform.attach(this.pivot);
      }
    }
  }
  setSkeleton(value) { this.showSkeleton = value; this.selection(); this.loop?.invalidate(); }
  mountCity(runtime) {
    this.original={scene:this.scene,camera:this.camera,target:this.orbit.target.clone()};
    this.city=runtime;this.scene=runtime.scene;this.camera=runtime.camera;
    this.replaceOrbit(runtime.target);this.transform.camera=this.camera;
    this.renderer.userData={...this.renderer.userData,viewportSize:null};
    this.scene.add(this.transform.getHelper(),this.pivot);
    for(const e of this.entries.values())if(e.root)this.scene.add(e.root);
    this.update(this.state);this.loop.setActive(true);this.loop.resize();
  }
  unmountCity() {
    if(!this.city)return;
    const old=this.original;this.city=null;this.scene=old.scene;this.camera=old.camera;
    this.replaceOrbit(old.target);this.transform.camera=this.camera;
    this.scene.add(this.transform.getHelper(),this.pivot);for(const e of this.entries.values())if(e.root)this.scene.add(e.root);
    this.renderer.userData={...this.renderer.userData,viewportSize:null};
    this.update(this.state);this.loop.resize();
  }
  replaceOrbit(target) {
    // OrbitControls freezes the camera's up axis at construction.
    this.orbit.dispose();this.orbit=new OrbitControls(this.camera,this.renderer.domElement);
    this.orbit.enableDamping=true;if(target)this.orbit.target.copy(target);
    this.orbit.addEventListener('start',()=>{this.userMoved=true;});
    this.orbit.addEventListener('change',()=>this.loop.invalidate());this.orbit.update();
  }
  beginTransform() {
    if (this.motionPlayer?.playing) this.motionPlayer.play();
    if (!this.transformRoot) return;
    this.transformRoot.updateWorldMatrix(true, false); this.pivot.updateWorldMatrix(true, false);
    this.dragStart = { root: this.transformRoot, matrix: this.transformRoot.matrixWorld.clone(),
      pivotInverse: this.pivot.matrixWorld.clone().invert(), revision: this.state?.revision,
      versions: Object.fromEntries((this.state?.objects || []).map(o => [o.id, o.version])) };
  }
  changeTransform() {
    if (!this.dragStart) return;
    const { root, matrix, pivotInverse } = this.dragStart;
    this.pivot.updateWorldMatrix(true, false); root.parent?.updateWorldMatrix(true, false);
    root.matrix.copy(root.parent?.matrixWorld || new THREE.Matrix4()).invert()
      .multiply(this.pivot.matrixWorld).multiply(pivotInverse).multiply(matrix);
    root.matrixAutoUpdate = false;
    root.matrix.decompose(root.position, root.quaternion, root.scale); root.updateMatrixWorld(true);
    this.helpers.forEach(h => h.update?.()); this.loop?.invalidate();
  }
  endTransform() {
    if (!this.dragStart) return;
    this.changeTransform();
    const { root, revision, versions } = this.dragStart; this.dragStart = null;
    const changed=root.userData.editorSkin ? root.matrix.clone().multiply(toGltf) : root.matrix.clone();
    if(this.city)changed.premultiply(toStudio);
    const v = changed.elements;
    this.onTransform(root.userData.editorId, Array.from({ length: 4 }, (_, row) =>
      Array.from({ length: 4 }, (_, col) => v[col * 4 + row])), revision, versions);
  }
  fit(ids = this.city ? this.state?.selection : null) {
    this.userMoved = false;
    const box = new THREE.Box3();
    for (const [id,entry] of this.entries) if (entry.root?.visible && (!ids?.length || ids.includes(id))) box.expandByObject(entry.root);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const extent = Math.max(box.getSize(new THREE.Vector3()).length(), 1);
    this.orbit.target.copy(center);
    this.camera.position.copy(center).add((this.city?new THREE.Vector3(.7,.7,-1):new THREE.Vector3(.7,-1,.7)).normalize().multiplyScalar(this.frame?.distance(extent / 2) || extent * 1.7));
    // City cameras use metres and retain kilometres of scenery. Applying the
    // millimetre editor's part-sized near plane makes roads fight the ground
    // after focusing a person. The city runtime owns its clipping range.
    if (!this.city) {
      this.camera.near = Math.max(extent / 10000, .001);
      this.camera.far = Math.max(extent * 100, 1000);
    }
    this.camera.updateProjectionMatrix(); this.orbit.update();
    this.grid.scale.setScalar(Math.max(extent / 100, .01));
    this.grid.position.set(center.x, center.y, box.min.z - extent * .002);
    this.loop.invalidate();
  }
  setPlane(point, normal, size) {
    if (this.plane) { this.scene.remove(this.plane); this.plane.geometry.dispose(); this.plane.material.dispose(); this.plane = null; }
    this.loop?.invalidate();
    if (!point || this.city) return;
    this.plane = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({
      color: 0x77adff, transparent: true, opacity: .22, side: THREE.DoubleSide, depthWrite: false,
    }));
    this.plane.position.set(...point);
    this.plane.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...normal).normalize());
    this.scene.add(this.plane);
  }
  setRegion(point, radius) {
    if (this.region) { this.scene.remove(this.region); this.region.geometry.dispose(); this.region.material.dispose(); this.region = null; }
    if (point) {
      this.region = new THREE.Mesh(new THREE.SphereGeometry(radius, 24, 16), new THREE.MeshBasicMaterial({ color: 0x71c3ed, transparent: true, opacity: .25, depthWrite: false }));
      this.region.position.set(...point); this.scene.add(this.region);
    }
    this.loop?.invalidate();
  }
  release(root) {
    root.traverse((o) => {
      o.geometry?.dispose(); o.skeleton?.dispose();
      for (const mat of (Array.isArray(o.material) ? o.material : [o.material]).filter(Boolean)) {
        for (const value of Object.values(mat)) if (value?.isTexture) value.dispose();
        mat.dispose();
      }
    });
  }
  remove(entry) { if (entry.root) { this.scene.remove(entry.root); this.release(entry.root); } }
  dispose() {
    this.loader.disposeCodecs();
    this.disposed = true; this.loop.dispose(); this.observer.disconnect(); this.frame.dispose();
    window.removeEventListener("resize", this.resize);
    this.element.removeEventListener("pointerdown", this.pointerDown); this.element.removeEventListener("click", this.click);
    this.element.removeEventListener('contextmenu', this.contextMenu);
    this.transform.dispose(); this.orbit.dispose(); this.setPlane(null); this.setRegion(null);
    this.helpers.forEach((h) => h.dispose()); this.entries.forEach((e) => this.remove(e));
    this.grid.geometry.dispose(); this.grid.material.dispose(); this.renderer.dispose();
  }
}
