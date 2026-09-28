// viewport.js — three.js 三维视口：打印床、零件、装配/盘两种视图、悬停与点选。
// 坐标约定：Z 朝上（camera.up 与场景整体一致设为 (0,0,1)，OrbitControls 据此定轨道轴）。

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { RenderLoop, resizeDrawingBuffer } from "./render-loop.js";

const PALETTE = [
  0xe9e9ec, 0xe2584f, 0x6fa8f0, 0xf0b45a, 0x7fd68b, 0xc58bf0, 0x5ad0c8, 0xf08bb5, 0xbac45a, 0x9aa1aa,
];

// v0.4: the canvas is transparent; the backdrop (black + soft glow) is painted by style.css on #viewport-col.

const HEAVY_MESH_FACES = 1_500_000;
const HOVER_THROTTLE_MS = 80;

function rowMajorToMatrix4(T) {
  const m = new THREE.Matrix4();
  m.set(
    T[0][0], T[0][1], T[0][2], T[0][3],
    T[1][0], T[1][1], T[1][2], T[1][3],
    T[2][0], T[2][1], T[2][2], T[2][3],
    T[3][0], T[3][1], T[3][2], T[3][3]
  );
  return m;
}

export class Viewport {
  constructor(container, opts) {
    this.container = container;
    this.opts = opts || {};
    this.mock = !!this.opts.mock;
    this.viewMode = "assembly";
    this.plateIndex = 0;
    this._lastPrinterKey = null;
    this._meshes = new Map(); // name -> {mesh, url, faces, loading}
    this._colorIndex = new Map(); // name -> PALETTE 序号
    this._selectedName = null;
    this._hoveredName = null;
    this._selectHelper = null;
    this._lastHoverTs = 0;
    this._pending = 0;
    this._active = true;

    this.scene = new THREE.Scene();
    this.scene.background = null;

    const rect = container.getBoundingClientRect();
    this.camera = new THREE.PerspectiveCamera(42, Math.max(rect.width, 1) / Math.max(rect.height, 1), 1, 20000);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(400, -500, 350);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setClearColor(0x000000, 0);
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(100, 100, 30);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.addEventListener("change", () => this._loop?.invalidate());
    this.userMoved = false;
    this.controls.addEventListener("start", () => {
      this.userMoved = true;
    });

    this.bedGroup = new THREE.Group();
    this.scene.add(this.bedGroup);
    this.partsGroup = new THREE.Group();
    this.scene.add(this.partsGroup);

    const hemi = new THREE.HemisphereLight(0xffffff, 0x20232b, 1.25);
    this.scene.add(hemi);
    const dir = new THREE.DirectionalLight(0xffffff, 1.9);
    dir.position.set(200, -400, 600);
    this.scene.add(dir);
    const fill = new THREE.DirectionalLight(0xffffff, 0.55);
    fill.position.set(-300, 400, 250);
    this.scene.add(fill);

    this._raycaster = new THREE.Raycaster();
    this._pointerNdc = new THREE.Vector2();
    this._loader = new STLLoader();

    this._onResize = this._onResize.bind(this);
    this._onPointerMove = this._onPointerMove.bind(this);
    this._onClick = this._onClick.bind(this);
    window.addEventListener("resize", this._onResize);
    // The container also changes size without a window resize (plan column collapse, cards docking).
    if (typeof ResizeObserver === "function") {
      this._ro = new ResizeObserver(() => this._onResize());
      this._ro.observe(container);
    }
    this.renderer.domElement.addEventListener("pointermove", this._onPointerMove);
    this.renderer.domElement.addEventListener("click", this._onClick);

    this._loop = new RenderLoop(({ resize, resizing }) => {
      if (resize) {
        resizeDrawingBuffer(this.renderer, this.camera, this.container, resizing);
        this._applyViewOffset();
      }
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
    this._loop.resize();
  }

  dispose() {
    this._active = false;
    this._disposed = true;
    this._loop.dispose();
    window.removeEventListener("resize", this._onResize);
    if (this._ro) this._ro.disconnect();
    this.renderer.domElement.removeEventListener("pointermove", this._onPointerMove);
    this.renderer.domElement.removeEventListener("click", this._onClick);
    this.controls.dispose();
    disposeObject(this.scene);
    this._meshes.clear();
    this.renderer.dispose();
  }

  // Keep the camera and loaded meshes when the host docks/undocks the app,
  // but do not render frames while only the conversation card is visible.
  setActive(active) {
    if (this._active === active) return;
    this._active = active;
    this._loop.setActive(active);
  }

  setView(mode) {
    this.viewMode = mode;
    this._applyTransforms(this._lastState);
  }

  setPlateIndex(i) {
    this.plateIndex = i;
    this._applyTransforms(this._lastState);
  }

  onProgress(cb) {
    this._progressCb = cb;
  }

  onSelect(cb) {
    this._selectCb = cb;
  }

  onHover(cb) {
    this._hoverCb = cb;
  }

  selectPart(name) {
    this._setSelected(name, /*silent*/ true);
  }

  // 返回零件当前配色（"#rrggbb"）。网格已建则读材质真实颜色；
  // 未建则按其在 state.parts 中的序号换算 PALETTE，保证与列表圆点一致。
  // 完全未知的名字返回 null。
  getPartColor(name) {
    const entry = this._meshes.get(name);
    if (entry && entry.mesh && entry.mesh.material && entry.mesh.material.color) {
      return "#" + entry.mesh.material.color.getHexString();
    }
    if (this._colorIndex && this._colorIndex.has(name)) {
      return numToHexStr(PALETTE[this._colorIndex.get(name) % PALETTE.length]);
    }
    return null;
  }

  // --- 主入口：state 变化后调用 ---
  update(state) {
    this._lastState = state;
    this._syncBed(state.printer);
    this._syncParts(state);
    this._applyTransforms(state);
  }

  fitView() {
    const box = new THREE.Box3();
    let any = false;
    this.bedGroup.traverseVisible((o) => {
      if (o.isMesh || o.isLine) {
        any = true;
        box.expandByObject(o);
      }
    });
    this.partsGroup.traverse((o) => {
      if (o.isMesh && o.visible) {
        any = true;
        box.expandByObject(o);
      }
    });
    if (!any) return;
    const size = new THREE.Vector3();
    box.getSize(size);
    const center = new THREE.Vector3();
    box.getCenter(center);
    // 取景按「没被悬浮卡盖住的那块区域」算：包围球要同时塞进它的宽和高。
    const radius = Math.max(size.length() * 0.5, 40);
    const rect = this.container.getBoundingClientRect();
    const ins = this._insets || { left: 0, right: 0, top: 0, bottom: 0 };
    const fullH = Math.max(rect.height, 1);
    const effW = Math.max(rect.width - ins.left - ins.right, rect.width * 0.35, 1);
    const effH = Math.max(rect.height - ins.top - ins.bottom, rect.height * 0.35, 1);
    const tanV = Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2);
    const halfV = Math.atan((tanV * effH) / fullH);
    const halfH = Math.atan((tanV * effW) / fullH);
    const dist = (radius / Math.sin(Math.max(Math.min(halfV, halfH), 0.05))) * 1.02;
    const dir = new THREE.Vector3(0.55, -0.85, 0.55).normalize();
    this.camera.position.copy(center).addScaledVector(dir, dist);
    this.controls.target.copy(center);
    this.camera.near = Math.max(radius * 0.01, 0.1);
    this.camera.far = radius * 40;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.userMoved = false;
  }

  // --- 打印床 ---
  _syncBed(printer) {
    if (!printer) return;
    const key = JSON.stringify([printer.bed_mm, printer.exclude_areas, printer.margin_mm]);
    if (key === this._lastPrinterKey) return;
    this._lastPrinterKey = key;
    while (this.bedGroup.children.length) {
      const c = this.bedGroup.children.pop();
      disposeObject(c);
    }
    const [bx, by] = printer.bed_mm;
    const margin = printer.margin_mm || 0;

    const bedPlaneGeo = new THREE.PlaneGeometry(bx, by);
    const bedPlaneMat = new THREE.MeshBasicMaterial({ color: 0x17191e });
    const bedPlane = new THREE.Mesh(bedPlaneGeo, bedPlaneMat);
    bedPlane.position.set(bx / 2, by / 2, -0.06);
    bedPlane.raycast = () => {}; // 不参与拾取
    this.bedGroup.add(bedPlane);

    const grid = makeGridLines(bx, by, 10, 0x24272e);
    this.bedGroup.add(grid);
    // major lines every 50 mm, drawn a hair above the minor grid
    const gridMajor = makeGridLines(bx, by, 50, 0x363b46);
    gridMajor.position.z = 0.01;
    this.bedGroup.add(gridMajor);

    const border = makeRectLine([0, 0], [bx, by], 0x8b94a8, 0.02);
    this.bedGroup.add(border);

    const crossX = makeLine([bx / 2, 0], [bx / 2, by], 0x4a5160, 0.02);
    const crossY = makeLine([0, by / 2], [bx, by / 2], 0x4a5160, 0.02);
    this.bedGroup.add(crossX);
    this.bedGroup.add(crossY);

    const marginRect = makeRectLine([margin, margin], [bx - margin, by - margin], 0x565d6c, 0.025, true);
    this.bedGroup.add(marginRect);

    for (const area of printer.exclude_areas || []) {
      const [x0, y0, x1, y1] = area;
      const w = x1 - x0;
      const h = y1 - y0;
      const geo = new THREE.PlaneGeometry(w, h);
      const mat = new THREE.MeshBasicMaterial({ color: 0xfb7185, transparent: true, opacity: 0.24, side: THREE.DoubleSide });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(x0 + w / 2, y0 + h / 2, 0.03);
      this.bedGroup.add(mesh);
    }
  }

  // --- 零件网格：按 stl_url 缓存，url 未变不重新下载 ---
  _syncParts(state) {
    const parts = state.parts || [];
    const names = new Set(parts.map((p) => p.name));
    for (const [name, entry] of this._meshes) {
      if (!names.has(name)) {
        if (entry.mesh) this.partsGroup.remove(entry.mesh), disposeObject(entry.mesh);
        this._meshes.delete(name);
      }
    }
    this._colorIndex.clear();
    parts.forEach((p, idx) => {
      this._colorIndex.set(p.name, idx);
      const entry = this._meshes.get(p.name);
      if (entry && entry.url === p.stl_url) return; // 未变，跳过
      this._loadPart(p, idx);
    });
  }

  _loadPart(p, idx) {
    const color = PALETTE[idx % PALETTE.length];
    const prevEntry = this._meshes.get(p.name);
    this._meshes.set(p.name, { mesh: prevEntry ? prevEntry.mesh : null, url: p.stl_url, faces: p.faces || 0, loading: true });
    this._pending += 1;
    this._reportProgress(p.name, 0);

    const finish = (geometry) => {
      if (this._disposed) { geometry.dispose(); return; }
      geometry.computeVertexNormals();
      geometry.computeBoundingBox();
      const material = new THREE.MeshStandardMaterial({ color, flatShading: false, roughness: 0.72, metalness: 0.04 });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.matrixAutoUpdate = false;
      mesh.userData.partName = p.name;
      mesh.userData.baseColor = color;
      mesh.userData.faces = p.faces || Math.round(geometry.attributes.position.count / 3);
      const old = this._meshes.get(p.name);
      if (old && old.mesh) {
        this.partsGroup.remove(old.mesh);
        disposeObject(old.mesh);
      }
      this._meshes.set(p.name, { mesh, url: p.stl_url, faces: mesh.userData.faces, loading: false });
      this.partsGroup.add(mesh);
      this._applyTransformToPart(p.name);
      this._pending = Math.max(0, this._pending - 1);
      this._reportProgress(p.name, 1);
      if (this._selectedName === p.name) this._highlightSelection();
    };

    if (this.mock) {
      // 演示模式：程序生成的盒子代替真实 STL。
      const ext = p.extents_mm || [40, 40, 40];
      const geometry = new THREE.BoxGeometry(ext[0], ext[1], ext[2]);
      const c = p.source_center_mm || [0, 0, 0];
      geometry.translate(c[0], c[1], c[2]);
      finish(geometry);
      return;
    }

    if (this.opts.loadGeometry) {
      this.opts.loadGeometry(p).then((geometry) => {
        if (this._meshes.get(p.name)?.url !== p.stl_url) {
          geometry.dispose();
          this._pending = Math.max(0, this._pending - 1);
          return;
        }
        finish(geometry);
      }).catch((err) => {
        this._pending = Math.max(0, this._pending - 1);
        if (this._meshes.get(p.name)?.url === p.stl_url) {
          const failed = this._meshes.get(p.name);
          if (failed.mesh) this.partsGroup.remove(failed.mesh), disposeObject(failed.mesh);
          this._meshes.delete(p.name); // allow refresh to retry a failed resource
        }
        this._reportProgress(p.name, -1, err);
      });
      return;
    }

    this._loader.load(
      p.stl_url,
      (geometry) => finish(geometry),
      (xhr) => {
        if (xhr && xhr.lengthComputable) this._reportProgress(p.name, xhr.loaded / xhr.total);
      },
      (err) => {
        this._pending = Math.max(0, this._pending - 1);
        this._reportProgress(p.name, -1, err);
      }
    );
  }

  _reportProgress(name, ratio, err) {
    if (this._progressCb) this._progressCb(name, ratio, err, this._pending);
  }

  _applyTransforms(state) {
    if (!state) return;
    const usePlate = this.viewMode === "plate" && state.plates && state.plates.length;
    let placementByPart = null;
    if (usePlate) {
      const plate = state.plates[this.plateIndex] || state.plates[0];
      placementByPart = new Map((plate.placements || []).map((pl) => [pl.part, pl.T]));
    }
    for (const p of state.parts || []) {
      if (usePlate) {
        const T = placementByPart.get(p.name);
        if (T) {
          this._setPartMatrix(p.name, rowMajorToMatrix4(T));
          this._setPartVisible(p.name, true);
        } else {
          this._setPartVisible(p.name, false);
        }
      } else {
        this._setPartMatrix(p.name, new THREE.Matrix4());
        this._setPartVisible(p.name, true);
      }
    }
    this._selectHelper?.update();
    this._loop?.invalidate();
  }

  _applyTransformToPart(name) {
    this._applyTransforms(this._lastState);
  }

  _setPartMatrix(name, matrix) {
    const entry = this._meshes.get(name);
    if (!entry || !entry.mesh) return;
    entry.mesh.matrix.copy(matrix);
    entry.mesh.matrixWorldNeedsUpdate = true;
  }

  _setPartVisible(name, visible) {
    const entry = this._meshes.get(name);
    if (!entry || !entry.mesh) return;
    entry.mesh.visible = visible;
  }

  // --- 拾取 ---
  _pickableMeshes(includeHeavy) {
    const list = [];
    for (const entry of this._meshes.values()) {
      if (!entry.mesh || !entry.mesh.visible) continue;
      if (!includeHeavy && entry.faces > HEAVY_MESH_FACES) continue;
      list.push(entry.mesh);
    }
    return list;
  }

  _updateNdc(evt) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this._pointerNdc.x = ((evt.clientX - rect.left) / rect.width) * 2 - 1;
    this._pointerNdc.y = -((evt.clientY - rect.top) / rect.height) * 2 + 1;
  }

  _onPointerMove(evt) {
    const now = performance.now();
    if (now - this._lastHoverTs < HOVER_THROTTLE_MS) return;
    this._lastHoverTs = now;
    this._updateNdc(evt);
    this._raycaster.setFromCamera(this._pointerNdc, this.camera);
    const hits = this._raycaster.intersectObjects(this._pickableMeshes(false), false);
    const name = hits.length ? hits[0].object.userData.partName : null;
    this._hoveredName = name;
    this.renderer.domElement.style.cursor = name ? "pointer" : "";
    if (this._hoverCb) this._hoverCb(name, evt.clientX, evt.clientY);
  }

  _onClick(evt) {
    this._updateNdc(evt);
    this._raycaster.setFromCamera(this._pointerNdc, this.camera);
    const hits = this._raycaster.intersectObjects(this._pickableMeshes(true), false);
    const name = hits.length ? hits[0].object.userData.partName : null;
    this._setSelected(name, false);
  }

  _setSelected(name, silent) {
    this._selectedName = name;
    this._highlightSelection();
    if (!silent && this._selectCb) this._selectCb(name);
  }

  _highlightSelection() {
    this._loop?.invalidate();
    if (this._selectHelper) {
      this.scene.remove(this._selectHelper);
      disposeObject(this._selectHelper);
      this._selectHelper = null;
    }
    for (const entry of this._meshes.values()) {
      if (!entry.mesh) continue;
      entry.mesh.material.emissive = new THREE.Color(0x000000);
    }
    if (!this._selectedName) return;
    const entry = this._meshes.get(this._selectedName);
    if (!entry || !entry.mesh) return;
    entry.mesh.material.emissive = new THREE.Color(0x0a1830);
    this._selectHelper = new THREE.BoxHelper(entry.mesh, 0x79b7ff);
    this.scene.add(this._selectHelper);
  }

  _onResize() {
    this._loop?.resize();
  }

  // 视口上浮着卡片时，把画面中心挪到没被盖住的那块区域的中心。
  // insets 是四边被盖住的像素数；全为 0 时等同于没有偏移。
  setViewInsets(insets) {
    const next = {
      left: Math.max(0, Number(insets && insets.left) || 0),
      right: Math.max(0, Number(insets && insets.right) || 0),
      top: Math.max(0, Number(insets && insets.top) || 0),
      bottom: Math.max(0, Number(insets && insets.bottom) || 0),
    };
    const prev = this._insets;
    if (prev && prev.left === next.left && prev.right === next.right && prev.top === next.top && prev.bottom === next.bottom) return;
    this._insets = next;
    this._applyViewOffset();
  }

  _applyViewOffset() {
    const rect = this.container.getBoundingClientRect();
    const ins = this._insets;
    if (!ins || rect.width < 1 || rect.height < 1 || (!ins.left && !ins.right && !ins.top && !ins.bottom)) {
      this.camera.clearViewOffset();
    } else {
      // 被盖住的一侧越宽，画面往另一侧挪得越多；最多挪到四分之一，避免极窄时把模型推出画面。
      const dx = Math.max(-rect.width / 4, Math.min(rect.width / 4, (ins.right - ins.left) / 2));
      const dy = Math.max(-rect.height / 4, Math.min(rect.height / 4, (ins.bottom - ins.top) / 2));
      this.camera.setViewOffset(rect.width, rect.height, dx, dy, rect.width, rect.height);
    }
    this.camera.updateProjectionMatrix();
    this._loop?.invalidate();
  }
}

function makeRectLine(p0, p1, color, z, dashed) {
  const pts = [
    new THREE.Vector3(p0[0], p0[1], z || 0),
    new THREE.Vector3(p1[0], p0[1], z || 0),
    new THREE.Vector3(p1[0], p1[1], z || 0),
    new THREE.Vector3(p0[0], p1[1], z || 0),
    new THREE.Vector3(p0[0], p0[1], z || 0),
  ];
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  let mat;
  let line;
  if (dashed) {
    mat = new THREE.LineDashedMaterial({ color, dashSize: 4, gapSize: 3 });
    line = new THREE.Line(geo, mat);
    line.computeLineDistances();
  } else {
    mat = new THREE.LineBasicMaterial({ color });
    line = new THREE.Line(geo, mat);
  }
  return line;
}

function disposeObject(obj) {
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) {
      if (Array.isArray(o.material)) o.material.forEach((m) => m.dispose());
      else o.material.dispose();
    }
  });
}

// 10mm 一格的细网格，只画在床面矩形 [0,bx]x[0,by] 内（不用 GridHelper 的外接正方形，
// 避免非正方形床把网格画出界）。
function makeGridLines(bx, by, step, color) {
  const positions = [];
  const nx = Math.floor(bx / step);
  for (let i = 0; i <= nx; i++) {
    const x = Math.min(i * step, bx);
    positions.push(x, 0, 0, x, by, 0);
  }
  const ny = Math.floor(by / step);
  for (let j = 0; j <= ny; j++) {
    const y = Math.min(j * step, by);
    positions.push(0, y, 0, bx, y, 0);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const mat = new THREE.LineBasicMaterial({ color });
  return new THREE.LineSegments(geo, mat);
}

function makeLine(p0, p1, color, z) {
  const geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(p0[0], p0[1], z || 0),
    new THREE.Vector3(p1[0], p1[1], z || 0),
  ]);
  const mat = new THREE.LineBasicMaterial({ color });
  return new THREE.Line(geo, mat);
}

function numToHexStr(n) {
  return "#" + (n >>> 0).toString(16).padStart(6, "0");
}
