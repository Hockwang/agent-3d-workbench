import * as THREE from 'three';

// PKF 参数 id 必须是合法 JS 标识符（REVIEW-v15 F4）
// 理由：
//   1. evaluatePkfFormula 用 /[a-zA-Z_]\w*/g 提取公式里的标识符做白名单校验，
//      带空格/连字符/点号的 id 在公式里会被拆成多个不可识别的 token → 求值永远报错
//   2. updatePkfParameter 改名时用 new RegExp(`\\b${id}\\b`) 做公式里的替换，
//      id 含正则元字符（*、[、(、?、. 等）会让 RegExp 抛 SyntaxError 或匹配错
// 只接受 /^[a-zA-Z_][a-zA-Z0-9_]*$/（和 JS 变量名规则一致）
export const PKF_ID_VALID_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function normalizeValue(raw, fallback = 0) {
  const next = Number(raw);
  return Number.isFinite(next) ? next : fallback;
}

// UI uses Z-up convention; Three.js runtime is Y-up.
function mapUiAxisToWorld(axis) {
  if (axis === 'z') return 'y';
  if (axis === 'y') return 'z';
  return 'x';
}

export class KeyframeManager {
  constructor() {
    this.currentTime = 0;
    // objectDataById：对象元数据。仅保留 baseTransform（被 jointDef baseTransform 兜底用）。
    // 不再有 per-object clips。
    this.objectDataById = new Map();
    /** Map<nodeUuid, {id, name, type, axis, limits:{min,max}, parentId, childId, currentValue, baseTransform}> */
    this.jointDefinitions = new Map();

    // ── 全局关键帧系统 ──
    // 项目级动画片段，所有关节共享同一时间线。每个 clip 包含：
    //   - clipName: 片段名（"default" / "open" / "close" 等）
    //   - duration: 片段时长（秒）
    //   - keyframes: 全局关键帧数组，每个 keyframe 是 { time, jointValues: { [jointDefId]: number } }
    //     一个 keyframe 同时记录多个关节在该时刻的状态，回放时所有关节同步插值
    /** @type {Map<string, {clipName:string, duration:number, keyframes:Array<{time:number, jointValues:Object<string,number>}>}>} */
    this.globalClips = new Map();
    this.globalClips.set('default', { clipName: 'default', duration: 10, keyframes: [], reparentEvents: [] });
    this.activeClipName = 'default';

    // ── PKF（参数化关键帧公式）数据容器 ──
    // 参数声明表：每个参数有 id（唯一标识）、type（number/vec3）、unit（单位）、desc（描述）、default（默认值）
    /** @type {Map<string, {id:string, type:string, unit:string, desc:string, default:*}>} */
    this.pkfParameters = new Map();
    // 步骤列表：每个步骤关联一个关节，定义通道/轴向/时间区间/起止公式/缓动
    /** @type {Array<{id:string, joint:string, joint_def_id:string, channel:string, axis:string, t_start:number, t_end:number, value_start:string, value_end:string, easing:string}>} */
    this.pkfSteps = [];

    // ── Reparent 事件系统（schema v5）──
    // 记录模型加载时每个对象的初始 scene graph parent（by name），循环回 t=0 时还原用。
    // Map<child_name, original_parent_name | null>
    this.originalParentMap = new Map();

    // ── 场景标记系统（schema v6）──
    // 用户在场景里加的辅助物：货物占位 / 取货点 / 放货点。独立于关节系统。
    // Marker 也作为 Three.js 对象出现在 sceneRoot 下，参与 reparent / 选中 / 编辑流程。
    // metadata（type/size/color）单独存这里，对应 scene 里的 Object3D 通过 name 查找。
    /** @type {Map<string, {id, name, type, size?, color?}>} */
    this.sceneMarkers = new Map();

    // ── 模板路径标记（mvp3 / forklift-pickup-template）──
    // 非空时表示当前 PKF 由叉车模板编译生成；applyReparentEventsAtTime 据此禁用 snap-attach
    // 强制位置对齐（因为模板本身保证了 fork/cargo 几何连续）。
    // 结构：{ template_version: number, rhythm_name?: string, total_duration?: number }
    this._pkfTemplateMeta = null;
  }

  reset() {
    this.currentTime = 0;
    this.objectDataById.clear();
    this.jointDefinitions.clear();
    this.globalClips.clear();
    this.globalClips.set('default', { clipName: 'default', duration: 10, keyframes: [], reparentEvents: [] });
    this.activeClipName = 'default';
    this.pkfParameters.clear();  // 清空 PKF 参数
    this.pkfSteps = [];           // 清空 PKF 步骤
    this.originalParentMap.clear(); // 清空初始 parent 快照
    this.sceneMarkers.clear();      // 清空场景标记
    this._pkfTemplateMeta = null;   // 清空模板标记
  }

  // ══════════════════════════════════════════════════════════════
  //  场景标记系统（schema v6）
  // ══════════════════════════════════════════════════════════════

  /**
   * 添加 marker
   * @param {Object} opts - { name, type, size?, color? }
   * @returns {Object} 创建的 marker 数据
   */
  addMarker({ name, type, size, color }) {
    const id = `mk_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e4)}`;
    const marker = {
      id,
      name: String(name || `${type}_${this.sceneMarkers.size + 1}`),
      type, // 'cargo' | 'pickup' | 'drop'
      size: type === 'cargo' ? (size || { w: 0.5, h: 0.5, d: 0.5 }) : null,
      color: color || null,
    };
    this.sceneMarkers.set(id, marker);
    return marker;
  }

  removeMarker(id) {
    return this.sceneMarkers.delete(id);
  }

  removeMarkerByName(name) {
    for (const [id, m] of this.sceneMarkers) {
      if (m.name === name) {
        this.sceneMarkers.delete(id);
        return true;
      }
    }
    return false;
  }

  getMarker(id) {
    return this.sceneMarkers.get(id);
  }

  getMarkerByName(name) {
    for (const m of this.sceneMarkers.values()) {
      if (m.name === name) return m;
    }
    return null;
  }

  getAllMarkers() {
    return [...this.sceneMarkers.values()];
  }

  updateMarker(id, patch) {
    const m = this.sceneMarkers.get(id);
    if (!m) return null;
    if (typeof patch.name !== 'undefined') m.name = String(patch.name);
    if (patch.size && m.type === 'cargo') {
      if (typeof patch.size.w !== 'undefined') m.size.w = Number(patch.size.w) || 0;
      if (typeof patch.size.h !== 'undefined') m.size.h = Number(patch.size.h) || 0;
      if (typeof patch.size.d !== 'undefined') m.size.d = Number(patch.size.d) || 0;
    }
    if (typeof patch.color !== 'undefined') m.color = patch.color;
    return m;
  }

  /**
   * 获取 cargo marker 的尺寸参数（注入到 PKF 公式求值器）
   * 当前简化：只取第一个 cargo marker 的尺寸作为 cargo_width / cargo_height / cargo_depth
   * 多 cargo 场景需要扩展（按 marker name 区分）
   */
  getCargoSizeParams() {
    for (const m of this.sceneMarkers.values()) {
      if (m.type === 'cargo' && m.size) {
        return {
          cargo_width: m.size.w,
          cargo_height: m.size.h,
          cargo_depth: m.size.d,
        };
      }
    }
    return {};
  }

  /**
   * F13：算 fork_anchor_zero 的"输入签名"，用于 hash-based cache 自动失效。
   * 签名包含：
   *   (1) reparent events 序列化（t / child_name / new_parent_name）
   *   (2) attach target joint 的所有 mesh 后代 uuid（检测子树增删 / reparent）
   * 任一输入变 → hash 变 → 下次 compute 自动重算。
   * 比显式 invalidateForkAnchorZero 覆盖面更广（叉齿子树结构变化 / roundtrip 重载 / undo 跨步 都自动命中）。
   * @private
   */
  _computeForkAnchorInputsHash(sceneRoot) {
    const events = this.getActiveGlobalClip()?.reparentEvents || [];
    const eventSig = events.map((e) => `${e.t}:${e.child_name}:${e.new_parent_name}`).join('|');
    const attachEvent = events.find((e) => e.new_parent_name);
    let meshSig = '';
    if (attachEvent && sceneRoot) {
      const forkObj = sceneRoot.getObjectByName(attachEvent.new_parent_name);
      if (forkObj) {
        const uuids = [];
        forkObj.traverse((o) => { if (o.isMesh) uuids.push(o.uuid); });
        meshSig = uuids.sort().join(',');
      }
    }
    return `${eventSig}||${meshSig}`;
  }

  /**
   * v14.1（#37 ~ #52）：算叉齿"承载锚点"在**零位**时的世界坐标。
   *
   * 语义历程（六轮迭代）：
   *   - #37 初版：bbox.getCenter() → cargo 陷进 fork ~h/2 米
   *   - #47 尝试：bbox.max.y 做"顶面"→ 合并 mesh 下 max.y 指向门架顶 → 穿地
   *   - #48 回退 center
   *   - #49：y 改 bbox.min.y
   *   - #50：forward-extreme（x/z 朝 cargo 方向推）
   *   - #51 误入歧途：读 joint origin —— 但 origin 是**旋转支点**，不能挪（会破坏关节旋转行为）
   *   - **#52 当前**：自动算 bbox 底面中心（center.x, min.y, center.z）—— 和"子对象底部"按钮**同公式**，
   *     但**不写进** def.origin，只用于 PKF / snap 内部计算。保留 joint origin 作为旋转支点
   *
   * 语义（#52）：
   *   anchor = (bbox.center.x, bbox.min.y, bbox.center.z)（threejs Y-up）
   *   = "子对象底部"按钮会算出来的那个点（但只用不写）
   *
   * 不使用 joint.origin（#51 的教训：origin 有自己的用途 —— 旋转支点 / URDF 关节原点）。
   *
   * 用途：AI 生成 PKF 时写公式：
   *   - 车体前进 y：`cargo_pos_y - fork_anchor_zero_y - approach_gap`
   *   - 车体横移 x：`cargo_pos_x - fork_anchor_zero_x`
   *   - 门架升降 z：`cargo_pos_z - cargo_height/2 - fork_anchor_zero_z`
   *     （cargo 底面中心对齐叉齿前端底面中心；snap-attach 复用缓存 forward 方向，零 teleport）
   * 因为 runtime 的 prismatic `currentValue` 是**位移**（加到 baseWorldPos 上），
   * 所以公式应该算"要从零位挪到目标的位移"，即：
   *   displacement = target_world - anchor_at_zero - gap
   * 之前用 fork_offset（关节间差）是错的，公式被 runtime 当位移 → double offset（见 #37）。
   *
   * ⚠️ 调用时机：**必须在所有关节 currentValue=0 时**才能得到真零位锚点。
   *    main.js 的 🚀 handler 负责临时归零 → 调本函数 → 恢复。
   *    此处不主动归零（避免破坏当前动画状态）。
   *
   * 缓存：结果存 `_forkAnchorZeroCached`，输入签名存 `_forkAnchorHash`（F13）。
   *   后续调用时若输入 hash 未变 → 直接返回缓存（即使 joint 位置在动）。
   *   hash 变了（event 增删 / 叉齿子树结构变）→ 重新计算。
   *   `invalidateForkAnchorZero()` 仍保留作显式清除手段（设为 null 强制重算）。
   *
   * @param {THREE.Object3D} sceneRoot
   * @returns {Object} {} 或 { fork_anchor_zero_x, fork_anchor_zero_y, fork_anchor_zero_z }
   */
  computeForkAnchorZero(sceneRoot) {
    if (!sceneRoot) return {};
    const clip = this.getActiveGlobalClip();
    const events = clip?.reparentEvents || [];
    const attachEvent = events.find((e) => e.new_parent_name);
    if (!attachEvent) return {};

    // F13: 先查 hash，没变就直接返回缓存
    const hash = this._computeForkAnchorInputsHash(sceneRoot);
    if (this._forkAnchorZeroCached && this._forkAnchorHash === hash) {
      return this._forkAnchorZeroCached;
    }

    const forkObj = sceneRoot.getObjectByName(attachEvent.new_parent_name);
    if (!forkObj) return {};

    sceneRoot.updateMatrixWorld(true);

    // #52：自动算 forkObj 的 bbox 底面中心（和 UI "子对象底部"按钮 同公式，但只用不写 def.origin）
    // 等价于：auto click "子对象底部" button internally，joint origin（旋转支点）不受影响
    const box = new THREE.Box3().setFromObject(forkObj);
    if (box.isEmpty()) return {};
    const center = box.getCenter(new THREE.Vector3());
    // anchor = (center.x, min.y, center.z) threejs
    const result = {
      fork_anchor_zero_x: +center.x.toFixed(3),
      fork_anchor_zero_y: +center.z.toFixed(3), // threejs z = UI y(前后)
      fork_anchor_zero_z: +box.min.y.toFixed(3), // threejs min.y = UI z(底面)
    };
    this._forkAnchorZeroCached = result;
    this._forkAnchorHash = hash;
    return result;
  }

  /**
   * 返回 computeForkAnchorZero 缓存值（给 buildDefaultParamValues 用，不触发重算）。
   * 未缓存 → 空对象（AI 退化用 approach_gap 老路）。
   */
  getForkAnchorZero() {
    return this._forkAnchorZeroCached || {};
  }

  /**
   * 清掉 fork_anchor_zero 缓存（显式清除手段）。
   * F13 加了 hash 自动失效后，大多数情况不需要手动调——但保留作兜底 API。
   * 调用点：addReparentEvent / removeReparentEvent / removeAllReparentEventsForChild。
   */
  invalidateForkAnchorZero() {
    this._forkAnchorZeroCached = null;
    this._forkAnchorHash = null;
  }

  // ══════════════════════════════════════════════════════════════
  //  Reparent 事件系统（schema v5）
  // ══════════════════════════════════════════════════════════════

  /**
   * 快照所有命名对象的初始 scene graph parent name。
   * 加载模型后调一次，循环回 t=0 时把 reparented 对象还原用。
   * @param {THREE.Object3D} root
   */
  snapshotOriginalParents(root) {
    this.originalParentMap.clear();
    this.originalWorldTransforms = this.originalWorldTransforms || new Map();
    this.originalWorldTransforms.clear();
    if (!root) return;
    root.updateMatrixWorld(true);
    root.traverse((obj) => {
      if (obj.name && obj.parent) {
        // 只记录命名对象；parent 也只记 name（无 name 的 parent 记为 null = sceneRoot 语义）
        this.originalParentMap.set(obj.name, obj.parent.name || null);
        // 同时快照世界变换：循环回 t=0 时 reparented 对象还要回到原位
        // 修的 bug：cargo 放下后卡在 drop 位置，第 2 轮不会自己回 spawn
        this.originalWorldTransforms.set(obj.name, {
          pos: obj.getWorldPosition(new THREE.Vector3()),
          quat: obj.getWorldQuaternion(new THREE.Quaternion()),
          scale: obj.getWorldScale(new THREE.Vector3()),
        });
      }
    });
  }

  /**
   * 给当前 clip 增加一个 reparent 事件
   * @param {number} t - 时间点（秒）
   * @param {string} childName - 子对象名字
   * @param {string|null} newParentName - 新父级名字，null = 挂回世界根
   * @returns {string} event_id
   */
  addReparentEvent(t, childName, newParentName) {
    const clip = this.getActiveGlobalClip();
    if (!clip) return null;
    if (!clip.reparentEvents) clip.reparentEvents = [];
    const id = `rev_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e4)}`;
    clip.reparentEvents.push({
      event_id: id,
      t: Number(t) || 0,
      child_name: String(childName || ''),
      new_parent_name: newParentName === null || newParentName === undefined ? null : String(newParentName),
    });
    // 按 t 升序排序，应用时从 t=0 顺序累积
    clip.reparentEvents.sort((a, b) => a.t - b.t);
    this.invalidateForkAnchorZero(); // #37: events 变了，fork anchor 可能变，强制下次重算
    return id;
  }

  /** 删除一个 reparent 事件 */
  removeReparentEvent(eventId) {
    const clip = this.getActiveGlobalClip();
    if (!clip?.reparentEvents) return false;
    const before = clip.reparentEvents.length;
    clip.reparentEvents = clip.reparentEvents.filter((e) => e.event_id !== eventId);
    const changed = clip.reparentEvents.length !== before;
    if (changed) this.invalidateForkAnchorZero();
    return changed;
  }

  /** 删除某个对象的所有 reparent 事件 */
  removeAllReparentEventsForChild(childName) {
    const clip = this.getActiveGlobalClip();
    if (!clip?.reparentEvents) return 0;
    const before = clip.reparentEvents.length;
    clip.reparentEvents = clip.reparentEvents.filter((e) => e.child_name !== childName);
    const removed = before - clip.reparentEvents.length;
    // #39: events 变了必须失效缓存，否则 PKF 预览继续读旧 fork_anchor_zero
    if (removed > 0) this.invalidateForkAnchorZero();
    return removed;
  }

  /** 获取当前 clip 所有 reparent 事件（浅拷贝） */
  getReparentEvents() {
    const clip = this.getActiveGlobalClip();
    return clip?.reparentEvents ? [...clip.reparentEvents] : [];
  }

  /**
   * 在时间 t 应用 reparent 事件到 scene graph
   *
   * 算法：从 t=0 沿事件列表累积，得出每个 child 在时间 t "应该处于"的 parent。
   * 然后和实际 scene graph 对比，用 Three.js 的 Object3D.attach() 切换
   * （attach 会自动保持世界变换不变）。
   *
   * 关键设计：状态由 t=0 累积而不是"处理 delta"——seek 到任意时间都正确。
   *
   * @param {number} t - 目标时间（秒）
   * @param {THREE.Object3D} root - sceneRoot
   */
  applyReparentEventsAtTime(t, root) {
    if (!root) return;
    const clip = this.getActiveGlobalClip();
    const events = clip?.reparentEvents || [];

    // 建 name → object 索引
    const nameMap = new Map();
    root.traverse((obj) => { if (obj.name) nameMap.set(obj.name, obj); });

    // 计算"在时间 t，每个被 reparent 过的 child 应该挂谁下面"
    // 初始状态：所有 child 在其 originalParent 下（由 snapshotOriginalParents 记录）
    const targetState = new Map(); // child_name → parent_name (null = sceneRoot)

    // 哪些 child 被事件涉及过 → 初始化为 originalParent
    const touchedChildren = new Set();
    const firstEventTime = new Map(); // child → 它最早一个事件的 t
    for (const ev of events) {
      touchedChildren.add(ev.child_name);
      if (!firstEventTime.has(ev.child_name)) {
        firstEventTime.set(ev.child_name, ev.t);
      }
    }
    for (const childName of touchedChildren) {
      targetState.set(childName, this.originalParentMap.get(childName) ?? null);
    }

    // 按 t 升序累积（events 已经排序）
    for (const ev of events) {
      if (ev.t > t + 1e-6) break; // 未到时间
      targetState.set(ev.child_name, ev.new_parent_name);
    }

    // 查 marker 类型的辅助（用于 snap-attach）
    const findMarkerMeta = (name) => {
      for (const meta of this.sceneMarkers.values()) {
        if (meta.name === name) return meta;
      }
      return null;
    };

    // 应用 diff：如果实际 parent !== target parent，attach 切换
    for (const [childName, targetParentName] of targetState) {
      const child = nameMap.get(childName);
      if (!child) continue;
      const targetParent = targetParentName ? (nameMap.get(targetParentName) || root) : root;
      const parentChanged = child.parent !== targetParent;

      // Snap-attach（#36 ~ #52）：cargo 底面中心对齐 fork bbox 底面中心。
      // #52：和 computeForkAnchorZero 同公式 —— bbox.center.x/z + bbox.min.y，自动算（不读 joint origin）
      // ⚠️ #50d：bbox 计算**必须在 attach 之前**，否则 setFromObject 会包含刚 attach 上的 cargo
      //
      // 模板路径分流（forklift-pickup-template §5.4）：
      //   当前 PKF 带 _pkfTemplateMeta 时，attach 由模板保证几何连续（fork 和 cargo 在 attach 前后位置关系已正确），
      //   靠 Three.js 原生 parent.attach(child) 保持世界坐标，不需要强制位置对齐。
      //   走此分支则不算 desiredWorldPos（下面 snap 写入段自然跳过）。
      let desiredWorldPos = null;
      const inTemplateMode = !!this._pkfTemplateMeta;
      if (!inTemplateMode && parentChanged && targetParent !== root) {
        const markerMeta = findMarkerMeta(childName);
        if (markerMeta?.type === 'cargo') {
          targetParent.updateMatrixWorld(true);
          const cargoHalfHeight = (markerMeta.size?.h ?? 0) / 2;
          const box = new THREE.Box3().setFromObject(targetParent);
          if (!box.isEmpty()) {
            const bboxCenter = box.getCenter(new THREE.Vector3());
            // cargo 中心 = bbox 底面中心 + cargoH/2（让 cargo 底贴 fork 底）
            desiredWorldPos = new THREE.Vector3(
              bboxCenter.x,
              box.min.y + cargoHalfHeight,
              bboxCenter.z,
            );
          } else {
            desiredWorldPos = targetParent.getWorldPosition(new THREE.Vector3());
          }
        }
      }

      // 算好目标位置后再 attach（保持世界变换）
      if (parentChanged) {
        targetParent.attach(child);
      }

      // 应用 snap（attach 之后写 local position 到 child）
      if (desiredWorldPos) {
        const localPos = targetParent.worldToLocal(desiredWorldPos.clone());
        child.position.copy(localPos);
        child.quaternion.identity();
        const parentWorldScale = targetParent.getWorldScale(new THREE.Vector3());
        child.scale.set(
          1 / (parentWorldScale.x || 1),
          1 / (parentWorldScale.y || 1),
          1 / (parentWorldScale.z || 1),
        );
      }
      // 循环边界修复：如果当前时间早于该 child 的第一个事件，
      // 把 child 重置到原始世界变换（否则循环回来 cargo 会卡在 drop 位置）
      const firstT = firstEventTime.get(childName);
      const snap = this.originalWorldTransforms?.get(childName);
      if (firstT !== undefined && t + 1e-6 < firstT && snap && child.parent) {
        child.parent.updateMatrixWorld(true);
        const localPos = child.parent.worldToLocal(snap.pos.clone());
        child.position.copy(localPos);
        const parentWorldQuat = child.parent.getWorldQuaternion(new THREE.Quaternion());
        const localQuat = parentWorldQuat.invert().multiply(snap.quat);
        child.quaternion.copy(localQuat);
        // 还原 scale：compensate parent world scale 让 child.world.scale = snap.scale
        if (snap.scale) {
          const parentWS = child.parent.getWorldScale(new THREE.Vector3());
          child.scale.set(
            snap.scale.x / (parentWS.x || 1),
            snap.scale.y / (parentWS.y || 1),
            snap.scale.z / (parentWS.z || 1),
          );
        }
      }
    }
  }

  /**
   * 确保对象有 objectData 记录（仅保留 baseTransform）
   * 主要用途：作为 jointDef.baseTransform 的兜底（当关节定义没有自己的零点时）
   * @param {THREE.Object3D} object
   */
  ensureObjectData(object) {
    if (!object) return null;
    const current = this.objectDataById.get(object.uuid);
    if (current) {
      current.objectName = object.name || '(unnamed)';
      return current;
    }
    const created = {
      objectId: object.uuid,
      objectName: object.name || '(unnamed)',
      baseTransform: {
        tx: object.position.x,
        ty: object.position.y,
        tz: object.position.z,
        rx: object.rotation.x,
        ry: object.rotation.y,
        rz: object.rotation.z,
      },
    };
    this.objectDataById.set(object.uuid, created);
    return created;
  }

  // ── Joint Definition CRUD (layer-tree joint type per node) ──

  getJointDef(nodeId) {
    return this.jointDefinitions.get(nodeId) ?? null;
  }

  /**
   * 创建或更新指定节点的关节定义
   * @param {string} nodeId - child 节点 uuid
   * @param {Object} patch - 要更新的字段
   * @param {Object} [patch.baseTransform] - 关节零点姿态 {tx,ty,tz,rx,ry,rz}
   *   首次创建关节时由调用方传入对象当前的 local position/rotation。
   *   之后 applyJointDrive 以此为零点（currentValue=0 时回到这个姿态）。
   *   注意：def.baseTransform 与 objectData.baseTransform 是两个独立概念，
   *   后者用于关键帧动画的 bind pose，前者只服务于关节驱动。
   * @returns {Object|null}
   */
  setJointDef(nodeId, patch) {
    const existing = this.jointDefinitions.get(nodeId);
    const def = existing || {
      id: nodeId,
      name: '',
      type: 'none',       // none | revolute | prismatic | fixed
      axis: 'y',           // x | y | z (UI convention)
      role: '',            // 语义角色标签（车体前进/门架升降等），AI 按此匹配意图
      origin: { x: 0, y: 0, z: 0 }, // 关节原点（世界空间，UI Z-up 约定）——revolute 的旋转中心
      limits: { min: -180, max: 180 },
      parentId: null,
      childId: nodeId,
      currentValue: 0,
      baseTransform: null, // 关节零点姿态，由首次创建关节时捕获
      // #59 双段门架（内外嵌套）overflow 机制（见 bugfix-log #59 / REVIEW-v15 后续）：
      //   limit_upper=null 表示未启用；启用时，currentValue 超过 limit_upper 的部分
      //   会由 _redistributeOverflows 在每次 applyAllJointDrives 前派给 overflow_to 指
      //   向的关节。overflow_to 存关节 **名字**（跨 ZIP roundtrip 稳定），不是 uuid。
      limit_upper: null,
      overflow_to: null,
    };
    if (typeof patch.name !== 'undefined') def.name = String(patch.name);
    if (typeof patch.role !== 'undefined') def.role = String(patch.role);
    if (patch.type) def.type = patch.type;
    if (patch.axis) def.axis = patch.axis;
    if (patch.origin) {
      if (typeof patch.origin.x !== 'undefined') def.origin.x = normalizeValue(patch.origin.x, def.origin.x);
      if (typeof patch.origin.y !== 'undefined') def.origin.y = normalizeValue(patch.origin.y, def.origin.y);
      if (typeof patch.origin.z !== 'undefined') def.origin.z = normalizeValue(patch.origin.z, def.origin.z);
    }
    if (patch.limits) {
      if (typeof patch.limits.min !== 'undefined') def.limits.min = normalizeValue(patch.limits.min, def.limits.min);
      if (typeof patch.limits.max !== 'undefined') def.limits.max = normalizeValue(patch.limits.max, def.limits.max);
    }
    if (typeof patch.parentId !== 'undefined') {
      // 环检测：从 patch.parentId 沿链向上走，如果走回到 nodeId 自己 → 形成循环 → 拒绝
      // 例：A→B→C，现在想设 A 的 parent 为 C → 走链 C→B→A → 碰到 A → 环！
      // 没有环检测的话 Kahn's 拓扑排序会静默丢弃环内关节，用户看到"关节不动"但不知道为什么
      if (patch.parentId) {
        let hasCycle = false;
        let cursor = patch.parentId;
        const visited = new Set([nodeId]); // 包含自己（自引用也是环）
        while (cursor) {
          if (visited.has(cursor)) { hasCycle = true; break; }
          visited.add(cursor);
          const parentDef = this.jointDefinitions.get(cursor);
          cursor = parentDef?.parentId || null;
        }
        if (hasCycle) {
          console.warn(`[setJointDef] 拒绝设置 parentId：${def.name || nodeId} → ${patch.parentId} 会形成循环依赖`);
        } else {
          def.parentId = patch.parentId;
        }
      } else {
        def.parentId = patch.parentId; // 设为 null（无父级 / 世界）始终允许
      }
    }
    if (typeof patch.childId !== 'undefined') def.childId = patch.childId;
    if (typeof patch.currentValue !== 'undefined') def.currentValue = normalizeValue(patch.currentValue, 0);
    // #59 overflow 机制：null / 空字符串 / undefined 均视为"未启用"
    if (typeof patch.limit_upper !== 'undefined') {
      if (patch.limit_upper === null || patch.limit_upper === '' || !Number.isFinite(Number(patch.limit_upper))) {
        def.limit_upper = null;
      } else {
        def.limit_upper = Number(patch.limit_upper);
      }
    }
    if (typeof patch.overflow_to !== 'undefined') {
      const trimmed = patch.overflow_to == null ? '' : String(patch.overflow_to).trim();
      def.overflow_to = trimmed || null;
    }
    // 仅在 patch 显式传入时更新 baseTransform，避免后续修改类型/轴时覆盖零点
    // 支持两种旋转格式：qx/qy/qz/qw（四元数，推荐）或 rx/ry/rz（Euler，兼容旧数据）
    if (patch.baseTransform) {
      const bt = patch.baseTransform;
      def.baseTransform = {
        tx: normalizeValue(bt.tx, 0),
        ty: normalizeValue(bt.ty, 0),
        tz: normalizeValue(bt.tz, 0),
      };
      if (bt.qw !== undefined) {
        // 四元数（无万向锁）
        def.baseTransform.qx = normalizeValue(bt.qx, 0);
        def.baseTransform.qy = normalizeValue(bt.qy, 0);
        def.baseTransform.qz = normalizeValue(bt.qz, 0);
        def.baseTransform.qw = normalizeValue(bt.qw, 1);
      } else {
        // Euler 兼容（旧数据）
        def.baseTransform.rx = normalizeValue(bt.rx, 0);
        def.baseTransform.ry = normalizeValue(bt.ry, 0);
        def.baseTransform.rz = normalizeValue(bt.rz, 0);
      }
    }

    if (def.type === 'none') {
      this.jointDefinitions.delete(nodeId);
      return null;
    }
    this.jointDefinitions.set(nodeId, def);
    return def;
  }

  removeJointDef(nodeId) {
    return this.jointDefinitions.delete(nodeId);
  }

  getAllJointDefs() {
    return [...this.jointDefinitions.values()];
  }

  /**
   * 按 role 找"主"关节。多个关节共享同一 role 时（如双段门架内外都叫"门架升降"），
   * 被别人 `overflow_to` 指向的关节（slave）自动被跳过。
   *
   * 设计理由（#59 UX 优化）：
   *   用户自然倾向于把"门架升降"这个 role 贴给**所有**门架段（语义真实）。
   *   原来的 `find(d => d.role === x)` 命中顺序不稳定，双段门架时可能随机挑到外门架，
   *   导致模板 PKF 绑错关节 + redistribute 把外门架 value 抢走 → fork 不抬（见 bugfix #59）。
   *
   *   这个 helper 统一规则："slave 不被选为主"。规则由 overflow_to 字段**自动推导**，
   *   用户无需 UI 侧额外操作。单关节 role 或无 overflow 配置 → slave 集合为空 → 退化为原行为。
   *
   *   若 role 只有 slave 命中（用户误配），fallback 仍返回 slave（保底行为不破坏），
   *   模板后续的 missing 检查会捕获真正的配置错误。
   *
   * @param {string} role
   * @returns {Object|null}
   */
  findPrimaryByRole(role) {
    if (!role) return null;
    const all = [...this.jointDefinitions.values()];
    const slaveNames = new Set();
    all.forEach((d) => { if (d.overflow_to) slaveNames.add(d.overflow_to); });
    return all.find((d) => d.role === role && d.name && !slaveNames.has(d.name))
      || all.find((d) => d.role === role)
      || null;
  }

  getJointDefLabel(nodeId) {
    const def = this.jointDefinitions.get(nodeId);
    if (!def) return '无';
    if (def.type === 'revolute') return '🔄R';
    if (def.type === 'prismatic') return '↕P';
    if (def.type === 'fixed') return '🔗F';
    return '无';
  }

  setJointValue(nodeId, value) {
    const def = this.jointDefinitions.get(nodeId);
    if (!def || def.type === 'fixed') return 0;
    // #59 若启用 overflow（双段门架等）：上界由 _redistributeOverflows 按 limit_upper
    //     拆给 overflow_to 关节；这里不能提前 clamp 掉，否则溢出量全被砍掉。
    const effectiveMax = def.overflow_to ? Number.POSITIVE_INFINITY : def.limits.max;
    const clamped = Math.max(def.limits.min, Math.min(effectiveMax, normalizeValue(value, 0)));
    def.currentValue = clamped;
    return clamped;
  }

  /**
   * FK 求解：驱动单个关节
   *
   * 核心改变（v4→v5）：不再依赖 Three.js 场景树层级来传递运动。
   * 运动链完全由 jointDefinition 的 parentId/childId 决定。
   *
   * def.parentId = "关节父级"（逻辑概念，可以是场景树里的任意节点，不一定是 childObj 的场景树 parent）
   * def.baseTransform = child 相对于**关节父级**的 local 姿态（不是场景树 parent）
   * def.origin = 旋转/平移参考点，在关节父级的 local 空间（UI Z-up）
   *
   * 求解流程：
   *  1. 找到关节父级对象（by def.parentId），读取其当前 worldMatrix
   *  2. 从关节父级的 local 空间恢复 child 的零点世界位置（jointParent.localToWorld(base)）
   *  3. 从关节父级的 local 空间恢复 origin 的世界位置
   *  4. 根据 type + axis + currentValue 在世界空间旋转/平移
   *  5. 把结果世界坐标转回**场景树 parent** 的 local，写入 childObj.position/quaternion
   *
   * 效果：场景树里平级的节点也能互相形成关节链。
   *       场景树层级变化不影响运动（只要关节定义不变）。
   *
   * @param {string} nodeId
   * @param {THREE.Object3D} root
   * @param {boolean} [force=false]
   */
  applyJointDrive(nodeId, root, force = false) {
    const def = this.jointDefinitions.get(nodeId);
    if (!def || def.type === 'none') return;
    if (!force && this._gizmoDraggingNodeId === nodeId) return;

    // ── 找对象 ──
    // _nodeMap 由 applyAllJointDrives 建立缓存；直接调用时（gizmo/slider）自建临时 map
    let nodeMap = this._nodeMap;
    if (!nodeMap && root) {
      nodeMap = new Map();
      root.traverse((obj) => nodeMap.set(obj.uuid, obj));
    }
    const childObj = nodeMap?.get(nodeId) || null;
    if (!childObj) return;
    const jointParent = def.parentId ? (nodeMap.get(def.parentId) || null) : null;
    const sceneParent = childObj.parent; // 场景树 parent（用于最后写回 local）
    if (!sceneParent) return;

    // ── 懒捕获 baseTransform（相对于关节父级）──
    // 旋转用四元数（qx/qy/qz/qw）而不是 Euler（rx/ry/rz）——避免万向锁丢失信息。
    // 典型触发：Euler ry≈π/2 时 Quaternion→Euler→Quaternion 来回转换会偏 57°+。
    if (!def.baseTransform) {
      if (jointParent) {
        jointParent.updateMatrixWorld(true);
        childObj.updateMatrixWorld(true);
        const childWorldPos = childObj.getWorldPosition(new THREE.Vector3());
        const childWorldQuat = childObj.getWorldQuaternion(new THREE.Quaternion());
        const jpWorldQuatInv = jointParent.getWorldQuaternion(new THREE.Quaternion()).invert();
        const childInJP = jointParent.worldToLocal(childWorldPos.clone());
        const childQuatInJP = jpWorldQuatInv.multiply(childWorldQuat);
        def.baseTransform = {
          tx: childInJP.x, ty: childInJP.y, tz: childInJP.z,
          qx: childQuatInJP.x, qy: childQuatInJP.y, qz: childQuatInJP.z, qw: childQuatInJP.w,
        };
      } else {
        // 没有关节父级，用场景树 local 兜底（四元数）
        def.baseTransform = {
          tx: childObj.position.x, ty: childObj.position.y, tz: childObj.position.z,
          qx: childObj.quaternion.x, qy: childObj.quaternion.y,
          qz: childObj.quaternion.z, qw: childObj.quaternion.w,
        };
      }
    }
    const base = def.baseTransform;

    // ── origin：关节父级 local (UI Z-up) → 世界 ──
    const originInJP = new THREE.Vector3(
      def.origin?.x ?? 0,
      def.origin?.z ?? 0,  // UI Z → Three.js Y
      def.origin?.y ?? 0,  // UI Y → Three.js Z
    );
    let originWorld;
    if (jointParent) {
      jointParent.updateMatrixWorld(true);
      originWorld = jointParent.localToWorld(originInJP.clone());
    } else {
      originWorld = originInJP.clone(); // 无关节父级，origin 当世界坐标
    }

    // ── 从 base 恢复 child 的零点世界位置/旋转（通过关节父级转换）──
    // 旋转从 baseTransform 的四元数（qx/qy/qz/qw）读取，避免 Euler 万向锁
    const baseLocalQuat = (base.qw !== undefined)
      ? new THREE.Quaternion(base.qx, base.qy, base.qz, base.qw)
      : new THREE.Quaternion().setFromEuler(new THREE.Euler(base.rx ?? 0, base.ry ?? 0, base.rz ?? 0)); // 兼容旧数据

    let baseWorldPos, baseWorldQuat;
    if (jointParent) {
      const baseLocalPos = new THREE.Vector3(base.tx, base.ty, base.tz);
      baseWorldPos = jointParent.localToWorld(baseLocalPos.clone());
      const jpWorldQuat = jointParent.getWorldQuaternion(new THREE.Quaternion());
      baseWorldQuat = jpWorldQuat.clone().multiply(baseLocalQuat);
    } else {
      // 无关节父级，base 当场景树 local → 世界
      sceneParent.updateMatrixWorld(true);
      baseWorldPos = sceneParent.localToWorld(new THREE.Vector3(base.tx, base.ty, base.tz));
      const spWorldQuat = sceneParent.getWorldQuaternion(new THREE.Quaternion());
      baseWorldQuat = spWorldQuat.multiply(baseLocalQuat);
    }

    // ── 按 type 应用 currentValue ──
    let newWorldPos, newWorldQuat;

    if (def.type === 'revolute') {
      const rad = (def.currentValue * Math.PI) / 180;
      const worldAxis = mapUiAxisToWorld(def.axis);
      const worldAxisVec = worldAxis === 'x' ? new THREE.Vector3(1, 0, 0)
        : worldAxis === 'y' ? new THREE.Vector3(0, 1, 0)
        : new THREE.Vector3(0, 0, 1);
      const deltaQuat = new THREE.Quaternion().setFromAxisAngle(worldAxisVec, rad);

      // 绕 originWorld 旋转
      const offset = baseWorldPos.clone().sub(originWorld);
      const rotatedOffset = offset.applyQuaternion(deltaQuat);
      newWorldPos = originWorld.clone().add(rotatedOffset);
      newWorldQuat = deltaQuat.clone().multiply(baseWorldQuat);
    } else if (def.type === 'prismatic') {
      const worldAxis = mapUiAxisToWorld(def.axis);
      const worldAxisVec = worldAxis === 'x' ? new THREE.Vector3(1, 0, 0)
        : worldAxis === 'y' ? new THREE.Vector3(0, 1, 0)
        : new THREE.Vector3(0, 0, 1);

      newWorldPos = baseWorldPos.clone().add(worldAxisVec.multiplyScalar(def.currentValue));
      newWorldQuat = baseWorldQuat.clone();
    } else if (def.type === 'fixed') {
      // 固定关节：刚性连接到关节父级，无自由度但要跟着父级动
      // 等价于 prismatic value=0：world 位置直接用 baseWorldPos（已经包含关节父级的最新变换）
      newWorldPos = baseWorldPos.clone();
      newWorldQuat = baseWorldQuat.clone();
    } else {
      return;
    }

    // ── 世界 → 场景树 parent local → 写入 child ──
    sceneParent.updateMatrixWorld(true);
    childObj.position.copy(sceneParent.worldToLocal(newWorldPos.clone()));
    const sceneParentQuatInv = sceneParent.getWorldQuaternion(new THREE.Quaternion()).invert();
    childObj.quaternion.copy(sceneParentQuatInv.multiply(newWorldQuat));

    // ── 帧级调试（开发期保留）：value=0 时验证 apply 结果是否等于 stored base ──
    // 旧版对比 before/after，会在 "value=1→0 恢复" 这种正常操作上误报。
    // 正确语义：value=0 时 apply 结果的世界位姿应该和 stored base 的世界位姿一致；
    // 如果不一致，说明 base 过时 / 链路错乱 / 懒捕获时机不对——这才是真 drift。
    if (def.currentValue === 0 && !def._driftWarned) {
      childObj.updateMatrixWorld(true);
      const _dbgPosAfter = childObj.getWorldPosition(new THREE.Vector3());
      const _dbgQuatAfter = childObj.getWorldQuaternion(new THREE.Quaternion());
      const _dbgPosDrift = _dbgPosAfter.distanceTo(baseWorldPos);
      const _dbgQuatDot = Math.abs(_dbgQuatAfter.dot(baseWorldQuat));
      const _dbgRotDrift = Math.acos(Math.min(_dbgQuatDot, 1.0)) * 2 * (180 / Math.PI);
      if (_dbgPosDrift > 0.01 || _dbgRotDrift > 1.0) {
        def._driftWarned = true;
        console.warn(
          `[applyJointDrive] ⚠ ${def.name} value=0 但 apply 结果偏离 stored base：pos=${_dbgPosDrift.toFixed(4)} rot=${_dbgRotDrift.toFixed(1)}°`,
          `\n  jointParent: ${jointParent?.name || '(无)'}  sceneParent: ${sceneParent?.name || '(无)'}`,
          `\n  base:`, JSON.stringify(base),
        );
      }
    }
  }

  /**
   * 驱动所有关节。按**关节定义链**拓扑排序（不是场景树深度）。
   *
   * 拓扑排序规则：如果 jointA 的 childId === jointB 的 parentId，
   * 则 jointA 先驱动。这样 jointB 求解时，jointA 的 child（即 jointB 的 parent）
   * 已经处于本帧的最终位置。
   *
   * 效果：场景树平级的节点也能正确级联（例如门架和叉齿平级，但叉齿的关节 parent 是门架）。
   */
  /**
   * #59 双段门架 overflow 机制：在驱动前重新分配溢出值。
   *
   * 典型场景：三向车 / 前移式叉车有内外两节门架
   *   - 内门架 cAR201（parent = 外门架 _____10，嵌套在外门架框架里）
   *   - 外门架 _____10
   *   - 自由升降阶段：只有 cAR201 在外门架内爬升
   *   - 高架阶段：cAR201 爬到顶（limit_upper），继续升高靠 _____10 整体上推
   *
   * 对 cAR201（limit_upper=4, overflow_to="_____10"）：
   *   currentValue=3 → 自己=3，_____10 的 currentValue=0
   *   currentValue=5 → 自己=4，_____10 的 currentValue=1
   *   currentValue=9 → 自己=4，_____10 的 currentValue=5
   *
   * 下降天然对称：target 从高到低减 → outer 先归零 → inner 才减。
   *
   * ⚠️ 只处理单级（inner → outer），多级嵌套（3 段门架）当前不支持。
   * ⚠️ overflow_to 指向的关节不应有独立动画（PKF step / 关键帧），会被强制覆盖为 overflow 值。
   *
   * @private
   */
  _redistributeOverflows() {
    // 建立 name → def 索引（overflow_to 按名字存，跨 ZIP roundtrip 稳定）
    let nameIndex = null;
    const getByName = (name) => {
      if (!nameIndex) {
        nameIndex = new Map();
        this.jointDefinitions.forEach((d) => {
          if (d.name) nameIndex.set(d.name, d);
        });
      }
      return nameIndex.get(name) || null;
    };

    this.jointDefinitions.forEach((def) => {
      if (!def.overflow_to || def.limit_upper == null) return;
      const targetDef = getByName(def.overflow_to);
      if (!targetDef) return; // 目标关节找不到 → 静默跳过（demo 级，避免烦人告警）
      const raw = def.currentValue;
      const limit = def.limit_upper;
      if (raw > limit) {
        def.currentValue = limit;
        targetDef.currentValue = raw - limit;
      } else {
        // 在 limit 范围内：inner 保持 raw 值，outer 归零（防止上一帧残留）
        targetDef.currentValue = 0;
      }
    });
  }

  applyAllJointDrives(root) {
    if (!root) return;

    // #59 overflow 分摊必须在驱动之前：让溢出量先落到 outer 关节的 currentValue 上，
    //     再走下面的拓扑排序 / applyJointDrive → 外门架先驱动、内门架在外门架的新位置里驱动。
    this._redistributeOverflows();

    // 建立 nodeMap 缓存（避免每个 joint 都 traverse 一遍）
    const nodeMap = new Map();
    root.traverse((obj) => nodeMap.set(obj.uuid, obj));
    this._nodeMap = nodeMap;

    // 拓扑排序：parentId 指向另一个 jointDef 的 childId → 被指向的先驱动
    const defs = [...this.jointDefinitions.values()];
    const childIdSet = new Set(defs.map((d) => d.childId));
    // 入度计数
    const inDegree = new Map();
    defs.forEach((d) => inDegree.set(d.childId, 0));
    defs.forEach((d) => {
      if (d.parentId && childIdSet.has(d.parentId)) {
        inDegree.set(d.childId, (inDegree.get(d.childId) || 0) + 1);
      }
    });
    // Kahn's algorithm
    const queue = defs.filter((d) => (inDegree.get(d.childId) || 0) === 0);
    const sorted = [];
    while (queue.length) {
      const cur = queue.shift();
      sorted.push(cur);
      // 找所有以 cur.childId 为 parentId 的关节
      defs.forEach((d) => {
        if (d.parentId === cur.childId) {
          inDegree.set(d.childId, (inDegree.get(d.childId) || 0) - 1);
          if (inDegree.get(d.childId) <= 0) queue.push(d);
        }
      });
    }
    // 如果有环（不太可能），把剩余的也加上
    defs.forEach((d) => {
      if (!sorted.includes(d)) sorted.push(d);
    });

    sorted.forEach((def) => {
      this.applyJointDrive(def.childId, root);
    });

    this._nodeMap = null; // 释放缓存
  }

  // ══════════════════════════════════════════════════════════════
  //  全局动画片段（Global Clips）管理
  // ══════════════════════════════════════════════════════════════

  /** 当前激活的全局 clip 对象 */
  getActiveGlobalClip() {
    return this.globalClips.get(this.activeClipName) ?? null;
  }

  /** 所有全局 clip 名称列表 */
  getClipNames() {
    return [...this.globalClips.keys()];
  }

  /** 切换激活的全局 clip */
  setActiveClip(clipName) {
    if (!this.globalClips.has(clipName)) return false;
    this.activeClipName = clipName;
    return true;
  }

  /**
   * 创建一个全局 clip。如果名字冲突自动加后缀
   * @param {string} requestedName
   * @returns {string} 实际创建的 clip 名（可能带后缀）
   */
  createClip(requestedName) {
    const base = (requestedName || 'new_clip').trim() || 'new_clip';
    let name = base;
    let i = 1;
    while (this.globalClips.has(name)) {
      i += 1;
      name = `${base}_${i}`;
    }
    this.globalClips.set(name, { clipName: name, duration: 10, keyframes: [], reparentEvents: [] });
    return name;
  }

  /** 当前 clip 时长（秒） */
  getClipDuration() {
    return this.getActiveGlobalClip()?.duration ?? 10;
  }

  /** 设置当前 clip 时长 */
  setClipDuration(duration) {
    const clip = this.getActiveGlobalClip();
    if (!clip) return;
    clip.duration = Math.max(0.1, Number(duration) || 10);
  }

  /** 当前 clip 的关键帧数组 */
  getKeyframes() {
    return this.getActiveGlobalClip()?.keyframes ?? [];
  }

  // ══════════════════════════════════════════════════════════════
  //  全局关键帧 CRUD
  // ══════════════════════════════════════════════════════════════

  /**
   * 在指定时间添加一个全局关键帧
   * 抓取**所有有 jointDef 的对象**的当前 def.currentValue，存入 keyframe.jointValues
   * @param {number} time
   * @returns {Object|null} 创建的关键帧对象
   */
  addKeyframe(time) {
    const clip = this.getActiveGlobalClip();
    if (!clip) return null;

    // 收集所有关节定义的当前状态
    const jointValues = {};
    this.jointDefinitions.forEach((def) => {
      jointValues[def.id] = normalizeValue(def.currentValue, 0);
    });

    const t = Number(time);
    // 同一时间已有关键帧则替换
    clip.keyframes = clip.keyframes.filter((k) => Math.abs(k.time - t) > 0.0001);
    const keyframe = { time: t, jointValues };
    clip.keyframes.push(keyframe);
    clip.keyframes.sort((a, b) => a.time - b.time);
    return keyframe;
  }

  /**
   * 删除指定时间的全局关键帧
   * @param {number} time
   * @returns {boolean}
   */
  removeKeyframe(time) {
    const clip = this.getActiveGlobalClip();
    if (!clip) return false;
    const before = clip.keyframes.length;
    clip.keyframes = clip.keyframes.filter((k) => Math.abs(k.time - Number(time)) > 0.0001);
    return clip.keyframes.length !== before;
  }

  // ══════════════════════════════════════════════════════════════
  //  关键帧求值
  // ══════════════════════════════════════════════════════════════

  /**
   * 在时间 t 上为指定 joint def 求值（在当前 clip 的关键帧中插值）
   * 只考虑那些 jointValues 字典里**包含该 jointDefId**的关键帧
   * @param {Array} keyframes - 全局关键帧数组
   * @param {string} jointDefId
   * @param {number} t
   * @returns {number|null} 插值结果，没有任何相关关键帧则返回 null
   */
  _interpolateJointValueAtTime(keyframes, jointDefId, t) {
    // 只看包含该关节状态的关键帧
    const relevant = keyframes.filter(
      (k) => k.jointValues && k.jointValues[jointDefId] !== undefined && k.jointValues[jointDefId] !== null,
    );
    if (!relevant.length) return null;

    if (t <= relevant[0].time) {
      return relevant[0].jointValues[jointDefId];
    }
    if (t >= relevant[relevant.length - 1].time) {
      return relevant[relevant.length - 1].jointValues[jointDefId];
    }
    for (let i = 0; i < relevant.length - 1; i += 1) {
      const left = relevant[i];
      const right = relevant[i + 1];
      if (t < left.time || t > right.time) continue;
      const ratio = (t - left.time) / (right.time - left.time);
      return lerp(left.jointValues[jointDefId], right.jointValues[jointDefId], ratio);
    }
    return null;
  }

  /**
   * 在时间 t 求值整个项目的关键帧动画
   * 对每个 jointDef 在当前 clip 中插值，写回 def.currentValue
   * 之后 loop 里的 applyAllJointDrives 会用新的 currentValue 驱动对象
   * @param {number} time
   * @param {THREE.Object3D} _root - 兼容旧签名，未使用
   */
  evaluateAllAt(time, _root) {
    this.currentTime = Math.max(0, Number(time) || 0);
    const clip = this.getActiveGlobalClip();
    if (!clip || !clip.keyframes.length) return;

    this.jointDefinitions.forEach((def) => {
      const value = this._interpolateJointValueAtTime(clip.keyframes, def.id, this.currentTime);
      if (value !== null && value !== undefined) {
        def.currentValue = normalizeValue(value, def.currentValue);
      }
    });
  }

  // ══════════════════════════════════════════════════════════════
  //  PKF 参数 CRUD（增删改查）
  // ══════════════════════════════════════════════════════════════

  /**
   * 添加一个 PKF 参数声明
   * @param {Object} param - 参数对象
   * @param {string} param.id       - 唯一标识（必填），同时也是公式中引用的变量名
   * @param {string} [param.type]   - 值类型，默认 'number'，可选 'vec3'
   * @param {string} [param.unit]   - 单位，如 'mm'、'deg'
   * @param {string} [param.desc]   - 中文描述
   * @param {*}      [param.default] - 默认值，编辑器预览时使用，默认 0
   * @returns {Object|null} 创建成功返回参数对象；id 为空或已存在返回 null
   */
  addPkfParameter(param) {
    if (!param?.id) return null;                       // id 为空，拒绝
    if (!PKF_ID_VALID_RE.test(param.id)) return null;  // 非法标识符（REVIEW-v15 F4），拒绝
    if (this.pkfParameters.has(param.id)) return null; // id 重复，拒绝
    const created = {
      id: param.id,
      type: param.type || 'number',
      unit: param.unit || '',
      desc: param.desc || '',
      default: param.default ?? 0,
    };
    this.pkfParameters.set(created.id, created);
    return created;
  }

  /**
   * 更新指定 PKF 参数的字段（支持改名）
   * 改名时会自动更新所有步骤公式中对该参数的引用（正则单词边界匹配）
   * @param {string} id    - 要修改的参数 id
   * @param {Object} patch - 要更新的字段（只传需要改的）
   * @returns {boolean} 成功返回 true；参数不存在或新 id 冲突返回 false
   */
  updatePkfParameter(id, patch) {
    const existing = this.pkfParameters.get(id);
    if (!existing) return false; // 参数不存在

    // ── 处理 id 改名 ──
    if (patch.id && patch.id !== id) {
      // REVIEW-v15 F4：新 id 必须是合法 JS 标识符（公式求值器的识别规则是 /[a-zA-Z_]\w*/g）
      // 否则公式里永远无法引用它；且 new RegExp 构造遇正则元字符会抛异常
      if (!PKF_ID_VALID_RE.test(patch.id)) return false;
      if (this.pkfParameters.has(patch.id)) return false; // 新 id 已被占用，拒绝
      this.pkfParameters.delete(id);       // 从 Map 中移除旧 key
      existing.id = patch.id;              // 更新对象的 id
      this.pkfParameters.set(existing.id, existing); // 用新 key 存回 Map

      // 遍历所有步骤，将公式中的旧参数名替换为新参数名
      // 使用 \b 单词边界，避免误替换（如 stroke 不会匹配 stroke_rate）
      // 安全性：旧 id 既然已存在就必然通过 addPkfParameter 的校验（合法标识符），
      //        new RegExp 不会因正则元字符抛（合法标识符全是字母数字下划线）
      this.pkfSteps.forEach((s) => {
        if (typeof s.value_start === 'string') s.value_start = s.value_start.replace(new RegExp(`\\b${id}\\b`, 'g'), existing.id);
        if (typeof s.value_end === 'string') s.value_end = s.value_end.replace(new RegExp(`\\b${id}\\b`, 'g'), existing.id);
      });
    }

    // ── 更新普通字段（只改传入的字段，不碰其他字段）──
    if (typeof patch.type !== 'undefined') existing.type = patch.type;
    if (typeof patch.unit !== 'undefined') existing.unit = patch.unit;
    if (typeof patch.desc !== 'undefined') existing.desc = patch.desc;
    if (typeof patch.default !== 'undefined') existing.default = patch.default;
    return true;
  }

  /**
   * 删除指定 PKF 参数
   * @param {string} id - 参数 id
   * @returns {boolean} 删除成功返回 true；不存在返回 false
   */
  removePkfParameter(id) {
    return this.pkfParameters.delete(id);
  }

  /**
   * 获取所有 PKF 参数的副本数组
   * @returns {Array<Object>} 参数对象数组（浅拷贝，修改不影响内部数据）
   */
  getAllPkfParameters() {
    return [...this.pkfParameters.values()];
  }

  // ══════════════════════════════════════════════════════════════
  //  PKF 步骤 CRUD（增删改查）
  // ══════════════════════════════════════════════════════════════

  /**
   * 添加一个 PKF 步骤
   * @param {Object} [step] - 步骤配置
   * @param {string} [step.id]           - 唯一标识，不传则自动生成（时间戳+随机串）
   * @param {string} [step.joint]        - 关联的关节名称
   * @param {string} [step.joint_def_id] - 关联的关节定义 id
   * @param {string} [step.channel]      - 通道：'translate' 或 'rotate'，默认 'translate'
   * @param {string} [step.axis]         - 轴向：'x'/'y'/'z'，默认 'z'（Z-up 主轴）
   * @param {number} [step.t_start]      - 起始时间（秒），默认 0
   * @param {number} [step.t_end]        - 结束时间（秒），默认 1
   * @param {string} [step.value_start]  - 起始值公式字符串，默认 '0'
   * @param {string} [step.value_end]    - 结束值公式字符串，默认 '0'
   * @param {string} [step.easing]       - 缓动类型，默认 'linear'
   * @returns {Object} 创建好的步骤对象
   */
  addPkfStep(step) {
    const created = {
      id: step?.id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, // 自动生成唯一 id
      joint: step?.joint || '',
      joint_def_id: step?.joint_def_id || '',
      channel: step?.channel || 'translate',
      axis: step?.axis || 'z',
      t_start: step?.t_start ?? 0,
      t_end: step?.t_end ?? 1,
      value_start: String(step?.value_start ?? '0'), // 强制转字符串，PKF 核心是公式
      value_end: String(step?.value_end ?? '0'),     // 同上
      easing: step?.easing || 'linear',
      // 模板元数据（mvp3）：compileTemplate 产出的段会带 template_segment + name
      // 用于轨迹 overlay / 诊断脚本的段号标签；非模板 step 为 null（不影响常规 PKF 求值）
      // REVIEW-v15 F34：之前这两字段被静默丢弃，轨迹 overlay 段号标签一直走 idx0+1 兜底
      template_segment: step?.template_segment ?? null,
      template_segment_name: step?.template_segment_name ?? null,
    };
    this.pkfSteps.push(created);
    return created;
  }

  /**
   * 更新指定 PKF 步骤的字段
   * @param {string} stepId - 步骤 id
   * @param {Object} patch  - 要更新的字段（只传需要改的）
   * @returns {boolean} 成功返回 true；步骤不存在返回 false
   */
  updatePkfStep(stepId, patch) {
    const step = this.pkfSteps.find((s) => s.id === stepId);
    if (!step) return false; // 步骤不存在

    // 逐字段检查并更新，只改传入的字段
    if (typeof patch.joint !== 'undefined') step.joint = patch.joint;
    if (typeof patch.joint_def_id !== 'undefined') step.joint_def_id = patch.joint_def_id;
    if (typeof patch.channel !== 'undefined') step.channel = patch.channel;
    if (typeof patch.axis !== 'undefined') step.axis = patch.axis;
    if (typeof patch.t_start !== 'undefined') step.t_start = Number(patch.t_start) || 0;
    if (typeof patch.t_end !== 'undefined') step.t_end = Number(patch.t_end) || 0;
    if (typeof patch.value_start !== 'undefined') step.value_start = String(patch.value_start); // 保持字符串
    if (typeof patch.value_end !== 'undefined') step.value_end = String(patch.value_end);       // 保持字符串
    if (typeof patch.easing !== 'undefined') step.easing = patch.easing;
    return true;
  }

  /**
   * 删除指定 PKF 步骤
   * @param {string} stepId - 步骤 id
   * @returns {boolean} 删除成功返回 true；不存在返回 false
   */
  removePkfStep(stepId) {
    const before = this.pkfSteps.length;
    this.pkfSteps = this.pkfSteps.filter((s) => s.id !== stepId); // 过滤掉目标步骤
    return this.pkfSteps.length !== before; // 长度变化说明确实删了
  }

  /**
   * 获取所有 PKF 步骤的副本数组
   * @returns {Array<Object>} 步骤对象数组（浅拷贝）
   */
  getAllPkfSteps() {
    return [...this.pkfSteps];
  }

  serializeState() {
    return {
      currentTime: this.currentTime,
      jointDefinitions: [...this.jointDefinitions.values()].map((d) => ({
        id: d.id,
        name: d.name,
        type: d.type,
        axis: d.axis,
        role: d.role || '',
        origin: { x: d.origin?.x ?? 0, y: d.origin?.y ?? 0, z: d.origin?.z ?? 0 },
        limits: { min: d.limits.min, max: d.limits.max },
        parentId: d.parentId,
        childId: d.childId,
        currentValue: d.currentValue,
        // 关节零点姿态（深拷贝），undo/redo 时不能丢
        baseTransform: d.baseTransform ? { ...d.baseTransform } : null,
        // #59 双段门架 overflow：null 表示未启用（默认），数字为 limit_upper 值
        limit_upper: d.limit_upper ?? null,
        overflow_to: d.overflow_to ?? null,
      })),
      objects: [...this.objectDataById.values()].map((obj) => ({
        objectId: obj.objectId,
        objectName: obj.objectName,
        baseTransform: obj.baseTransform,
      })),
      // 全局 clips：每个 clip 包含 duration + keyframes + reparentEvents（schema v5）
      activeClipName: this.activeClipName,
      globalClips: [...this.globalClips.values()].map((clip) => ({
        clipName: clip.clipName,
        duration: clip.duration,
        keyframes: clip.keyframes.map((k) => ({
          time: k.time,
          jointValues: { ...k.jointValues }, // 浅拷贝足够（值都是 number）
        })),
        // v5: reparent 事件（深拷贝）
        reparentEvents: (clip.reparentEvents || []).map((e) => ({ ...e })),
      })),
      // PKF 数据序列化（深拷贝，确保快照与当前数据解耦）
      pkfParameters: [...this.pkfParameters.values()].map((p) => ({ ...p })),
      pkfSteps: this.pkfSteps.map((s) => ({ ...s })),
      // schema v6: 场景标记
      sceneMarkers: [...this.sceneMarkers.values()].map((m) => ({
        id: m.id,
        name: m.name,
        type: m.type,
        size: m.size ? { ...m.size } : null,
        color: m.color || null,
      })),
      // mvp3: 模板路径 runtime 标记（applyReparentEventsAtTime 据此禁用 snap-attach）
      // REVIEW-v15 F35：之前不进 undo，导致模板→清空→undo 后 pkfSteps 回到模板但 _pkfTemplateMeta=null
      //                 → snap-attach 被重新激活 → attach 瞬移
      _pkfTemplateMeta: this._pkfTemplateMeta ? { ...this._pkfTemplateMeta } : null,
    };
  }

  restoreState(serializedState) {
    this.currentTime = serializedState?.currentTime ?? 0;

    // F11 (DEBT #3) 防御：先捕获恢复前的 role 映射。
    // 正常路径里 serializeState 一定写 role 字段（见 L1124），但：
    // (a) 老版本序列化的 state（pre-v10 role 字段引入前）缺这个字段
    // (b) 外部代码误构造 snapshot 时可能丢
    // 遇到 snapshot 里 role 字段**缺失**（undefined，不是空字符串）→ 保留当前值，不清空
    const prevRoles = new Map();
    this.jointDefinitions.forEach((d, id) => {
      if (d.role) prevRoles.set(id, d.role);
    });

    // Restore joint definitions
    this.jointDefinitions.clear();
    (serializedState?.jointDefinitions || []).forEach((d) => {
      // role 字段缺失（undefined）→ 用恢复前值兜底；显式空字符串 → 接受为空
      const roleFromSnapshot = Object.prototype.hasOwnProperty.call(d, 'role') ? (d.role || '') : undefined;
      this.jointDefinitions.set(d.id, {
        id: d.id,
        name: d.name || '',
        type: d.type || 'none',
        axis: d.axis || 'y',
        role: roleFromSnapshot !== undefined ? roleFromSnapshot : (prevRoles.get(d.id) || ''),
        origin: { x: d.origin?.x ?? 0, y: d.origin?.y ?? 0, z: d.origin?.z ?? 0 },
        limits: { min: d.limits?.min ?? -180, max: d.limits?.max ?? 180 },
        parentId: d.parentId ?? null,
        childId: d.childId ?? d.id,
        currentValue: normalizeValue(d.currentValue, 0),
        // 关节零点姿态：可能为 null（旧数据），applyJointDrive 会 fallback
        baseTransform: d.baseTransform ? { ...d.baseTransform } : null,
        // #59 overflow 字段：老 snapshot 没有 → null（未启用），向后兼容
        limit_upper: (d.limit_upper != null && Number.isFinite(Number(d.limit_upper))) ? Number(d.limit_upper) : null,
        overflow_to: d.overflow_to || null,
      });
    });

    // Restore objectData (only baseTransform, no per-object clips anymore)
    this.objectDataById.clear();
    (serializedState?.objects || []).forEach((obj) => {
      this.objectDataById.set(obj.objectId, {
        objectId: obj.objectId,
        objectName: obj.objectName,
        baseTransform: obj.baseTransform,
      });
    });

    // Restore global clips
    this.globalClips.clear();
    (serializedState?.globalClips || []).forEach((clip) => {
      this.globalClips.set(clip.clipName, {
        clipName: clip.clipName,
        duration: Math.max(0.1, Number(clip.duration) || 10),
        keyframes: (clip.keyframes || []).map((k) => ({
          time: Number(k.time) || 0,
          jointValues: { ...(k.jointValues || {}) },
        })),
        // v5: 恢复 reparent 事件（旧快照没有字段 → 空数组兜底）
        reparentEvents: (clip.reparentEvents || []).map((e) => ({ ...e })),
      });
    });
    // 至少保证有一个 default clip
    if (!this.globalClips.size) {
      this.globalClips.set('default', { clipName: 'default', duration: 10, keyframes: [], reparentEvents: [] });
    }
    this.activeClipName = serializedState?.activeClipName && this.globalClips.has(serializedState.activeClipName)
      ? serializedState.activeClipName
      : this.globalClips.keys().next().value;

    // ── 恢复 PKF 数据 ──
    this.pkfParameters.clear(); // 先清空再重建，避免残留
    (serializedState?.pkfParameters || []).forEach((p) => {
      this.pkfParameters.set(p.id, { ...p }); // 深拷贝存入，与快照解耦
    });
    // 步骤数组整体替换，逐项深拷贝
    this.pkfSteps = (serializedState?.pkfSteps || []).map((s) => ({ ...s }));
    // schema v6: 恢复场景标记
    this.sceneMarkers.clear();
    (serializedState?.sceneMarkers || []).forEach((m) => {
      this.sceneMarkers.set(m.id, {
        id: m.id,
        name: m.name,
        type: m.type,
        size: m.size ? { ...m.size } : null,
        color: m.color || null,
      });
    });
    // mvp3 模板路径标记（REVIEW-v15 F35）：
    // hasOwnProperty 检查区分"老 snapshot 没这字段"（undefined，保持当前值）
    // 和"新 snapshot 显式写 null"（用户清空了模板，应恢复成 null）
    if (serializedState && Object.prototype.hasOwnProperty.call(serializedState, '_pkfTemplateMeta')) {
      this._pkfTemplateMeta = serializedState._pkfTemplateMeta
        ? { ...serializedState._pkfTemplateMeta }
        : null;
    }
  }

  // ══════════════════════════════════════════════════════════════
  //  PKF 公式求值与预览
  // ══════════════════════════════════════════════════════════════

  /**
   * 安全求值 PKF 公式字符串
   * 白名单机制：只允许数字、运算符、括号、Math 函数和已声明的参数名。
   * 拒绝任何可能的代码注入（函数调用、赋值、关键字等）。
   *
   * @param {string} formula     - 公式字符串，如 "stroke * 0.5 + 10"
   * @param {Object} paramValues - 参数名→实际值的映射，如 { stroke: 100, angle: 90 }
   * @returns {{ value: number, error: string|null }}
   *   成功时 value 为计算结果，error 为 null；
   *   失败时 value 为 0，error 为错误描述。
   */
  evaluatePkfFormula() {
    throw new Error('Studio requires the restricted expression adapter');
  }

  /**
   * 根据参数默认值构建参数值映射
   * @returns {Object} 参数名→默认值的映射，如 { stroke: 100, angle: 90 }
   */
  buildDefaultParamValues() {
    const values = {};
    this.pkfParameters.forEach((p) => {
      values[p.id] = p.default ?? 0;
    });
    // schema v6: 注入 cargo 尺寸参数（cargo_width / cargo_height / cargo_depth）
    // 用户在公式里可直接写 "cargo_width / 2 + 0.05"
    Object.assign(values, this.getCargoSizeParams());
    // v14.1 (#37): 叉齿零位锚点参数（fork_anchor_zero_x/y/z）—— 读缓存
    // 缓存由 main.js 🚀 handler 在"关节归零"状态下显式调 computeForkAnchorZero 填充。
    // 这里不主动算，避免每帧读实时场景（运动中场景 ≠ 零位 → 参数会漂，见 #37）。
    Object.assign(values, this.getForkAnchorZero());
    return values;
  }

  /**
   * 预览 PKF：用参数默认值求值所有步骤，在指定时间 t 计算每个关节的目标值
   * 返回每个关节定义 id 对应的驱动值（可用于 applyJointDrive）。
   *
   * @param {number} t           - 当前预览时间（秒）
   * @param {Object} [paramOverrides] - 可选的参数值覆盖（优先于默认值）
   * @returns {Array<{ joint_def_id: string, channel: string, axis: string, value: number, error: string|null }>}
   */
  evaluatePkfAt(t, paramOverrides = {}) {
    const paramValues = { ...this.buildDefaultParamValues(), ...paramOverrides };
    const results = [];

    // 按 t_start 排序：多个步骤驱动同一关节时，时间晚的覆盖时间早的
    const sortedSteps = [...this.pkfSteps].sort((a, b) => a.t_start - b.t_start);

    sortedSteps.forEach((step) => {
      // 未开始的步骤不输出结果（由 applyPkfAtTime 统一重置为 0）
      if (t < step.t_start) return;

      // 计算时间进度 [0, 1]，完成后保持在 1（hold at value_end）
      // 这样循环内部步骤完成后关节不会飘，循环结束时关节保持在动画末态
      const duration = step.t_end - step.t_start;
      let progress;
      if (t >= step.t_end) {
        progress = 1;
      } else {
        progress = duration > 0 ? (t - step.t_start) / duration : 1;
        progress = this._applyEasing(progress, step.easing);
      }

      // 求值起止公式
      const startResult = this.evaluatePkfFormula(step.value_start, paramValues);
      const endResult = this.evaluatePkfFormula(step.value_end, paramValues);

      // 线性插值
      const value = startResult.value + (endResult.value - startResult.value) * progress;
      const error = startResult.error || endResult.error || null;

      results.push({
        step_id: step.id,
        joint_def_id: step.joint_def_id,
        joint: step.joint,
        channel: step.channel,
        axis: step.axis,
        value,
        error,
      });
    });

    return results;
  }

  /**
   * 应用缓动函数，将线性进度 [0,1] 映射为缓动后的进度
   * @param {number} t      - 线性进度 0~1
   * @param {string} easing - 缓动类型
   * @returns {number} 缓动后的进度
   * @private
   */
  _applyEasing(t, easing) {
    switch (easing) {
      case 'ease-in':
        return t * t;                          // 二次缓入
      case 'ease-out':
        return t * (2 - t);                    // 二次缓出
      case 'ease-in-out':
        return t < 0.5                         // 二次缓入缓出
          ? 2 * t * t
          : -1 + (4 - 2 * t) * t;
      case 'linear':
      default:
        return t;
    }
  }
}
