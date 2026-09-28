/**
 * 结果包导出器
 * 将编辑器数据打包为带时间戳的 ZIP 文件，包含 manifest、joints、motion、pkf、model
 *
 * schema_version 历史：
 *  - v1：老格式，joints.json 是关节点（空间锚点）+ joint-definitions.json 是 FK 关节定义
 *  - v2：joints.json 直接存 FK 关节定义；origin 是世界坐标（UI Z-up）
 *  - v3：origin 改为 parent-local（URDF 风格），父节点动 → 关节中心自动跟。
 *       motion.json 是全局关键帧 schema（clips[].keyframes[].joint_values 字典）
 *  - v4：model.glb 由 GLTFExporter 重新序列化当前 sceneRoot，
 *       包含运行时插入的父级 group（onInsertGroup）和其他 reparent 修改。
 *       这样导入时场景树状态完整，joint def 的 parent/child 关系不会丢。
 *  - v5：motion.json clips 加 reparent_events（cargo 在时间轴上换 parent）
 *  - v6：sceneMarkers（货物占位 / 取货点 / 放货点 metadata），pkf（参数化公式）
 *  - v7：joint def 加 limit_upper + overflow_to（双段门架 overflow 机制，bugfix #59）
 */
// #65 bundle 瘦身：JSZip (~90 kB) + GLTFExporter (~60 kB) 都只在导出 ZIP 时用，
// 改动态 import → Vite 切成独立 chunk，首屏 bundle 瘦身 ~150 kB

export class ResultPackageExporter {
  /**
   * 用 GLTFExporter 把当前场景序列化成 GLB ArrayBuffer
   *
   * 关键：不直接导出 sceneRoot（THREE.Scene），而是导出其第一个有意义的子节点
   * （模型的实际根 Group）。原因：
   *   - GLTFExporter 对 Scene 类型节点的处理和 GLTFLoader 不一致
   *   - GLTFLoader 总是在外面包一层新 Scene → roundtrip 多出一层嵌套 → 层级变了
   *   - 只导出 Group 子节点 → GLTFLoader 导入后 gltf.scene.children[0] 就是原始结构
   *
   * @param {THREE.Object3D} sceneRoot - sceneManager.sceneRoot（通常是 THREE.Scene）
   * @returns {Promise<ArrayBuffer>}
   */
  async serializeSceneToGlb(sceneRoot) {
    // 收集 sceneRoot 下所有有意义的子节点（跳过灯光/相机/Helper）
    // 不直接导出 sceneRoot（THREE.Scene），避免 GLTFExporter/GLTFLoader 的 Scene roundtrip 不一致
    // GLTFExporter 支持传入数组：所有子节点作为 GLB 的顶层节点
    // 导入后 gltf.scene.children 就是这些节点，结构与原始一致
    // REVIEW-v15 F28 防御：过滤轨迹 overlay group（UI toggle 的 __isTrajectoryOverlay
    // 和 Console __diagTpl.drawTrajectory 的 __isDiagTrajectory）。即使 caller 忘记 clear，
    // 这里也不烘焙进 GLB。
    const exportTargets = (sceneRoot.children || []).filter(
      (c) => !c.isLight
        && !c.isCamera
        && !c.type?.includes('Helper')
        && !c.userData?.__isTrajectoryOverlay
        && !c.userData?.__isDiagTrajectory,
    );
    // 如果只有一个子节点，直接传对象；多个传数组
    const target = exportTargets.length === 1 ? exportTargets[0] : exportTargets;

    // #65 动态 import GLTFExporter（独立 chunk ~60 kB，首屏不需要）
    const { GLTFExporter } = await import('three/examples/jsm/exporters/GLTFExporter.js');

    return new Promise((resolve, reject) => {
      const exporter = new GLTFExporter();
      exporter.parse(
        target,
        (result) => {
          if (result instanceof ArrayBuffer) {
            resolve(result);
          } else {
            reject(new Error('GLTFExporter 返回非 ArrayBuffer，可能是 binary 选项未生效'));
          }
        },
        (error) => reject(error),
        { binary: true, embedImages: true }, // .glb 二进制 + 嵌入纹理
      );
    });
  }

  /**
   * 导出结果包 ZIP
   * @param {Object} options
   * @param {string}  options.sourceFileName    - 源文件名（仅用于命名 ZIP，不再决定模型扩展名）
   * @param {string}  options.sourceFormat      - 源格式
   * @param {THREE.Object3D} options.sceneRoot  - 当前场景根（v4 起必填，会被序列化为 model.glb）
   * @param {Array}   options.jointDefinitions  - 关节定义数组
   * @param {Array}   options.clips             - 动作片段数据
   * @param {Array}   [options.pkfParameters]   - PKF 参数声明数组
   * @param {Array}   [options.pkfSteps]        - PKF 步骤数组
   * @param {string}  [options.editorName]      - 编辑器名称
   * @returns {Promise<{manifest, joints, motion, pkf}>}
   */
  async exportZip({
    sourceFileName,
    sourceFormat,
    sceneRoot,
    jointDefinitions,
    clips,
    pkfParameters,
    pkfSteps,
    pkfTemplateMeta, // mvp3: 叉车模板路径生成的 PKF 带此 meta；import 时据此还原 runtime 状态禁用 snap-attach
    sceneMarkers,
    editorName = 'MotionForge',
    fps = 30,
  }) {
    if (!sceneRoot) {
      throw new Error('exportZip: sceneRoot 为必填参数（v4 schema）');
    }
    // #65 动态 import JSZip（独立 chunk ~90 kB）
    const { default: JSZip } = await import('jszip');
    const zip = new JSZip();
    const timestamp = this.getTimestamp();
    const manifestFileName = `manifest-${timestamp}.json`;
    const jointsFileName = `joints-${timestamp}.json`;
    const motionFileName = `motion-${timestamp}.json`;
    // PKF 文件：有参数或步骤时才生成
    const hasPkf = (pkfParameters && pkfParameters.length) || (pkfSteps && pkfSteps.length);
    const pkfFileName = hasPkf ? `pkf-${timestamp}.json` : null;

    // v4：模型固定为 .glb（GLTFExporter 输出格式），不管原文件是 fbx/usd 都统一
    const modelFileName = `model-${timestamp}.glb`;

    // schema v6：场景标记（货物占位 / 取货点 / 放货点）含位置 + 类型 + 尺寸
    // markers 同时是 Three.js 对象（已存进 GLB），这里的 metadata 给 type/size/color 等
    // 不存 position：position 已经在 GLB 里（marker 是 sceneRoot 的子对象）
    const markersMetadata = (sceneMarkers || []).map((m) => ({
      id: m.id,
      name: m.name,
      type: m.type,
      size: m.size ? { ...m.size } : null,
      color: m.color || null,
    }));

    const manifest = {
      schema_version: 7,
      generator: editorName,
      exported_at: new Date().toISOString(),
      source: {
        file_name: sourceFileName || 'unknown',
        format: sourceFormat || 'unknown',
        // v5：保存原始场景根节点名（如 FBX 源的 "Scene"），导入时恢复用
        // 修复"parent=root 的关节在 roundtrip 后 parent_name 查不到"的 bug：
        // GLTFExporter/Loader 会把 root.name 改成 AuxScene，之前代码用 file_name
        // 覆盖，导致原来叫 "Scene" 的根在新场景里找不到 → joint.parent_name 失效
        root_name: sceneRoot?.name || null,
        up_axis: 'Z',
        units_in_meters: 1.0,
        fps,
      },
      // v6: 场景标记 metadata（位置/Three.js 对象在 GLB 里，按 name 关联）
      scene_markers: markersMetadata,
      files: {
        manifest: manifestFileName,
        model: modelFileName,
        joints: jointsFileName, // v2: FK 关节定义（取代了 v1 的关节点系统）
        motion: motionFileName,
        pkf: pkfFileName,       // 可为 null
      },
    };

    // joints.json（v2 schema）：FK 关节定义。
    // 每条记录包含：type（revolute/prismatic/fixed）、axis、origin（世界空间）、
    // limits、parent_id、child_id、current_value、base_transform（关节零点姿态）。
    const joints = {
      _comment: 'FK 关节定义。type 决定运动语义；origin 是世界空间旋转/平移参考点（UI Z-up 约定）；base_transform 是关节零点的 parent-local 姿态。',
      definitions: (jointDefinitions || []).map((d) => ({
        id: d.id,
        name: d.name,
        scene_path: d.scenePath || null,
        type: d.type,
        axis: d.axis,
        role: d.role || '', // v6+：语义角色标签（车体前进/门架升降等），AI 按此匹配意图
        origin: { x: d.origin?.x ?? 0, y: d.origin?.y ?? 0, z: d.origin?.z ?? 0 },
        limits: { min: d.limits?.min ?? -180, max: d.limits?.max ?? 180 },
        parent_id: d.parentId,
        parent_name: d.parentName || null,
        child_id: d.childId,
        current_value: d.currentValue ?? 0,
        base_transform: d.baseTransform || null,
        // v7+ 双段门架 overflow（bugfix #59）：limit_upper=null 表示未启用，向后兼容老 ZIP
        // overflow_to 存目标关节 **名字**，跨 roundtrip 稳定（uuid 会变）
        limit_upper: (d.limit_upper != null && Number.isFinite(d.limit_upper)) ? d.limit_upper : null,
        overflow_to: d.overflow_to || null,
      })),
    };

    // motion.json v2 schema：全局动画片段
    // 每个 clip 包含 duration + 全局关键帧数组
    // 每个关键帧含 jointValues 字典：{ jointDefName: number }
    // 不再有 per-object channels，所有关节在同一时间线上同步
    const motion = {
      _comment: 'v5 全局关键帧 + reparent 事件 schema：keyframes[] 驱动 joint_values；reparent_events[] 在指定时间切换对象的 scene graph parent（取货/放货用）。child_name/new_parent_name 用名字跨 roundtrip 稳定。new_parent_name=null 表示挂回世界根。',
      clips: (clips || []).map((clip) => ({
        clip_name: clip.clip_name,
        duration: clip.duration,
        keyframes: (clip.keyframes || []).map((k) => ({
          t: k.t,
          joint_values: { ...(k.joint_values || {}) },
        })),
        // v5: reparent 事件（按 t 排序；child_name/new_parent_name 是名字不是 uuid）
        reparent_events: (clip.reparent_events || []).map((e) => ({
          event_id: e.event_id,
          t: e.t,
          child_name: e.child_name,
          new_parent_name: e.new_parent_name, // null = 世界根
        })),
      })),
    };

    // ── 构建 PKF 数据（参数化关键帧公式）──
    // 注意：step 只序列化 `joint`（关节名字），不写 `joint_def_id`（那是运行时 uuid，
    // 跨导出/导入不稳定）。下游按 joint 名字匹配 joints.json 里的 name 字段即可。
    const pkf = hasPkf
      ? {
          _comment: '参数化关键帧公式：parameters 声明输入参数，steps 定义公式驱动的运动步骤。joint 字段引用 joints.json 的 name。',
          // mvp3：模板路径生成的 PKF 带 template_meta；import 时据此还原 runtime 状态禁用 snap-attach
          // 不是模板路径生成的 PKF 此字段为 null，下游按常规 snap-attach 走（兼容老 ZIP）
          template_meta: pkfTemplateMeta || null,
          parameters: (pkfParameters || []).map((p) => ({
            id: p.id,
            type: p.type || 'number',
            unit: p.unit || '',
            desc: p.desc || '',
            default: p.default ?? 0,
          })),
          steps: (pkfSteps || []).map((s) => ({
            id: s.id,
            joint: s.joint || '', // 关节名字（对应 joints.json 里的 name）
            channel: s.channel || 'translate',
            axis: s.axis || 'z',
            t_start: s.t_start ?? 0,
            t_end: s.t_end ?? 1,
            value_start: s.value_start ?? '0',
            value_end: s.value_end ?? '0',
            easing: s.easing || 'linear',
            // F61: 模板编译产出的段号 / 段名（mvp3），只写非 null 值避免 ZIP 膨胀
            // 导入端按同字段恢复；TrajectoryOverlay / 诊断脚本据此显示段号列
            ...(s.template_segment != null ? { template_segment: s.template_segment } : {}),
            ...(s.template_segment_name != null ? { template_segment_name: s.template_segment_name } : {}),
          })),
        }
      : null;

    zip.file(manifestFileName, JSON.stringify(manifest, null, 2));
    zip.file(jointsFileName, JSON.stringify(joints, null, 2));
    zip.file(motionFileName, JSON.stringify(motion, null, 2));

    // PKF 文件仅在有数据时写入
    if (pkf && pkfFileName) {
      zip.file(pkfFileName, JSON.stringify(pkf, null, 2));
    }

    // v4：用 GLTFExporter 序列化当前 sceneRoot（包含运行时插入的 group / reparent）
    // 这样导入时模型就是用户编辑后的状态，joint def 的 parent/child 关系不会断
    const glbBuffer = await this.serializeSceneToGlb(sceneRoot);
    zip.file(modelFileName, glbBuffer);

    const blob = await zip.generateAsync({ type: 'blob' });
    const safeName = (sourceFileName || 'motionforge').replace(/\.[^/.]+$/, '');
    this.downloadBlob(blob, `${safeName}-motion-package-${timestamp}.zip`);
    return { manifest, joints, motion, pkf };
  }

  getTimestamp() {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${yyyy}${mm}${dd}-${hh}${mi}${ss}`;
  }

  downloadBlob(blob, fileName) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }
}
