/* Scene Viewer —— merge_ui / a8 / hackday urdf-viewer 三合一。
 *
 * 内核（建模、炸件、编号 sprite、材质、轴向、关节）移植自 hackday urdf-viewer，
 * 那份已经在线上跑了几个月；这里只把它的输入从 `viewer_config + viewer_model +
 * viewer_structure` 三件套换成单份 assembly-scene/v1，并补上 a8 的评审外壳
 * （案列、↑↓ 导航、参考图、URL 同步）。
 *
 * 图层按数据自动亮灭：没有 joints 就没有关节滑杆和轴向开关 —— 切割结果与可动
 * URDF 因此是同一个 viewer 的两种输入，而不是两个 viewer。
 */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { assetUrl, readResource } from './offline.js';
import { RenderLoop, resizeDrawingBuffer } from '../../../../../web/render-loop.js';
import { ViewportFrame } from '../../../../../web/viewport-frame.js';
let loop;
let viewportFrame, userMoved = false;
const invalidate = () => loop?.invalidate();

const $ = (id) => document.getElementById(id);
const stage = $("stage");

/* a8 的加载帘同时当错误帘用。停在一张"还在转"的画面上是最坏的失败模式 ——
 * 看的人会以为还在加载，而其实已经死了。 */
function setCurtain(kind, message, command = "") {
  invalidate();
  const curtain = $("loading-curtain");
  curtain.dataset.state = kind;
  curtain.classList.toggle("is-hidden", kind === "hidden");
  $("loader-orbit").hidden = kind !== "loading";
  $("loading-message").textContent = message || "";
  $("loading-command").hidden = !command;
  $("loading-command").textContent = command;
}

function setStatus(state_, text) {
  const chip = $("status-chip");
  chip.dataset.state = state_;
  chip.replaceChildren(document.createElement("i"), document.createTextNode(text));
}

const PALETTE = [
  0x159d82, 0xe8a62a, 0x397fd1, 0xdf5f68, 0x8664c7,
  0x5b9f48, 0xe27635, 0x319baa, 0xb95a9e, 0x8f9630,
];

const state = {
  index: null,
  caseIndex: -1,
  scene: null,
  model: null,
  token: 0,
  labelsOn: false,
  originalMaterialsOn: false,
  axesOn: false,
  xrayOn: false,
  sourceOn: true,
  wireframeOn: false,
  explode: 0,
  phase: 0,
  playing: false,
  phaseDir: 1,
  lastFrame: 0,
  jointSliders: new Map(),
  selectedPart: null,
  selectedJoint: null,
  pendingPose: null,
  pendingMode: null,
  originalMaterials: new WeakMap(),
  axisHelpers: [],
  partSprites: [],
  explodeDirections: new Map(),
  jointValues: new Map(),
  caseStatus: new Map(),
  mode: "a8",              // a8=当前 / a2=对照 / split=并排
  compareModel: null,
  compareScene: null,
  compareLoading: false,
};

/* ── three 基础设施 ──────────────────────────────────────────── */

/* ── 舞台：配色 / 灯光 / 地面 ────────────────────────────────────
 * 整段抄自 a8 审阅台（tooling/a8_viewer/main.js）。三个要点，别"顺手优化"掉：
 *
 * ① **canvas 用 alpha，scene 不设 background** —— a8 的暖纸色和那层淡网格
 *    来自 CSS 的 #app 渐变与 #app::before，让它透上来才是那个味道；一旦给
 *    scene.background 上色，整张纸就被盖死了。
 * ② **圆盘 + 细环**代替方格地。a8 写死半径 8.5 / 3.8 是因为它把模型归一化到
 *    固定高度；这里模型是真实米制（柜子 ~0.9m），照抄会把柜子淹在一张巨盘里，
 *    所以按模型包围球缩放。
 * ③ 点光与阴影相机的范围**也是尺度相关的**，跟着一起缩放；平行光只定方向，
 *    不用动。
 */

const world = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(31, 1, 0.01, 500);
camera.up.set(0, 1, 0);

const renderer = new THREE.WebGLRenderer({
  antialias: true,
  alpha: true,                       // ① 让 CSS 的纸面透上来
  powerPreference: "high-performance",
});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
stage.prepend(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.screenSpacePanning = true;
controls.zoomToCursor = true;
controls.minDistance = 0.05;
controls.maxDistance = 100;
controls.maxPolarAngle = Math.PI * 0.49;   // 别转到地面以下去
controls.addEventListener('start', () => { userMoved = true; });

world.add(new THREE.HemisphereLight(0xffffff, 0x313747, 2.5));

const keyLight = new THREE.DirectionalLight(0xffffff, 3);
keyLight.position.set(-4.5, 8.5, 6.5);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
world.add(keyLight);

const rimLight = new THREE.DirectionalLight(0xffffff, 1.5);
rimLight.position.set(7, 4, -5);
world.add(rimLight);

const floor = new THREE.Mesh(
  new THREE.CircleGeometry(1, 128),
  new THREE.MeshStandardMaterial({
    color: 0x101012, roughness: 0.86, metalness: 0,
    transparent: true, opacity: 0.45,
  })
);
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
world.add(floor);

const floorRing = new THREE.Mesh(
  // 粗细要按**相对半径**取，跟 a8 一致（3.815/3.8 ≈ +0.39%）。写成 0.999/1
  // 只有 0.1%，缩放到米制模型上就细得看不见了。
  new THREE.RingGeometry(0.996, 1, 128),
  new THREE.MeshBasicMaterial({
    color: 0x444448, transparent: true, opacity: 0.35, side: THREE.DoubleSide,
  })
);
floorRing.rotation.x = -Math.PI / 2;
world.add(floorRing);

/* 地面与尺度相关的灯按模型大小重算。a8 的比例：盘 8.5 / 环 3.8 ≈ 2.24。 */
function layoutStage() {
  const bounds = modelBounds();
  if (!bounds || bounds.isEmpty()) return;
  const size = bounds.getSize(new THREE.Vector3());
  const center = bounds.getCenter(new THREE.Vector3());
  const footprint = Math.max(Math.hypot(size.x, size.z) * 0.5, 0.05);
  const ringRadius = footprint * 1.9;
  const discRadius = ringRadius * 2.24;

  floor.scale.setScalar(discRadius);
  floor.position.set(center.x, bounds.min.y - size.y * 0.004, center.z);
  floorRing.scale.setScalar(ringRadius);
  floorRing.position.set(center.x, bounds.min.y - size.y * 0.003, center.z);

  const radius = Math.max(size.length() * 0.5, 0.05);
  const span = radius * 3;
  const shadow = keyLight.shadow.camera;
  shadow.left = -span; shadow.right = span; shadow.top = span; shadow.bottom = -span;
  shadow.near = 0.01; shadow.far = span * 12;
  shadow.updateProjectionMatrix();
  keyLight.position.set(center.x - radius * 1.8, bounds.min.y + radius * 3.4, center.z + radius * 2.6);
  keyLight.target.position.copy(center);
  keyLight.target.updateMatrixWorld();
  world.add(keyLight.target);

  // Neutral Studio lighting preserves the source material without a warm fog tint.
  world.fog = null;
}

/* ── 建模：scene.parts/joints → link 树 ──────────────────────── */

function applyTransform(object, origin, rpy, scale = null, rotationOrder = "ZYX") {
  object.position.fromArray(origin || [0, 0, 0]);
  object.rotation.set(...(rpy || [0, 0, 0]), rotationOrder || "ZYX");
  if (scale) object.scale.fromArray(scale);
}

function motionRange(joint) {
  if (joint.motionType === "continuous") return [-Math.PI, Math.PI];
  if (joint.motionType === "prismatic") return joint.motionRange || [0, 0.2];
  return joint.poseRange || joint.motionRange || [-Math.PI / 2, Math.PI / 2];
}

function orderedBounds(range) {
  const [start, end] = range;
  return [Math.min(start, end), Math.max(start, end)];
}

function clampToRange(range, amount) {
  const [minimum, maximum] = orderedBounds(range);
  return Math.min(maximum, Math.max(minimum, Number(amount)));
}

function isMovable(joint) {
  return !joint.fixed && joint.motionType !== "fixed";
}

/* ── 机构相位 ────────────────────────────────────────────────────
 * 一个 0→1 驱动全部可动关节。参数化线的所有行程都写成 [0, X]（比例参数，界恒为
 * [0,1]，越界不可表示），所以"相位"才是它的原生抽象；逐关节滑杆对它是错的粒度。
 * 对普通 URDF 它退化成"一键全开/全合"，同样有用。
 *
 * ⚠️ 缓动只给转动，移动保持线性 —— 抽屉匀速滑出才自然，门带 smoothstep 才像
 * 真开合。两者混用会让抽屉在两端"黏一下"。沿用 a8 的取舍，别自作主张统一。
 */

function easedPhase(value) {
  const t = Math.min(1, Math.max(0, Number(value) || 0));
  return t * t * (3 - t * 2);   // smoothstep
}

function jointValueAtPhase(joint, phase) {
  const [lower, upper] = motionRange(joint);
  if (joint.motionType === "continuous") return lower + (upper - lower) * phase;
  if (joint.motionType === "prismatic") return lower + (upper - lower) * phase;   // 线性
  return lower + (upper - lower) * easedPhase(phase);                             // 缓动
}

/* 把相位落到某一个 model 上。对照件也吃相位 —— 相位是"整机开合到几成"，
 * 两边同步开合才对得起来；这跟逐件审阅是两回事，不违反对照件那条规矩。 */
function applyPhaseTo(model, phase, { bindSliders = false } = {}) {
  if (!model) return;
  for (const joint of model.movable) {
    const value = jointValueAtPhase(joint, phase);
    model.setJointValue(joint.name, value);
    if (!bindSliders) continue;
    state.jointValues.set(joint.name, value);
    // 逐关节滑杆跟着走，否则两套控件会各说各话
    const bound = state.jointSliders.get(joint.name);
    if (bound) {
      bound.slider.value = String(value);
      bound.output.value = `${value.toFixed(3)} ${bound.unit}`;
    }
  }
}

function applyPhase(phase, { silent = false } = {}) {
  state.phase = Math.min(1, Math.max(0, Number(phase) || 0));
  if (!state.model) return;
  applyPhaseTo(state.model, state.phase, { bindSliders: true });
  applyPhaseTo(state.compareModel, state.phase);
  if (!silent) {
    $("pose-slider").value = String(state.phase);
    // a8 的读数是 <strong> 不是 <output>：写 .value 只会挂个 JS 属性，屏幕上纹丝不动
    $("pose-value").textContent = `${Math.round(state.phase * 100)}%`;
    // ⚠️ 轨道填充是 CSS 变量 --pose 画的，**默认值 42%**。不写它，滑块在最左、
    // 读数 0%，绿色却一直亮到中间 —— 看起来像"机构已经开了一半"。
    $("pose-slider").style.setProperty("--pose", `${state.phase * 100}%`);
  }
}

/** 播放推进一步（纯函数）。抽出来是为了能脱离 rAF 直接验往返逻辑 ——
 *  页面在后台时 rAF 完全停摆，靠肉眼或浏览器脚本都测不到这段。 */
function advancePhase(phase, direction, deltaSeconds, speed = 0.45) {
  let next = phase + deltaSeconds * speed * direction;
  let dir = direction;
  if (next >= 1) { next = 1; dir = -1; }        // 到端点折返，不是跳回 0
  else if (next <= 0) { next = 0; dir = 1; }
  return { phase: next, direction: dir };
}

function setPlaying(playing) {
  invalidate();
  state.playing = playing && Boolean(state.model?.movable.length);
  state.lastFrame = 0;
  const button = $("play-toggle");
  button.setAttribute("aria-pressed", String(state.playing));
  // 播放/暂停的形状是 CSS 画在里面那个 <span> 上的；写 textContent 会把它冲掉
  button.classList.toggle("is-playing", state.playing);
}

async function loadVisual(loader, visual) {
  const gltf = await loader.loadAsync(assetUrl(visual.file));
  const group = new THREE.Group();
  applyTransform(group, visual.origin, visual.rpy, visual.scale, visual.rotationOrder || "ZYX");
  // 导出侧若注入过 Z-up 根旋转，这里必须清掉，否则叠加成双重旋转（零位就散架）
  const injected = gltf.scene.getObjectByName("urdf_z_up_root");
  if (injected) injected.quaternion.identity();
  group.add(gltf.scene);
  return group;
}

async function buildModel(scene, token) {
  const root = new THREE.Group();
  root.name = "scene-root";
  // Z-up 数据整体扳正一次（且只此一次）
  if (scene.coordinateSystem === "z-up") root.rotation.x = -Math.PI / 2;

  const partNodes = new Map();
  const visualContainers = new Map();
  const jointByChild = new Map();
  const jointRuntime = new Map();
  for (const joint of scene.joints || []) jointByChild.set(joint.child, joint);

  const ensurePart = (name) => {
    if (partNodes.has(name)) return partNodes.get(name);
    const node = new THREE.Group();
    node.name = name;
    const container = new THREE.Group();
    container.name = `${name}:visuals`;
    node.add(container);
    partNodes.set(name, node);
    visualContainers.set(name, container);
    const joint = jointByChild.get(name);
    if (!joint || name === scene.root) {
      root.add(node);
      return node;
    }
    const parent = ensurePart(joint.parent);
    const originNode = new THREE.Group();
    applyTransform(originNode, joint.origin, joint.rpy, null, joint.rotationOrder || "ZYX");
    const motionNode = new THREE.Group();
    originNode.add(motionNode);
    motionNode.add(node);
    parent.add(originNode);
    jointRuntime.set(joint.name, { definition: joint, originNode, motionNode });
    return node;
  };

  for (const part of scene.parts || []) ensurePart(part.name);

  const loader = new GLTFLoader();
  const jobs = (scene.parts || []).flatMap((part) =>
    (part.visuals || []).map((visual) => ({ part, visual }))
  );
  let done = 0;
  const missing = [];
  await Promise.all(jobs.map(async ({ part, visual }) => {
    // 缺一件不该让整案打不开 —— 审阅工具的价值就在于"看见缺了什么"，
    // 整页报错反而把信息藏了。缺件记账，其余照渲。
    let group;
    try {
      group = await loadVisual(loader, visual);
    } catch (error) {
      console.warn(`部件 ${part.name} 加载失败：`, error);
      missing.push(part.name);
      done += 1;
      return;
    }
    if (token !== state.token) { disposeRoot(group); return; }
    group.traverse((object) => {
      if (object.isMesh) {
        object.userData.viewerPart = part.name;
        object.frustumCulled = false;
        object.castShadow = true;      // a8 的观感有一半来自模型投在圆盘上的影子
        object.receiveShadow = true;
      }
    });
    visualContainers.get(part.name).add(group);
    done += 1;
    setCurtain("loading", `LOADING PARTS · ${Math.round((done / Math.max(jobs.length, 1)) * 100)}%`);
  }));

  const setJointValue = (jointName, amount) => {
    const runtime = jointRuntime.get(jointName);
    if (!runtime) return;
    const joint = runtime.definition;
    const range = motionRange(joint);
    const value = clampToRange(range, amount);
    const axis = new THREE.Vector3(...(joint.axis || [0, 0, 1])).normalize();
    runtime.motionNode.position.set(0, 0, 0);
    runtime.motionNode.quaternion.identity();
    if (joint.motionType === "prismatic") runtime.motionNode.position.addScaledVector(axis, value);
    else runtime.motionNode.quaternion.setFromAxisAngle(axis, value);
    root.updateMatrixWorld(true);
  };

  const movable = (scene.joints || []).filter((j) => isMovable(j) && jointRuntime.has(j.name));
  for (const joint of movable) {
    setJointValue(joint.name, clampToRange(motionRange(joint), 0));
  }
  return { root, partNodes, visualContainers, jointRuntime, movable, missing, setJointValue };
}

/* ── 视角 ────────────────────────────────────────────────────── */

/* 当前模式下真正在场上的根。fitView / groundModel / 包围盒全走它 ——
 * 否则并排时相机只框住其中一个，另一半在画面外。 */
function visibleRoots() {
  const roots = [];
  if (state.model && state.mode !== "a2") roots.push(state.model.root);
  if (state.compareModel && state.mode !== "a8") roots.push(state.compareModel.root);
  if (!roots.length && state.model) roots.push(state.model.root);
  return roots;
}

function boundsOf(root) {
  if (!root) return null;
  root.updateMatrixWorld(true);
  // 只吃模型自己的 mesh；地面圆盘不在 root 下，overlay（轴、sprite）显式排除
  const bounds = new THREE.Box3();
  root.traverse((object) => {
    if (object.isMesh && !object.userData.viewerOverlay) bounds.expandByObject(object);
  });
  return bounds;
}

function modelBounds() {
  const bounds = new THREE.Box3();
  for (const root of visibleRoots()) {
    const own = boundsOf(root);
    if (own && !own.isEmpty()) bounds.union(own);
  }
  return bounds;
}

function groundModel(model = state.model) {
  const bounds = boundsOf(model?.root);
  if (!bounds || bounds.isEmpty()) return;
  model.root.position.y -= bounds.min.y;
  model.root.updateMatrixWorld(true);
}

function fitView() {
  userMoved = false;
  const bounds = modelBounds();
  if (!bounds || bounds.isEmpty()) return;
  if (stage.clientWidth && stage.clientHeight) camera.aspect = stage.clientWidth / stage.clientHeight;
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  // Share Studio's framing: reserve cards and the playback deck in projection,
  // without moving model coordinates or replacing a user-controlled orbit.
  const distance = viewportFrame?.distance(sphere.radius) || sphere.radius * 4;
  const target = sphere.center.clone();
  // a8 的机位：偏高、偏侧
  camera.position.copy(target)
    .addScaledVector(new THREE.Vector3(0.88, 0.62, 1.02).normalize(), distance);
  camera.near = Math.max(distance / 200, 0.005);
  camera.far = Math.max(distance * 30, 100);
  camera.updateProjectionMatrix();
  controls.target.copy(target);
  controls.update();
}

/* ── 图层：编号 / 炸件 / 材质 / 轴向 ─────────────────────────── */

function meshesForPart(name) {
  const meshes = [];
  state.model?.partNodes.get(name)?.traverse((object) => {
    if (object.isMesh && object.userData.viewerPart === name) meshes.push(object);
  });
  return meshes;
}

function partNumber(part, index) {
  const match = String(part.partId || part.name || "").match(/(\d+)$/);
  return match ? String(Number(match[1])) : String(index + 1);
}

function makeSprite(text, color, size) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext("2d");
  ctx.beginPath();
  ctx.arc(64, 64, 58, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(23, 33, 31, 0.9)";
  ctx.fill();
  ctx.lineWidth = 7;
  ctx.strokeStyle = `#${color.toString(16).padStart(6, "0")}`;
  ctx.stroke();
  ctx.fillStyle = "#ffffff";
  ctx.font = `700 ${text.length > 2 ? 42 : 54}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 64, 67);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(canvas), depthTest: false, transparent: true,
  }));
  sprite.scale.set(size, size, size);
  sprite.renderOrder = 100;
  sprite.userData.viewerOverlay = true;
  return sprite;
}

function ensureSprites() {
  if (state.partSprites.length) return;
  const bounds = modelBounds();
  if (!bounds || bounds.isEmpty()) return;
  const size = bounds.getSize(new THREE.Vector3());
  const labelSize = Math.max(size.x, size.y, size.z, 0.1) * 0.075;
  (state.scene.parts || []).forEach((part, index) => {
    const meshes = meshesForPart(part.name);
    const container = state.model.visualContainers.get(part.name);
    if (!meshes.length || !container) return;
    const partBounds = new THREE.Box3();
    meshes.forEach((mesh) => partBounds.expandByObject(mesh));
    if (partBounds.isEmpty()) return;
    const center = partBounds.getCenter(new THREE.Vector3());
    container.worldToLocal(center);
    const sprite = makeSprite(partNumber(part, index), PALETTE[index % PALETTE.length], labelSize);
    sprite.position.copy(center);
    sprite.userData.partName = part.name;
    container.add(sprite);
    state.partSprites.push(sprite);
  });
}

function updateSprites() {
  for (const sprite of state.partSprites) {
    const selected = !state.selectedPart || state.selectedPart === sprite.userData.partName;
    sprite.visible = state.labelsOn;
    sprite.material.opacity = selected ? 1 : 0.18;
  }
}

/* 炸开方向 = 该件重心相对整体重心的**偏移向量本身**（不归一化）。
 *
 * 🔴 这条是从 merge_ui 抄回来的，别再"顺手归一化一下"：归一化后每件位移等长，
 * 于是 ① 位于中心的柜体壳会跟顶抽同方向等距飞出去，看上去是整体平移而不是炸开；
 * ② 壳的重心常常正好落在整体重心上，方向向量长度≈0 撞进退化兜底，方向就成了
 * 瞎猜的 (0,1,0)。正比位移没有这两个问题：中心的件自然不动，边缘的件散得远，
 * 相对布局也保住了。
 *
 * 已知局限（merge_ui 同样有）：同心件——盖在盒里、环套环——重心都在中心附近，
 * 这个方法散不开它们。那种要靠别的策略（沿轴推、按包含关系分层）。
 */
function prepareExplode() {
  state.explodeDirections.clear();
  for (const container of state.model.visualContainers.values()) container.position.set(0, 0, 0);
  state.model.root.updateMatrixWorld(true);
  // ⚠️ 用主模型自己的盒，不能用 modelBounds()：并排时那是两者的合并盒，
  // 炸开方向会整体偏向对照件那一侧。
  const bounds = boundsOf(state.model.root);
  if (!bounds || bounds.isEmpty()) return;
  const center = bounds.getCenter(new THREE.Vector3());
  for (const part of state.scene.parts || []) {
    const meshes = meshesForPart(part.name);
    const container = state.model.visualContainers.get(part.name);
    if (!meshes.length || !container?.parent) continue;
    const partBounds = new THREE.Box3();
    meshes.forEach((mesh) => partBounds.expandByObject(mesh));
    // 世界系下的偏移，再转进 container 父节点的朝向（关节树里父帧可能是转过的）
    const direction = partBounds.getCenter(new THREE.Vector3()).sub(center)
      .applyQuaternion(container.parent.getWorldQuaternion(new THREE.Quaternion()).invert());
    state.explodeDirections.set(part.name, direction);
  }
}
/* 炸开只作用于主模型 —— 跟"对照件不参与逐件审阅"同一条规矩：
 * 炸件是拆开被审对象去看内部，参照物跟着散开只会干扰对读。 */
function applyExplode(value) {
  state.explode = value;
  if (!state.model) return;
  if (!state.explodeDirections.size) prepareExplode();
  for (const [name, container] of state.model.visualContainers) {
    container.position.copy(state.explodeDirections.get(name) || new THREE.Vector3())
      .multiplyScalar(value);
  }
  state.model.root.updateMatrixWorld(true);
  const slider = $("explode");
  slider.value = String(value);
  // 读数按**行程比例**算，不是按倍数：量程是 0–1.5（跟 merge_ui 一致），
  // 写 value*100 的话拉到头会显示 150%，而滑块和填充都在 100% 处 ——
  // 数字跟它俩都对不上。三者统一到行程比例。
  const span = Number(slider.max || 1) - Number(slider.min || 0);
  const ratio = Math.max(0, Math.min(1, (value - Number(slider.min || 0)) / (span || 1)));
  $("explode-value").value = `${Math.round(ratio * 100)}%`;
  slider.style.setProperty("--explode", `${ratio * 100}%`);
}

function rememberMaterial(mesh) {
  if (state.originalMaterials.has(mesh)) return;
  state.originalMaterials.set(mesh, mesh.material);
  const source = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  const replacement = source.map(() => new THREE.MeshBasicMaterial({
    side: THREE.DoubleSide, toneMapped: false,
  }));
  mesh.material = replacement.length === 1 ? replacement[0] : replacement;
}

/* 材质原始态快照。X-ray / wireframe 是**叠加层**，关掉要还原成本来的样子，
 * 不能记成"关掉 = 不透明 + 不线框"—— 原 PBR 材质本来就可能是半透的。 */
const materialBase = new WeakMap();

function rememberBase(material) {
  if (materialBase.has(material)) return;
  materialBase.set(material, {
    transparent: material.transparent,
    opacity: material.opacity,
    depthWrite: material.depthWrite,
    wireframe: material.wireframe,
  });
}

function materialsOfPart(name) {
  const out = [];
  for (const mesh of meshesForPart(name)) {
    const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of list) if (material) out.push(material);
  }
  return out;
}

function applyPartColors() {
  (state.scene.parts || []).forEach((part, index) => {
    for (const mesh of meshesForPart(part.name)) {
      rememberMaterial(mesh);
      const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const material of list) material.color.setHex(PALETTE[index % PALETTE.length]);
    }
  });
}

/* 叠加层统一在这儿落：谁开着都不会互相吃掉对方（a8 的 INSPECTION LAYERS
 * 是并列的开关，不是互斥的模式）。 */
function applyOverlays() {
  (state.scene.parts || []).forEach((part) => {
    const selected = !state.selectedPart || state.selectedPart === part.name;
    for (const material of materialsOfPart(part.name)) {
      rememberBase(material);
      const base = materialBase.get(material);
      material.wireframe = state.wireframeOn;
      if (state.xrayOn) {
        material.transparent = true;
        material.opacity = selected ? 0.42 : 0.06;
        material.depthWrite = false;
      } else if (!selected) {
        material.transparent = true;
        material.opacity = 0.1;
        material.depthWrite = false;
      } else {
        material.transparent = base.transparent;
        material.opacity = base.opacity;
        material.depthWrite = base.depthWrite;
      }
      material.needsUpdate = true;
    }
  });
}

/* Source skin：只藏几何，不藏 link 节点 —— 藏 link 会把它的子 link 一起带走，
 * 于是"关掉皮肤只看关节示意"变成"整个模型消失"。 */
function applySourceVisibility() {
  for (const container of state.model?.visualContainers.values() || []) {
    container.visible = state.sourceOn;
  }
}

function restoreMaterials() {
  for (const node of state.model?.partNodes.values() || []) {
    node.traverse((mesh) => {
      const original = state.originalMaterials.get(mesh);
      if (!original) return;
      (Array.isArray(mesh.material) ? mesh.material : [mesh.material])
        .forEach((material) => material.dispose());
      mesh.material = original;
      state.originalMaterials.delete(mesh);
    });
  }
}

/* 图层可用性。**行永远在，不可用就置灰并说明为什么** —— 行直接消失会让人
 * 以为"这版少了个功能"，而真相往往是"这案没有这层的数据"。 */
function syncLayerAvailability() {
  const hasMotion = (state.model?.movable.length || 0) > 0;
  const rows = [
    ["completion-toggle", hasMotion, "这案没有关节 —— 没有轴与原点可画"],
    // 原材质是"分件配色"的反面：没开配色时材质本来就是原样，开关是空转的
    ["texture-toggle", state.labelsOn, "先开「编号 / 分组」—— 没上配色时本来就是原材质"],
  ];
  // 炸开需要至少两件。一件的案（原 mesh 切割前）拖滑杆什么都不会发生 ——
  // 控件不该看着能用却是空转的。
  const parts = (state.scene?.parts || []).length;
  const explodable = parts > 1;
  $("explode").disabled = !explodable;
  const deck = document.querySelector(".explode-deck");
  deck.classList.toggle("is-disabled", !explodable);
  deck.title = explodable ? "" : `只有 ${parts} 个件 —— 没有可炸开的东西`;

  for (const [id, enabled, why] of rows) {
    const input = $(id);
    const label = input.closest("label");
    input.disabled = !enabled;
    label.classList.toggle("is-disabled", !enabled);
    label.title = enabled ? "" : why;
    if (!enabled && input.checked) {
      input.checked = false;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
}

function refreshAppearance() {
  if (!state.model) return;
  if (state.labelsOn && !state.originalMaterialsOn) applyPartColors();
  else restoreMaterials();
  applyOverlays();
  applySourceVisibility();
  updateSprites();
}

function clearAxes() {
  for (const helper of state.axisHelpers) {
    helper.parent?.remove(helper);
    helper.traverse((object) => {
      object.geometry?.dispose?.();
      object.material?.dispose?.();
    });
  }
  state.axisHelpers = [];
  $("legend-completion").hidden = true;
}

function createAxisHelper(axis, length, color) {
  const direction = new THREE.Vector3(...axis).normalize();
  const group = new THREE.Group();
  const material = new THREE.MeshBasicMaterial({
    color, depthTest: false, transparent: true, opacity: 0.94,
  });
  const rotation = new THREE.Quaternion()
    .setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(length * 0.018, length * 0.018, length * 0.78, 10), material);
  shaft.quaternion.copy(rotation);
  shaft.position.copy(direction).multiplyScalar(length * 0.39);
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(length * 0.065, length * 0.22, 12), material.clone());
  cone.quaternion.copy(rotation);
  cone.position.copy(direction).multiplyScalar(length * 0.89);
  const pivot = new THREE.Mesh(new THREE.SphereGeometry(length * 0.045, 14, 10), material.clone());
  group.add(shaft, cone, pivot);
  group.traverse((object) => {
    object.renderOrder = 50;
    object.userData.viewerOverlay = true;
  });
  return group;
}

function showAxes() {
  clearAxes();
  const bounds = modelBounds();
  if (!bounds || bounds.isEmpty()) return;
  const size = bounds.getSize(new THREE.Vector3());
  const length = Math.max(size.x, size.y, size.z, 1) * 0.16;
  (state.scene.joints || []).filter(isMovable).forEach((joint, index) => {
    const runtime = state.model.jointRuntime.get(joint.name);
    if (!runtime) return;
    const helper = createAxisHelper(
      joint.axis || [0, 0, 1], length, PALETTE[index % PALETTE.length]);
    runtime.originNode.add(helper);
    state.axisHelpers.push(helper);
  });
  $("legend-completion").hidden = state.axisHelpers.length === 0;
}

/* ── 对照层 ──────────────────────────────────────────────────────
 * 同一评审单元的第二套几何（`scene.compare`）。两条规矩写在契约里，这里落实：
 *   ① 对照件**不参与逐件审阅** —— 保持原材质，不上编号配色、不进部件清单、
 *      不响应点选。它是参照物；否则"哪个 part-03"会同时指向两个模型。
 *   ② **不递归** —— 对照方自己的 compare 一律忽略，只并排两套。
 */

const SPLIT_GAP = 0.22;  // 相对两者宽度之和的间隙比例

function disposeCompare() {
  if (!state.compareModel) return;
  disposeRoot(state.compareModel.root);
  state.compareModel = null;
  state.compareScene = null;
}

async function ensureCompare(token) {
  if (state.compareModel || state.compareLoading) return state.compareModel;
  const compare = state.scene?.compare;
  if (!compare?.sceneUrl) return null;
  state.compareLoading = true;
  try {
    const scene = await readResource(compare.sceneUrl);
    delete scene.compare;                       // ② 不递归
    if (token !== state.token) return null;     // 已经切到别的案子了
    const model = await buildModel(scene, token);
    if (token !== state.token) { disposeRoot(model.root); return null; }
    state.compareScene = scene;
    state.compareModel = model;
    world.add(model.root);
    groundModel(model);
    // 对照件一律原材质：它是参照物，不是被审对象
    if (model.movable.length) applyPhaseTo(model, state.phase);
    return model;
  } finally {
    state.compareLoading = false;
  }
}

/* 并排布局：两者各自居中到自己那一半，间隙按两者宽度取，
 * 免得小件被大件挤到画面边上。 */
function layoutMode() {
  const main = state.model?.root;
  const other = state.compareModel?.root;
  if (main) main.position.x = 0;
  if (other) other.position.x = 0;
  if (state.mode !== "split" || !main || !other) return;
  const a = boundsOf(main);
  const b = boundsOf(other);
  if (!a || a.isEmpty() || !b || b.isEmpty()) return;
  const wa = a.max.x - a.min.x;
  const wb = b.max.x - b.min.x;
  const gap = (wa + wb) * SPLIT_GAP;
  main.position.x = (wb + gap) / 2;
  other.position.x = -(wa + gap) / 2;
  main.updateMatrixWorld(true);
  other.updateMatrixWorld(true);
}

/* 面板永远要说清楚"你现在看的是哪一侧"。
 *
 * 🔴 这条是被真事逼出来的：模式切到对照后，舞台上换成了对照几何，右侧面板却
 * 还在描述主案 —— 于是在一个 1 件的"原 mesh"案上切到"切割后"，屏幕上是切开的
 * 几何，面板上写着"1 件"，读的人只能得出"切割后还是一整块"这个错误结论。
 * 面板不跟着走比按钮撞名更能骗人。
 */
function renderModeContext() {
  const compare = state.scene?.compare;
  const total = (state.index?.cases || []).length;
  const index = state.caseIndex + 1;
  const base = `CASE ${String(index).padStart(2, "0")} / ${String(total).padStart(2, "0")}`
    + (state.scene?.eyebrow ? ` · ${state.scene.eyebrow}` : "");
  let suffix = "";
  if (compare && state.mode === "a2") {
    const parts = (state.compareScene?.parts || []).length;
    suffix = ` · 正在看对照：${compare.label}${parts ? `（${parts} 件）` : ""}`;
  } else if (compare && state.mode === "split") {
    suffix = " · 并排：左=对照，右=本案";
  }
  $("case-index").textContent = base + suffix;

  // 🔴 面板描述**舞台上那一份**，不是"本案"。
  // 这条是被用户当场戳穿逼出来的：一个 1 件的"原 mesh"案切到对照档，舞台上是
  // 4 件的切割结果，面板却照旧写"拓扑 1 件 / 部件 1" —— 图上明明是散开的几块，
  // 字上说是一整块。小字上标一句"正在看对照"不够，事实卡和清单必须一起跟着走。
  const showingCompare = state.mode === "a2" && state.compareScene;
  const shown = showingCompare ? state.compareScene : state.scene;
  const model = showingCompare ? state.compareModel : state.model;
  const entry = state.index?.cases?.[state.caseIndex] || {};
  if (state.scene) renderFacts(shown, entry, showingCompare ? [] : (state.model?.missing || []), model);
  $("case-title").textContent = shown?.title || entry.id || "";
  $("parts-section").classList.toggle("is-muted", Boolean(showingCompare));
  $("joints-section").classList.toggle("is-muted", Boolean(showingCompare));
  renderInspector();
}

function applyModeVisibility() {
  if (state.model) state.model.root.visible = state.mode !== "a2";
  if (state.compareModel) state.compareModel.root.visible = state.mode !== "a8";
  for (const button of document.querySelectorAll("#mode-switch [data-mode]")) {
    button.classList.toggle("is-active", button.dataset.mode === state.mode);
  }
}

async function setMode(mode) {
  const compare = state.scene?.compare;
  if (mode !== "a8" && !compare) return;   // 没有对照就没有别的档
  const token = state.token;
  state.mode = mode;
  applyModeVisibility();
  if (mode !== "a8") {
    const before = $("loading-curtain").dataset.state;
    try {
      await ensureCompare(token);
    } catch (error) {
      console.error(error);
      // 对照拿不到就退回当前档并说清楚，别停在一个空舞台上
      state.mode = "a8";
      applyModeVisibility();
      setCurtain("error", `对照层加载失败：${error?.message || error}`);
      return;
    }
    if (token !== state.token) return;
    renderModeContext();
    if (before === "hidden") setCurtain("hidden", "");
  }
  applyModeVisibility();
  renderModeContext();
  layoutMode();
  layoutStage();
  fitView();
  syncUrl();
}

/* ── 检视面板 ────────────────────────────────────────────────── */

function createRow(name, detail, color) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "inspector-row";
  const mark = document.createElement("i");
  mark.className = "color-mark";
  mark.style.setProperty("--item-color", `#${color.toString(16).padStart(6, "0")}`);
  const copy = document.createElement("span");
  copy.className = "row-copy";
  const title = document.createElement("strong");
  title.textContent = name;
  const meta = document.createElement("small");
  meta.textContent = detail;
  copy.append(title, meta);
  row.append(mark, copy);
  return row;
}

function addDetailLine(host, label, value) {
  if (value === undefined || value === null || value === "") return;
  const row = document.createElement("div");
  row.className = "detail-line";
  const key = document.createElement("b");
  key.textContent = label;
  const content = document.createElement("span");
  content.textContent = Array.isArray(value)
    ? `[${value.map((v) => Number(v).toFixed(3)).join(", ")}]`
    : String(value);
  row.append(key, content);
  host.append(row);
}

function renderSelectionDetail() {
  const host = $("selection-detail");
  host.replaceChildren();
  let title = "";
  const fields = [];
  if (state.selectedJoint) {
    const joint = (state.scene.joints || []).find((item) => item.name === state.selectedJoint);
    if (joint) {
      title = joint.name;
      fields.push(
        ["层级", `${joint.parent} → ${joint.child}`],
        ["类型", joint.motionType],
        ["轴方向", joint.axis],
        ["轴原点", joint.axisOriginWorld || joint.origin],
        ["运动范围", joint.motionRange || joint.poseRange],
        ["生成依据", joint.source],
      );
    }
  } else if (state.selectedPart) {
    const part = (state.scene.parts || []).find((item) => item.name === state.selectedPart);
    if (part) {
      title = part.name;
      fields.push(
        ["部件编号", part.partId],
        ["语义", part.label || (part.labels || []).join(", ")],
        ["面数", part.metrics?.faces],
        ["顶点", part.metrics?.vertices],
        ["水密", part.metrics?.is_watertight === undefined
          ? "" : (part.metrics.is_watertight ? "是" : "否")],
        ["尺寸", part.metrics?.extent],
        ["运动类型", part.motionType],
        ["说明", part.note],
      );
    }
  }
  if (!title) { host.hidden = true; return; }
  const heading = document.createElement("h3");
  heading.textContent = title;
  host.append(heading);
  fields.forEach(([label, value]) => addDetailLine(host, label, value));
  host.hidden = false;
}

function renderInspector() {
  state.jointSliders.clear();
  // 对照档下清单要列**舞台上那一份**。但对照件不参与逐件审阅（契约里那条 ①），
  // 所以列出来是只读的：不点选、不上配色、关节不给滑杆。
  const readOnly = state.mode === "a2" && Boolean(state.compareScene);
  const shown = readOnly ? state.compareScene : state.scene;
  const parts = shown.parts || [];
  const joints = (shown.joints || []).filter(isMovable);

  const partsList = $("parts-list");
  partsList.replaceChildren();
  parts.forEach((part, index) => {
    const detail = [part.partId, part.label || (part.labels || []).join(", "),
      part.metrics?.faces ? `${part.metrics.faces} 面` : ""].filter(Boolean).join(" · ");
    const row = createRow(part.name, detail || "无扩展信息", PALETTE[index % PALETTE.length]);
    if (readOnly) {
      row.disabled = true;
      row.title = "对照件不参与逐件审阅 —— 切回本案那一档再点";
    } else {
      row.classList.toggle("active", state.selectedPart === part.name);
      row.addEventListener("click", () => {
        state.selectedPart = state.selectedPart === part.name ? null : part.name;
        state.selectedJoint = null;
        refreshAppearance();
        renderInspector();
      });
    }
    partsList.append(row);
  });

  const jointsList = $("joints-list");
  jointsList.replaceChildren();
  joints.forEach((joint, index) => {
    if (readOnly) {
      const axisText = (joint.axis || []).map((v) => Number(v).toFixed(2)).join(", ");
      const row = createRow(joint.name, `${joint.motionType} · axis [${axisText}]`,
        PALETTE[index % PALETTE.length]);
      row.disabled = true;
      row.title = "对照件的关节 —— 相位统一驱动两边，这里不单独调";
      jointsList.append(row);
      return;
    }
    const article = document.createElement("article");
    article.className = "joint-control";
    const axisText = (joint.axis || []).map((v) => Number(v).toFixed(2)).join(", ");
    const head = createRow(joint.name, `${joint.motionType} · axis [${axisText}]`,
      PALETTE[index % PALETTE.length]);
    head.classList.toggle("active", state.selectedJoint === joint.name);
    head.addEventListener("click", () => {
      state.selectedJoint = state.selectedJoint === joint.name ? null : joint.name;
      state.selectedPart = state.selectedJoint ? joint.child : null;
      refreshAppearance();
      renderInspector();
    });
    const range = motionRange(joint);
    const [lower, upper] = orderedBounds(range);
    const current = state.jointValues.has(joint.name)
      ? state.jointValues.get(joint.name)
      : clampToRange(range, 0);
    const unit = joint.motionType === "prismatic"
      ? (joint.linearUnit === "relative" ? "u" : "m")
      : "rad";
    const control = document.createElement("label");
    control.className = "joint-slider";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = String(lower);
    slider.max = String(upper);
    slider.step = String(Math.max(Math.abs(upper - lower) / 500, 0.0001));
    slider.value = String(current);
    slider.setAttribute("aria-label", `${joint.name} 运动控制`);
    const output = document.createElement("output");
    output.value = `${current.toFixed(3)} ${unit}`;
    slider.addEventListener("input", (event) => {
      const value = Number(event.currentTarget.value);
      state.jointValues.set(joint.name, value);
      state.model.setJointValue(joint.name, value);
      output.value = `${value.toFixed(3)} ${unit}`;
      // 手动调单个关节 = 离开相位统一驱动，继续播放会把它冲掉
      setPlaying(false);
    });
    state.jointSliders.set(joint.name, { slider, output, unit });
    control.append(slider, output);
    article.append(head, control);
    jointsList.append(article);
  });

  $("parts-count").textContent = String(parts.length);
  $("joints-count").textContent = String(joints.length);
  $("joints-section").hidden = joints.length === 0;
  $("parts-section").querySelector("h3").firstChild.textContent = readOnly ? "对照部件 " : "部件 ";
  if (readOnly) $("selection-detail").hidden = true;
  else renderSelectionDetail();
}

/* 案列的下边界要避开左下角那张证据卡（高度随图片比例变），否则案子一多，
 * 列表尾部就被卡片压住够不着。
 * ⚠️ 这里**不用 ResizeObserver**：内嵌浏览器里它对这个绝对定位元素一次都不触发
 * （实测 observe 后 300ms 内 0 次回调，连初始那次都没有）。改成在真正会改高度的
 * 三个时刻显式量：换案、图片加载完、展开/收起。 */
function syncEvidenceHeight() {
  const card = $("evidence-card");
  const height = card.hidden ? 0 : card.getBoundingClientRect().height;
  document.documentElement.style.setProperty("--evidence-h", `${Math.round(height)}px`);
}

function renderRefs() {
  const refs = state.scene.refs || [];
  const primary = refs[0];
  $("evidence-card").hidden = !primary;
  if (!primary) { syncEvidenceHeight(); return; }
  $("reference-image").src = assetUrl(primary.url);
  $("reference-image").alt = primary.caption || "参考图";
  $("reference-hash").textContent = primary.caption || "参考图";
  $("reference-note").textContent = refs.length > 1
    ? `本案共 ${refs.length} 张参考；下面的件与关节都是这一单实际跑出来的。`
    : "下面的件与关节都是这一单实际跑出来的。";
  $("reference-image").onload = syncEvidenceHeight;
  syncEvidenceHeight();
}

/* ── 评审外壳：案列 / 键盘 / URL ─────────────────────────────── */

/* ── 审计层：G / B 标记 ──────────────────────────────────────────
 * 移植自 a8 审阅台，三条性质原样保住：
 *   ① 身份是 executionKey = <batchId>::<caseId> —— 标的是"哪个批次里的哪一次
 *      执行"，不是"哪个案子"。同一个案在两个批次里可以有不同结论。
 *   ② contentSha256 做陈旧闸门 —— 数据重建过，旧标记不生效。**灰掉而不是删掉**，
 *      让人看得见"这里以前标过、但对象已经变了"，比静默套用或静默丢弃都强。
 *   ③ 导出带 scope.executionKeys —— 回灌时只覆盖本次可见范围，不误伤别的批次。
 */

const CURATION_KEY = "scene-viewer-curation/v1";
const CURATION_EXPORT_SCHEMA = "assembly-scene-curation/v1";

function loadCuration() {
  return {};
}

const curation = loadCuration();

function saveCuration() {
  // srcdoc has an opaque origin: do not pretend localStorage persisted a vote.
  $("curation-export").textContent = '导出标记*';
  document.querySelector('.review-session').textContent = '标记尚未保存 · 导出标记可保存到工作区 · 原数据只读';
}

/** 挂了 A8 registry 时，服务端那份是真话 —— 它跨机器、跨浏览器。 */
function serverBacked() {
  return Boolean(state.index?.catalog?.writable);
}

/** 当前生效的结论；指纹对不上就不算数（但把 stale 标出来）。 */
function decisionOf(entry) {
  if (serverBacked()) {
    // 服务端已经按 manifestSha256 把陈旧的挡在写入口了，这里不再二次判定
    return {
      classification: entry.decision || null,
      stale: false,
      staleClassification: null,
      markedAt: entry.decidedAt || null,
    };
  }
  const stored = curation[entry.executionKey];
  if (!stored) return { classification: null, stale: false };
  const stale = stored.contentSha256 !== entry.contentSha256;
  return {
    classification: stale ? null : stored.classification,
    stale,
    staleClassification: stale ? stored.classification : null,
    markedAt: stored.markedAt,
  };
}

async function setClassification(entry, classification) {
  if (state.index?.curationEnabled === false) return;
  const current = decisionOf(entry);
  // 再点一次同一个标 = 取消（a8 同款手感）
  const next = current.classification === classification ? null : classification;

  if (serverBacked()) {
    const before = entry.decision || "";
    entry.decision = next || "";           // 先落屏幕，手感不能等网络
    entry.decidedAt = next ? new Date().toISOString() : "";
    renderCaseList();
    try {
      await postCuration();
    } catch (error) {
      // 回滚并说清楚。默认"写上了"是审计数据最坏的谎。
      entry.decision = before;
      renderCaseList();
      console.error(error);
      setCurtain("error", `标记没写进 registry：${error?.message || error}`);
    }
    return;
  }

  if (next === null) delete curation[entry.executionKey];
  else {
    curation[entry.executionKey] = {
      classification: next,
      contentSha256: entry.contentSha256,
      markedAt: new Date().toISOString(),
    };
  }
  saveCuration();
  renderCaseList();
}

async function postCuration() {
  const response = await fetch("api/curation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildCurationExport()),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

function buildCurationExport() {
  const cases = state.index?.cases || [];
  const exportedAt = new Date().toISOString();
  const decisions = cases.map((entry) => {
    const decision = decisionOf(entry);
    if (!decision.classification) return null;
    return {
      executionKey: entry.executionKey,
      // 跨批次目录（golden / bad）里每案的批次各不相同，不能取索引那个全局值
      batchId: entry.batchId || state.index.batchId || "local",
      caseId: entry.id,
      classification: decision.classification,
      // 服务端的陈旧闸门比对的是它 —— 缺了就写不进 registry
      manifestSha256: entry.manifestSha256 || "",
      contentSha256: entry.contentSha256,
      markedAt: decision.markedAt || exportedAt,
      caseSnapshot: {
        title: entry.title,
        eyebrow: entry.eyebrow || null,
        parts: entry.parts,
        joints: entry.joints,
      },
    };
  }).filter(Boolean);
  return {
    schema: CURATION_EXPORT_SCHEMA,
    exportedAt,
    sourceIndex: {
      schema: state.index?.schema,
      title: state.index?.title,
      batchId: state.index?.batchId || "local",
      caseCount: cases.length,
    },
    // 回灌语义：只替换本次可见的这批 execution，别的批次的结论不动
    scope: { mode: "replace-visible-executions", executionKeys: cases.map((c) => c.executionKey) },
    decisions,
  };
}

function exportCuration() {
  const payload = buildCurationExport();
  if (window.parent !== window && location.protocol === 'about:') {
    $("curation-export").textContent = '正在保存…';
    window.parent.postMessage({ type: 'workbench-review-export', payload }, '*');
    return;
  }
  const stamp = payload.exportedAt.replace(/[:.]/g, "-");
  const safe = String(payload.sourceIndex.batchId).replace(/[^A-Za-z0-9._-]+/g, "-");
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = `scene-viewer-${safe}-curation-${stamp}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10000);
  $("curation-export").textContent = '导出标记';
}

window.addEventListener('message', event => {
  if (event.source !== parent || event.data?.type !== 'workbench-review-saved') return;
  const { path, error } = event.data;
  $("curation-export").textContent = error ? '保存失败，重试' : '导出标记';
  document.querySelector('.review-session').textContent = error ? `标记未保存：${error}` : `标记已保存：${path}`;
  document.querySelector('.review-session').title = error || path;
});

function renderCaseList() {
  const host = $("case-rail");
  host.replaceChildren();
  let golden = 0;
  let bad = 0;
  let stale = 0;
  let lastGroup = null;
  (state.index?.cases || []).forEach((entry, index) => {
    const decision = decisionOf(entry);
    if (decision.classification === "golden") golden += 1;
    if (decision.classification === "typical_bad") bad += 1;
    if (decision.stale) stale += 1;

    // 分组小标题：19 个案平铺成一列谁也记不住哪个是哪类。索引里的 eyebrow
    // 已经带着批次/域，直接拿它断段。
    const group = entry.eyebrow || "";
    if (group && group !== lastGroup) {
      lastGroup = group;
      const head = document.createElement("div");
      head.className = "case-group";
      head.textContent = group;
      host.append(head);
    }

    const row = document.createElement("div");
    row.className = "case-row";
    row.dataset.executionKey = entry.executionKey || entry.id;
    if (decision.stale) row.dataset.stale = "1";

    const markers = document.createElement("div");
    markers.className = "case-markers";
    markers.setAttribute("role", "group");
    for (const [classification, label, title] of [
      ["golden", "G", "Golden case"],
      ["typical_bad", "B", "Typical bad case"],
    ]) {
      const mark = document.createElement("button");
      mark.type = "button";
      mark.className = `case-mark case-mark-${classification}`;
      mark.dataset.classification = classification;
      mark.textContent = label;
      mark.title = `${entry.title || entry.id} · ${title}`;
      const shown = decision.classification || decision.staleClassification;
      mark.setAttribute("aria-pressed", String(shown === classification));
      mark.addEventListener("click", (event) => {
        event.stopPropagation();  // 别顺手切了案子
        setClassification(entry, classification);
      });
      markers.append(mark);
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = `case-button${index === state.caseIndex ? " is-active" : ""}`;
    button.dataset.case = entry.id;
    button.title = entry.title || entry.id;  // 案名比 a8 的短名长，列里放不下
    const number = document.createElement("span");
    number.className = "case-number";
    number.textContent = String(index + 1).padStart(2, "0");
    const copy = document.createElement("span");
    copy.className = "case-copy";
    const title = document.createElement("strong");
    title.textContent = entry.title || entry.id;
    const meta = document.createElement("small");
    meta.textContent = `${entry.parts} 件${entry.joints ? ` · ${entry.joints} DOF` : ""}`
      + (entry.hasCompare ? " · ⇔" : "");
    copy.append(title, meta);
    button.append(number, copy);
    // a8 用第三列那颗琥珀点表示"这案要修"。同一颗点两种来源：上游判 blocked，
    // 或本地标记已陈旧。鼠标悬停说明是哪一种。
    const status = state.caseStatus.get(entry.id) ?? entry.status ?? "";
    const flagged = decision.stale || status === "blocked";
    if (flagged) {
      const dot = document.createElement("em");
      dot.title = status === "blocked" ? "上游判定：blocked" : "标记已陈旧";
      button.append(dot);
    }
    button.addEventListener("click", () => loadCase(index));

    row.append(markers, button);
    if (decision.stale) {
      const note = document.createElement("small");
      note.className = "case-stale";
      note.textContent = "内容已变，旧标记失效";
      row.append(note);
    }
    host.append(row);
  });
  $("golden-count").textContent = String(golden);
  $("bad-count").textContent = String(bad);
  $("stale-count").textContent = String(stale);
  $("stale-wrap").hidden = stale === 0;
}

function disposeRoot(root) {
  root.removeFromParent();
  const disposed = new Set();
  root.traverse((object) => {
    object.geometry?.dispose?.();
    for (const source of [object.material, state.originalMaterials.get(object)]) {
      for (const material of Array.isArray(source) ? source : [source]) {
        if (!material || disposed.has(material)) continue;
        disposed.add(material);
        for (const value of Object.values(material)) if (value?.isTexture && !disposed.has(value)) {
          disposed.add(value); value.dispose(); value.source?.data?.close?.();
        }
        material.dispose();
      }
    }
  });
}

function disposeModel() {
  if (!state.model) return;
  disposeRoot(state.model.root);
  state.model = null;
  state.partSprites = [];
  state.axisHelpers = [];
  state.explodeDirections.clear();
  state.jointValues.clear();
  state.originalMaterials = new WeakMap();
  state.selectedPart = null;
  state.selectedJoint = null;
}

/* 事实卡：a8 那四格。scene_viewer 吃的是多来源数据，字段缺了就留 "—" ——
 * 切件数据集根本没有"线上判定"这种跑批元数据，**空着比编一个强**。 */
function renderFacts(scene, entry, missing, model = state.model) {
  const parts = scene.parts || [];
  const joints = scene.joints || [];
  const movable = model?.movable || [];
  const shownParts = missing.length ? `${parts.length - missing.length}/${parts.length}` : String(parts.length);
  const frame = scene.coordinateSystem || "—";
  $("fact-topology").textContent = `${shownParts} 件 · ${frame}`;
  $("fact-topology").title = missing.length ? `缺件：${missing.join("、")}` : "";

  const provenance = scene.provenance || {};
  // A8 的案表自己写了这四格（topology / profile / a2 / a8）。上游写了就照抄，
  // **不拿本地推算去覆盖它** —— 那四句话是跑批时的结论，viewer 没资格改。
  const audit = provenance.audit || {};
  if (audit.topology) $("fact-topology").textContent = audit.topology;
  $("fact-source").textContent = audit.profile || provenance.source || entry.eyebrow || "—";
  $("fact-source").previousElementSibling.textContent = audit.profile ? "线上判定" : "来源";

  // 切割 label：有逐件语义名才算"有 label"，光有件数不算
  const labelled = parts.filter((part) => part.label || (part.labels || []).length).length;
  $("fact-a2").textContent = audit.a2 || (labelled ? `${labelled}/${parts.length} 件有名` : "—");

  if (!joints.length) {
    // 切割结果没有关节是**合法的**，不是缺陷。写清楚它为什么空。
    $("fact-a8").textContent = "无关节（切件）";
  } else {
    const kinds = new Map();
    for (const joint of movable) kinds.set(joint.motionType, (kinds.get(joint.motionType) || 0) + 1);
    const breakdown = [...kinds].map(([kind, count]) => `${count} ${kind}`).join(" · ");
    $("fact-a8").textContent = audit.a8
      || `${parts.length} link · ${movable.length} joint${breakdown ? ` (${breakdown})` : ""}`;
  }

  const note = audit.note || provenance.poseSemantics?.note || provenance.note || "";
  $("case-note").textContent = note || (joints.length ? "" : "切割结果：只有件，没有关节 —— 相位条因此不出现。");
  $("case-note").hidden = !$("case-note").textContent;

  // 阻断说明：上游明确写了才出，不自己编
  const blocker = audit.blocker || provenance.blocker?.title || "";
  const blockerCopy = audit.blockerCopy || provenance.blocker?.copy || "";
  $("blocker-note").hidden = !blocker;
  if (blocker) {
    $("blocker-title").textContent = blocker;
    // ⚠️ 是 textContent 不是 innerHTML：这段文案来自跑批产物，当数据不当标记
    $("blocker-copy").textContent = blockerCopy;
  }
  return audit;
}

function announceViewerReady(entry, status) {
  if (window.parent === window) return;
  window.parent.postMessage({
    schema: "assembly-scene-viewer-message/v1",
    type: "assembly-scene-viewer-ready",
    caseId: entry.id,
    catalog: state.index?.catalog?.id || "",
    status,
  }, '*');
}

async function loadCase(index) {
  const entry = state.index?.cases?.[index];
  if (!entry) return;
  const token = ++state.token;
  state.caseIndex = index;
  renderCaseList();
  setCurtain("loading", "LOADING PARTS");
  setStatus("loading", "LOADING");

  try {
    const scene = await readResource(entry.sceneUrl);
    if (token !== state.token) return;

    disposeModel();
    disposeCompare();
    state.scene = scene;
    const loadedModel = await buildModel(scene, token);
    if (token !== state.token) { disposeRoot(loadedModel.root); return; }
    state.model = loadedModel;

    world.add(state.model.root);
    groundModel();
    resize();
    fitView();

    // 对照层：有 compare 才出模式条；换案一律回到"当前"档
    const compare = scene.compare || null;
    state.mode = "a8";
    $("mode-switch").hidden = !compare;
    if (compare) {
      $("mode-compare-name").textContent = String(compare.mode || "a2").toUpperCase();
      $("mode-compare-caption").textContent = compare.label || "对照";
      // 主按钮写**本案自己**是哪一侧，不能想当然 —— 一个 _src 案的主按钮写
      // "切割后"，就跟它的对照按钮撞成一模一样，两个按钮看不出区别。
      $("mode-main-name").textContent = String(compare.self?.mode || "a8").toUpperCase();
      $("mode-main-caption").textContent = compare.self?.label || "当前";
    }
    applyModeVisibility();

    $("case-title").title = entry.id;  // 案名是人读的，case id 是拿去贴命令的
    const missing = state.model.missing || [];
    // 缺一件不炸整案是对的；**缺光了还静默就错了** —— 那会让人对着一个空舞台
    // 找半天，而真相是几何一个都没取到（软链被守卫挡掉时就是这个症状）。
    if (missing.length && missing.length === (scene.parts || []).length) {
      throw new Error(
        `全部 ${missing.length} 个部件都加载失败 —— 检查几何是否可取（看控制台的逐件报错）`
      );
    }
    document.title = `${scene.title || entry.id} · Scene Viewer`;

    // 图层按数据亮灭：没有可动关节就不出 Completion hypothesis 和相位条
    const hasMotion = state.model.movable.length > 0;
    if (!hasMotion) { state.axesOn = false; $("completion-toggle").checked = false; }
    syncLayerAvailability();
    $("pose-deck").hidden = !hasMotion;
    setPlaying(false);
    // 两端语义：清单里声明了就照写（0=收合 / 1=拟合位），没有就退成 0 / 1
    const semantics = scene.provenance?.poseSemantics || {};
    // 两端标签是 6px 的角标，塞得下的只有一个词；全文挂 title。
    const endLabel = (raw, fallback) => {
      const text = String(raw || "").trim();
      if (!text) return fallback;
      return text.split(/\s*[—–-]\s*/)[0].slice(0, 16);
    };
    $("phase-lo").textContent = endLabel(semantics["0"], "Q0");
    $("phase-lo").title = String(semantics["0"] || "");
    $("phase-hi").textContent = endLabel(semantics["1"], "Q1");
    $("phase-hi").title = String(semantics["1"] || "");

    layoutStage();
    applyExplode(state.explode);
    if (state.labelsOn) { ensureSprites(); prepareExplode(); }
    refreshAppearance();
    if (state.axesOn) showAxes(); else clearAxes();
    renderInspector();
    // 深链带 pose 时用它做初始姿态（只认第一次，之后由用户拖动接管）
    const wantedPose = state.pendingPose;
    state.pendingPose = null;
    if (hasMotion) applyPhase(wantedPose == null ? 0 : wantedPose);
    renderRefs();
    const audit = renderFacts(scene, entry, missing);
    renderModeContext();
    syncUrl();
    setCurtain("hidden", "");
    // 上游跑批的结论优先；本地缺件只能把它降级，不能把 blocked 抬成 ready
    let viewerStatus = "ready";
    if (missing.length) {
      viewerStatus = "partial";
      setStatus("provisional", "PARTIAL");
    } else if (audit.status === "blocked") {
      viewerStatus = "blocked";
      setStatus("blocked", "A8 BLOCKED");
    } else if (audit.status === "provisional") {
      viewerStatus = "provisional";
      setStatus("provisional", "PROVISIONAL");
    } else {
      setStatus("ready", "READY");
    }
    state.caseStatus.set(entry.id, audit.status || "");
    renderCaseList();
    announceViewerReady(entry, viewerStatus);
  } catch (error) {
    if (token !== state.token) return;
    console.error(error);
    setCurtain("error", error?.message || String(error));
    setStatus("blocked", "BLOCKED");
  }
}

function syncUrl() {
  if (location.protocol === 'about:' || location.protocol === 'file:') return;
  const entry = state.index?.cases?.[state.caseIndex];
  if (!entry) return;
  const params = new URLSearchParams(location.search);
  params.set("case", entry.id);
  const catalogId = state.index?.catalog?.id;
  if (catalogId) params.set("catalog", catalogId);
  // 跟 a8 一样把姿态写进 URL —— 审阅时"你看这个角度"要能贴给别人
  if (state.model?.movable.length) params.set("pose", state.phase.toFixed(3));
  else params.delete("pose");
  if (state.mode !== "a8") params.set("mode", state.mode);
  else params.delete("mode");
  history.replaceState(null, "", `${location.pathname}?${params}`);
}

function navigate(direction) {
  const total = state.index?.cases?.length || 0;
  if (!total) return;
  loadCase((state.caseIndex + direction + total) % total);
}

function resize() {
  state.lastFrame = 0;
  loop?.resize();
}

/* ── 事件绑定 ────────────────────────────────────────────────── */

const narrowPanel = matchMedia('(max-width:760px)');
function setInspectorCollapsed(value) {
  document.querySelector('.audit-panel').classList.toggle('is-collapsed', value);
  $('inspector-toggle').setAttribute('aria-expanded', String(!value));
}
narrowPanel.addEventListener('change', () => setInspectorCollapsed(narrowPanel.matches));
setInspectorCollapsed(narrowPanel.matches);
$('inspector-toggle').addEventListener('click', () => setInspectorCollapsed($('inspector-toggle').getAttribute('aria-expanded') === 'true'));

$("fit-view").addEventListener("click", fitView);

/* INSPECTION LAYERS —— a8 的语义：并列的叠加层，不是互斥的模式。
 * 旧版把 X-ray / 原材质 藏在"编号"开关背后，等于把三层拧成一个模式选择器，
 * 想"原材质 + X-ray 看内腔"就做不到。 */
$("source-toggle").addEventListener("change", (event) => {
  state.sourceOn = event.currentTarget.checked;
  applySourceVisibility();
});

$("completion-toggle").addEventListener("change", (event) => {
  state.axesOn = event.currentTarget.checked;
  if (state.axesOn) showAxes(); else clearAxes();
});

$("label-toggle").addEventListener("change", (event) => {
  state.labelsOn = event.currentTarget.checked;
  if (state.labelsOn) { ensureSprites(); prepareExplode(); }
  else { state.selectedPart = null; }
  syncLayerAvailability();
  refreshAppearance();
  renderInspector();
});

$("audit-toggle").addEventListener("change", (event) => {
  state.xrayOn = event.currentTarget.checked;
  refreshAppearance();
});

$("wire-toggle").addEventListener("change", (event) => {
  state.wireframeOn = event.currentTarget.checked;
  refreshAppearance();
});

$("texture-toggle").addEventListener("change", (event) => {
  state.originalMaterialsOn = event.currentTarget.checked;
  refreshAppearance();
});

$("explode").addEventListener("input", (event) => applyExplode(Number(event.currentTarget.value)));

$("pose-slider").addEventListener("input", (event) => {
  setPlaying(false);
  applyPhase(Number(event.currentTarget.value));
});
$("pose-slider").addEventListener("change", syncUrl);
$("play-toggle").addEventListener("click", () => setPlaying(!state.playing));

for (const button of document.querySelectorAll("#mode-switch [data-mode]")) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}

$("curation-export").addEventListener("click", exportCuration);

document.addEventListener("keydown", (event) => {
  // 只避让**文本录入**。range 滑杆拖完焦点会留在 <input> 上，若一律避让，
  // 那之后按 G/B 会被静默吃掉 —— 审阅时最常见的动作序列正是"拖完滑杆就下判断"。
  const target = event.target;
  const tag = target?.tagName;
  const typing = tag === "TEXTAREA"
    || target?.isContentEditable
    || (tag === "INPUT" && target.type !== "range" && target.type !== "checkbox");
  if (typing) return;
  if (event.key === "ArrowDown") { event.preventDefault(); navigate(1); }
  if (event.key === "ArrowUp") { event.preventDefault(); navigate(-1); }
  const entry = state.index?.cases?.[state.caseIndex];
  if (!entry) return;
  if (event.key === " ") { event.preventDefault(); setPlaying(!state.playing); }
  // 1/2/3 切对照档，跟 ↑↓ 一样是单键 —— 对读时手不用离开键盘
  if (event.key === "1") setMode("a8");
  if (event.key === "2") setMode("a2");
  if (event.key === "3") setMode("split");
  if (event.key === "g" || event.key === "G") setClassification(entry, "golden");
  if (event.key === "b" || event.key === "B") setClassification(entry, "typical_bad");
});

$("reference-toggle").addEventListener("click", () => {
  $("evidence-card").classList.toggle("is-expanded");
  // 展开/收起有 220ms 过渡，量早了拿到的是旧高度
  setTimeout(syncEvidenceHeight, 260);
});

addEventListener("resize", syncEvidenceHeight);

new ResizeObserver(resize).observe(stage);

function render({ resize: sizeChanged }) {
  if (sizeChanged) { resizeDrawingBuffer(renderer, camera, stage, false); viewportFrame?.apply(); }
  const now = performance.now();
  if (state.playing) {
    // 按真实时间推进（不按帧数），掉帧时速度才不变
    const delta = state.lastFrame ? Math.min((now - state.lastFrame) / 1000, 0.1) : 0;
    state.lastFrame = now;
    const step = advancePhase(state.phase, state.phaseDir, delta);
    state.phaseDir = step.direction;
    applyPhase(step.phase);
  }
  const moving = controls.update();
  renderer.render(world, camera);
  return state.playing || moving;
}
loop = new RenderLoop(render);
$('app').classList.add('v04-stage');
$('case-rail').classList.add('float-card', 'v04-library');
document.querySelector('.audit-panel').classList.add('float-card');
viewportFrame = new ViewportFrame(stage, camera, () => {
  if (!userMoved) fitView();
  invalidate();
}, { top: 80, bottom: 130 });
controls.addEventListener('change', invalidate);
// Model changes, checkbox layers and async comparison completion all invalidate.
for (const event of ['input', 'change', 'click', 'keydown']) document.addEventListener(event, invalidate);
new MutationObserver(invalidate).observe($('loading-curtain'), { attributes: true, childList: true, subtree: true });
document.addEventListener('visibilitychange', () => { state.lastFrame = 0; loop.setActive(!document.hidden); });
loop.resize();

/* 目录加载。切目录 = 重取索引 + 重建案列，不是刷新整页 —— 刷新会把
 * 相位、炸开、图层开关全丢掉。 */
async function loadIndex(catalogId) {
  // 相对挂载点取：本地 serve 挂在 /，产品侧挂在 /api/studio/viewer/ ——
  // 写成根绝对路径的话，同一份文件只能在其中一边活。
  state.index = await readResource('api/index.json');
  const curationDisabled = state.index.curationEnabled === false;
  $('app').dataset.curation = curationDisabled ? 'disabled' : 'enabled';
  document.querySelector('.review-session').textContent = curationDisabled
    ? '模型原始结果 · 评价请在工作台下方提交'
    : 'G/B 标记仅在本次预览中，导出 JSON 保存 · 原数据只读';

  const catalog = state.index.catalog || {};
  $("catalog-kind").textContent = String(catalog.kind || "index").toUpperCase();
  const select = $("catalog-title");
  select.replaceChildren();
  for (const item of catalog.available || [{ id: catalog.id, title: state.index.title, count: (state.index.cases || []).length }]) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.title}（${item.count}）`;
    select.append(option);
  }
  select.value = catalog.id || "";
  select.disabled = (catalog.available || []).length < 2;
  // 挂了 registry 才是跨机器持久的；没挂要说出来，别让人以为标了就存住了
  $("curation-export").title = catalog.writable
    ? "导出人工决定（标记已直接写进 registry）"
    : "标记仅在本次预览中；导出 JSON 保存，重新打开会清空。不会修改原 registry。";

  renderCaseList();
  const empty = (state.index.cases || []).length === 0;
  if (empty) {
    disposeModel();
    disposeCompare();
    setCurtain("error", `${state.index.title}：这个目录里还没有案子`);
    return;
  }
  const wanted = new URLSearchParams(location.search).get("case");
  const start = Math.max(0, (state.index.cases || []).findIndex((c) => c.id === wanted));
  await loadCase(start);
}

$("catalog-title").addEventListener("change", async (event) => {
  const catalogId = event.currentTarget.value;
  const params = new URLSearchParams(location.search);
  params.set("catalog", catalogId);
  params.delete("case");
  history.replaceState(null, "", `${location.pathname}?${params}`);
  try {
    await loadIndex(catalogId);
  } catch (error) {
    setCurtain("error", error?.message || String(error));
  }
});

(async function initialise() {
  try {
    const query = new URLSearchParams(location.search);
    const pose = Number(query.get("pose"));
    state.pendingPose = Number.isFinite(pose) && query.has("pose") ? pose : null;
    state.pendingMode = ["a2", "split"].includes(query.get("mode")) ? query.get("mode") : null;
    await loadIndex(query.get("catalog") || "");
    if (state.pendingMode) { const mode = state.pendingMode; state.pendingMode = null; await setMode(mode); }
  } catch (error) {
    setCurtain("error", error?.message || String(error));
    setStatus("blocked", "BLOCKED");
  }
})();

// 自动化核验钩子（跟 hackday viewer 同名同语义，便于两边共用检查脚本）
window.__VIEWER_AUDIT__ = {
  // 跟 hackday viewer 的钩子保持同名同语义，两边共用检查脚本
  three: { world, camera, renderer, controls, THREE },
  get root() { return state.model?.root || null; },
  get bounds() {
    const box = modelBounds();
    if (!box || box.isEmpty()) return null;
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    return {
      min: box.min.toArray(), max: box.max.toArray(),
      size: size.toArray(), center: center.toArray(),
    };
  },
  get scene() { return state.scene; },
  get partCount() { return (state.scene?.parts || []).length; },
  get dof() { return state.model?.movable.length || 0; },
  get partLabelCount() { return state.partSprites.length; },
  get axisCount() { return state.axisHelpers.length; },
  get explode() { return state.explode; },
  get mode() { return state.mode; },
  get compareRoot() { return state.compareModel?.root || null; },
  get comparePartCount() { return (state.compareScene?.parts || []).length; },
  setMode,
  get sourceSkin() { return state.sourceOn; },
  get wireframe() { return state.wireframeOn; },
  get phase() { return state.phase; },
  get playing() { return state.playing; },
  advancePhase,
  easedPhase,
  jointValueAtPhase(name, phase) {
    const joint = (state.model?.movable || []).find((j) => j.name === name);
    return joint ? jointValueAtPhase(joint, phase) : null;
  },
  get caseId() { return state.index?.cases?.[state.caseIndex]?.id || ""; },
  get curationExport() { return buildCurationExport(); },
  decisionOf(id) {
    const entry = (state.index?.cases || []).find((c) => c.id === id);
    return entry ? decisionOf(entry) : null;
  },
};
