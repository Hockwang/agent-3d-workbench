import assert from "node:assert/strict";
import test from "node:test";

// recipes.js 定义 class Recipes（依赖 document），但这里只测不依赖 DOM 的具名导出函数；
// 直接动态 import 真实文件（而非 test_webmcp.mjs 曾用的 data: URL 技巧——recipes.js 现在
// import 了 ./i18n.js，data: URL 模块没有真实 base，解析不了相对 import）。
// 文件顶层不触碰 document，class 方法体里的 document 用法在这些测试里不会被执行到。
const {
  deriveStepStatus,
  mapStepStatusToDotClass,
  nextStepOf,
  oneShotVisible,
  stepButtonLabel,
  stepButtonAction,
  groupRecipes,
  indexRows,
  rowChipExists,
  formatMissingTools,
  progressLabel,
} = await import(new URL("../studio/web/recipes.js", import.meta.url));

// ------------------------------------------------------------- deriveStepStatus

test("deriveStepStatus: 未知行（source/split/connect/joint/color）恒为 todo", () => {
  for (const row of ["source", "split", "connect", "joint", "color"]) {
    assert.equal(deriveStepStatus(row, { readinessStatus: "pass", staleKeys: ["inspect"], busyOp: "load" }), "todo");
  }
});

test("deriveStepStatus: readiness 的 pass/warn/todo 原样传递", () => {
  assert.equal(deriveStepStatus("model", { readinessStatus: "pass" }), "pass");
  assert.equal(deriveStepStatus("orient", { readinessStatus: "warn" }), "warn");
  assert.equal(deriveStepStatus("arrange", { readinessStatus: "todo" }), "todo");
  assert.equal(deriveStepStatus("check", {}), "todo"); // 没给 readinessStatus 时兜底 todo
});

test("deriveStepStatus: 该行的流水线步骤出现在 stale 里 → redo，优先于 readiness", () => {
  assert.equal(deriveStepStatus("arrange", { readinessStatus: "pass", staleKeys: ["arrange"] }), "redo");
  assert.equal(deriveStepStatus("export", { readinessStatus: "todo", staleKeys: ["export", "check"] }), "redo");
  assert.equal(deriveStepStatus("check", { readinessStatus: "pass", staleKeys: ["arrange"] }), "pass"); // 别行 stale 不影响本行
});

test("deriveStepStatus: busy.op 正在跑的就是这一行 → running，优先于 stale 与 readiness", () => {
  assert.equal(deriveStepStatus("orient", { readinessStatus: "pass", staleKeys: ["orient"], busyOp: "orient" }), "running");
  assert.equal(deriveStepStatus("model", { readinessStatus: "todo", busyOp: "load" }), "running"); // model 行同时对应 inspect/load
  assert.equal(deriveStepStatus("deliver", { busyOp: "send" }), "running");
});

test("deriveStepStatus: busy.op === 'prepare' 时谁都不算 running", () => {
  assert.equal(deriveStepStatus("orient", { readinessStatus: "todo", busyOp: "prepare" }), "todo");
  assert.equal(deriveStepStatus("check", { readinessStatus: "pass", busyOp: "prepare" }), "pass");
});

// ------------------------------------------------------------- mapStepStatusToDotClass

test("mapStepStatusToDotClass: 五种状态映射到流程行同款颜色类名，未知状态兜底 todo", () => {
  assert.equal(mapStepStatusToDotClass("pass"), "ok");
  assert.equal(mapStepStatusToDotClass("warn"), "warn");
  assert.equal(mapStepStatusToDotClass("redo"), "stale");
  assert.equal(mapStepStatusToDotClass("running"), "run");
  assert.equal(mapStepStatusToDotClass("todo"), "todo");
  assert.equal(mapStepStatusToDotClass("nonsense"), "todo");
  assert.equal(mapStepStatusToDotClass(undefined), "todo");
});

// ------------------------------------------------------------- nextStepOf

test("nextStepOf: 按 recipe.next 的 key 取对应步骤对象", () => {
  const recipe = { next: "orient", steps: [{ key: "load", row: "model" }, { key: "orient", row: "orient" }] };
  assert.deepEqual(nextStepOf(recipe), { key: "orient", row: "orient" });
});

test("nextStepOf: next 为 null（全部通过）或没在用配方 → null", () => {
  assert.equal(nextStepOf({ next: null, steps: [{ key: "load" }] }), null);
  assert.equal(nextStepOf(null), null);
});

test("nextStepOf: next 指向一个 steps 里找不到的 key → null（不抛异常）", () => {
  assert.equal(nextStepOf({ next: "ghost", steps: [{ key: "load" }] }), null);
});

// ------------------------------------------------------------- oneShotVisible

test("oneShotVisible: 没有 one_shot → 恒不显示", () => {
  assert.equal(oneShotVisible({ one_shot: null, steps: [{ row: "model", status: "todo" }] }), false);
  assert.equal(oneShotVisible(null), false);
});

test("oneShotVisible: 带 one_shot 且除模型行外都还没做 → 显示", () => {
  const recipe = {
    one_shot: { tool: "studio_prepare", args: {} },
    steps: [
      { row: "model", status: "pass" },
      { row: "orient", status: "todo" },
      { row: "arrange", status: "todo" },
    ],
  };
  assert.equal(oneShotVisible(recipe), true);
});

test("oneShotVisible: 模型以外任一步骤已经不是 todo（pass/warn/redo/running）→ 不显示", () => {
  const base = { one_shot: { tool: "studio_prepare", args: {} } };
  assert.equal(oneShotVisible(Object.assign({}, base, { steps: [{ row: "model", status: "pass" }, { row: "orient", status: "pass" }] })), false);
  assert.equal(oneShotVisible(Object.assign({}, base, { steps: [{ row: "model", status: "todo" }, { row: "orient", status: "redo" }] })), false);
});

// ------------------------------------------------------------- stepButtonLabel / stepButtonAction

test("stepButtonLabel/Action: studio_load 恒为「去载入模型」+ open，不管 who 是什么", () => {
  for (const who of ["either", "ai", "you"]) {
    const step = { tool: "studio_load", who };
    assert.equal(stepButtonLabel(step), "去载入模型");
    assert.equal(stepButtonAction(step), "open");
  }
});

test("stepButtonLabel/Action: who=you 且非 studio_load →「这一步要你来定」+ open", () => {
  const step = { tool: "studio_check", who: "you" };
  assert.equal(stepButtonLabel(step), "这一步要你来定");
  assert.equal(stepButtonAction(step), "open");
});

test("stepButtonLabel/Action: who=ai/either 且非 studio_load →「按配方做这一步」+ run", () => {
  for (const who of ["ai", "either"]) {
    const step = { tool: "studio_orient", who };
    assert.equal(stepButtonLabel(step), "按配方做这一步");
    assert.equal(stepButtonAction(step), "run");
  }
});

test("stepButtonLabel/Action: 空步骤不抛异常", () => {
  assert.equal(stepButtonLabel(null), "");
  assert.equal(stepButtonAction(null), "open");
  assert.equal(stepButtonAction(undefined), "open");
});

// ------------------------------------------------------------- groupRecipes

test("groupRecipes: 按 availability 分两组，组内顺序照给定顺序不重排", () => {
  const list = [
    { id: "a", availability: "ready" },
    { id: "b", availability: "needs_tools" },
    { id: "c", availability: "ready" },
    { id: "d", availability: "needs_tools" },
  ];
  const { ready, needsTools } = groupRecipes(list);
  assert.deepEqual(ready.map((r) => r.id), ["a", "c"]);
  assert.deepEqual(needsTools.map((r) => r.id), ["b", "d"]);
});

test("groupRecipes: 空列表/未传 → 两组都是空数组", () => {
  assert.deepEqual(groupRecipes([]), { ready: [], needsTools: [] });
  assert.deepEqual(groupRecipes(undefined), { ready: [], needsTools: [] });
});

// ------------------------------------------------------------- indexRows / rowChipExists

test("indexRows + rowChipExists: 按 key 查表，缺失的行按不存在处理", () => {
  const rows = [{ key: "model", label: "模型", exists: true }, { key: "split", label: "拆件", exists: false }];
  const idx = indexRows(rows);
  assert.equal(rowChipExists("model", idx), true);
  assert.equal(rowChipExists("split", idx), false);
  assert.equal(rowChipExists("joint", idx), false); // 表里压根没有这一行
  assert.equal(rowChipExists("model", indexRows(undefined)), false);
});

// ------------------------------------------------------------- formatMissingTools / progressLabel

test("formatMissingTools: 显示能力名称；空列表也不抛异常", () => {
  assert.equal(formatMissingTools(["studio_split", "studio_connect"]), "还缺：语义分件、定位销与孔");
  assert.equal(formatMissingTools([]), "还缺：");
  assert.equal(formatMissingTools(undefined), "还缺：");
});

test("progressLabel: 「done / total」；没在用配方为空字符串", () => {
  assert.equal(progressLabel({ done: 3, total: 6 }), "3 / 6");
  assert.equal(progressLabel(null), "");
});

// ------------------------------------------------------------- 头壳配方（workspace: "tasks"）步骤按钮

test("头壳步骤打开参数或检查入口，不直接从配方启动无输入任务", () => {
  for (const key of ["prepare", "generate", "geometry", "head_fit", "sight"]) {
    // wearable-head-shell 的 steps[].tool 是裸 "studio_task"（没有 "#" 后缀），
    // 靠 args.template === "shell-kit" 标出这是哪个模板（recipes/wearable-head-shell/recipe.json）。
    const step = { key, tool: "studio_task", who: "you", args: { action: "start", template: "shell-kit" } };
    assert.equal(stepButtonAction(step), "open");
    assert.equal(stepButtonLabel(step), ["prepare", "generate"].includes(key) ? "调整头壳参数" : "查看检查结果");
  }
  assert.equal(stepButtonLabel({ key: "appearance", tool: "studio_observe", who: "you" }), "打开外观对照");
});

// ------------------------------------------------------------- 非头壳 studio_task 步骤（#后缀）按钮

test("非 shell-kit 的 studio_task 步骤（generate/checkFit 等）走通用 who 标签，不套用头壳文案", () => {
  // image-to-print 的 "generate" 步骤：studio_task#image-to-3d（托管操作），key 恰好也叫 generate，
  // 但不是 shell-kit，不该显示「调整头壳参数」。
  const generate = {
    key: "generate", tool: "studio_task#image-to-3d", who: "either",
    args: { action: "start" }, call: { tool: "studio_task", operation: "image-to-3d" },
  };
  assert.equal(stepButtonLabel(generate), "按配方做这一步");
  assert.equal(stepButtonAction(generate), "run");

  // mechanical-joints/poseable-figure 的 "check_fit" 步骤：studio_task#assembly-audit（本地模板）。
  const checkFit = {
    key: "check_fit", tool: "studio_task#assembly-audit", who: "ai",
    args: { action: "start", template: "assembly-audit" },
    call: { tool: "studio_task", template: "assembly-audit" },
  };
  assert.equal(stepButtonLabel(checkFit), "按配方做这一步");
  assert.equal(stepButtonAction(checkFit), "run");

  // test-coupon-first 的 "coupon" 步骤：studio_task#joint-coupon，who=you → 走「这一步要你来定」。
  const coupon = {
    key: "coupon", tool: "studio_task#joint-coupon", who: "you",
    args: { action: "start", template: "joint-coupon" },
    call: { tool: "studio_task", template: "joint-coupon" },
  };
  assert.equal(stepButtonLabel(coupon), "这一步要你来定");
  assert.equal(stepButtonAction(coupon), "open");
});
