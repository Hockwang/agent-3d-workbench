// recipes.js — 配方条 + 配方抽屉：把面板已有的行动作串成预设路线。
// 契约见 SPEC_RECIPES.md §3–§5。这里只读 state.recipe（/api/state）与 GET /api/recipes、GET /api/recipe，
// 所有写操作（用/停用配方、按配方做某一步、一键走完、展开某一行）都经回调交给 app.js 复用现有的 runAction/flow。
// 配方文字（尤其 source:"user" 的第三方配方与 guide_md）一律走 textContent，不拼进未转义的 innerHTML。

import { t } from "./i18n.js";

// Row-key → locale-key suffix. Text itself lives in locales/*.js under
// `recipes.row.*` so a live locale switch also updates already-built labels
// (this map is just which suffix to look up, not the translated string).
const ROW_LABEL_KEY = {
  source: "source", model: "model", split: "split", connect: "connect", joint: "joint", color: "color",
  orient: "orient", arrange: "arrange", export: "export", check: "check", deliver: "deliver",
  // 卡片上的人话标签：输入类型、需要用户自备的外部服务、出处一行。
  inspect_mesh: "inspectMesh", repair_mesh: "repairMesh", simplify_mesh: "simplifyMesh", material: "material", export_mesh: "exportMesh",
  // "wearable-head-shell" 的 workspace:"tasks" 检查行（studio_task/studio_observe 步骤，无对应流水线动作）。
  shell_plan: "shellPlan", shell_build: "shellBuild", shell_geometry: "shellGeometry",
  head_fit: "headFit", sight: "sight", appearance: "appearance",
};

// workspace:"tasks" 检查条目的状态点文案（跟 `mapStepStatusToDotClass` 共享同一套 pass/warn/running/todo 状态，
// 只是这里要给用户看文字而不是颜色点）。
const CHECK_STATUS_KEY = { pass: "pass", warn: "warn", running: "running", todo: "todo" };
function checkStatusText(status) {
  const suffix = CHECK_STATUS_KEY[status];
  return t(suffix ? "recipes.checkStatus." + suffix : "recipes.checkStatus.unknown");
}

// 只有这六行有对应的流水线动作；其余（source/split/connect/joint/color）面板上还没有，恒为 todo。
const ROW_TO_PIPELINE_STEP = {
  model: ["inspect", "load"], orient: ["orient"], arrange: ["arrange"],
  export: ["export"], check: ["check"], deliver: ["send"],
};

const STATUS_TO_DOT = { pass: "ok", warn: "warn", redo: "stale", running: "run", todo: "todo" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Looks up a row's human label; returns null (not the row key) when unknown,
// so callers can decide their own fallback (matches the old `ROW_LABEL[k]`
// lookup semantics, which returned undefined for unknown rows).
function rowLabelText(rowKey) {
  const suffix = ROW_LABEL_KEY[rowKey];
  return suffix ? t("recipes.row." + suffix) : null;
}

/* ------------------------------------------------------------------------ */
/* 纯函数：不依赖 DOM，覆盖测试见 tests/test_recipes_ui.mjs                    */
/* ------------------------------------------------------------------------ */

/**
 * 六个已知行：readiness 状态 + 是否 stale + 是否正在跑，推出这一步在路线小格里的状态。
 * 规则见 SPEC_RECIPES.md §3.3：`pass`/`warn`/`todo` 来自 readiness；该行的流水线步骤在 `stale` 里 → `redo`；
 * `busy.op` 正在跑的就是这一行 → `running`（`busy.op === "prepare"` 时谁都不算 running）。
 * 未知行（source/split/connect/joint/color）恒为 `todo`。
 */
export function deriveStepStatus(row, ctx) {
  const c = ctx || {};
  const pipelineSteps = ROW_TO_PIPELINE_STEP[row];
  if (!pipelineSteps) return "todo";
  if (c.busyOp && c.busyOp !== "prepare" && pipelineSteps.includes(c.busyOp)) return "running";
  if ((c.staleKeys || []).some((k) => pipelineSteps.includes(k))) return "redo";
  return c.readinessStatus === "pass" || c.readinessStatus === "warn" ? c.readinessStatus : "todo";
}

/** 配方步骤状态 → 跟流程行状态点同一套颜色的类名（ok/warn/stale/run/todo）。 */
export function mapStepStatusToDotClass(status) {
  return STATUS_TO_DOT[status] || "todo";
}

/** `recipe.next` 对应的那个步骤对象；没在用配方或已经全部通过时为 null。 */
export function nextStepOf(recipe) {
  if (!recipe || !recipe.next) return null;
  return (recipe.steps || []).find((s) => s.key === recipe.next) || null;
}

/** 「一键走完」只在配方带 one_shot、且除了模型这一行以外都还没做时才出现。 */
export function oneShotVisible(recipe) {
  if (!recipe || !recipe.one_shot) return false;
  return (recipe.steps || []).every((s) => s.row === "model" || s.status === "todo");
}

/**
 * `studio_load` 这一步永远没有文件可给，按钮固定是「去载入模型」并展开对应行；
 * 其余按 `who` 决定：`you` → 展开对应行让人自己定；否则 → 直接按配方跑这一步。
 */
export function stepButtonLabel(step) {
  if (!step) return "";
  // `tool` may carry a `#action` / `#template` suffix (recipes/README.md); button copy keys off the base tool.
  const base = String(step.tool || "").split("#")[0];
  if (base === "studio_load") return t("recipes.stepButton.loadModel");
  if (base === "studio_observe") return t("recipes.stepButton.openAppearanceCompare");
  // Only the wearable-head-shell recipe's `shell-kit` steps get the head-shell-specific
  // copy; every other studio_task step (a hosted operation like `image-to-3d`, or a
  // local template like `assembly-audit`/`joint-coupon`/`removal-audit`) falls through
  // to the generic who-based label below. Keyed off the resolved template/operation
  // (`step.call`, or `step.args.template` for the bare `studio_task` tool the shell-kit
  // recipe uses without a `#` suffix) rather than the step key, which does not identify
  // which recipe a step belongs to.
  if (base === "studio_task" && (step.call?.template ?? step.call?.operation ?? step.args?.template) === "shell-kit") {
    return t(["prepare", "generate"].includes(step.key) ? "recipes.stepButton.adjustShellParams" : "recipes.stepButton.viewCheckResult");
  }
  if (step.who === "you") return t("recipes.stepButton.yourTurn");
  return t("recipes.stepButton.runStep");
}
export function stepButtonAction(step) {
  if (!step) return "open";
  if (String(step.tool || "").split("#")[0] === "studio_load" || step.who === "you") return "open";
  return "run";
}

/** GET /api/recipes 的摘要列表 → {ready, needsTools}，组内顺序照后端给的顺序，不重新排序。 */
export function groupRecipes(list) {
  const ready = [];
  const needsTools = [];
  for (const r of list || []) (r.availability === "ready" ? ready : needsTools).push(r);
  return { ready, needsTools };
}

/** GET /api/recipes 的 `rows` 摘要 → 按 key 查的表，供卡片路线小格判断「面板上有没有这一行」。 */
export function indexRows(rows) {
  const map = {};
  for (const r of rows || []) map[r.key] = r;
  return map;
}

/** 卡片路线小格：这一行现在有没有装在面板上（跟这一行眼下的运行状态无关）。 */
export function rowChipExists(rowKey, rowsIndex) {
  const info = rowsIndex && rowsIndex[rowKey];
  return !!(info && info.exists);
}

const TOOL_LABEL_KEY = {
  studio_connect: "connect", studio_split: "split", studio_check_assembly: "checkAssembly",
  studio_make_coupon: "makeCoupon", studio_add_joint: "addJoint", studio_check_motion: "checkMotion",
  studio_color_split: "colorSplit", studio_check_printability: "checkPrintability", studio_generate: "generate",
};
export function formatMissingTools(list) {
  const names = (list || []).map((name) => {
    const suffix = TOOL_LABEL_KEY[name];
    return suffix ? t("recipes.tool." + suffix) : name;
  });
  return t("recipes.missingTools", { names: names.join(t("common.listSeparator")) });
}

export function progressLabel(recipe) {
  if (!recipe) return "";
  return `${recipe.done} / ${recipe.total}`;
}

/* ------------------------------------------------------------------------ */
/* 组件                                                                      */
/* ------------------------------------------------------------------------ */

const INPUT_LABEL_KEY = { mesh: "mesh", mesh_set: "meshSet", labels: "labels", cut_plan: "cutPlan", image: "image", urdf: "urdf" };
const BACKEND_LABEL_KEY = { image_to_3d: "imageTo3d", segmentation: "segmentation", llm: "llm" };
export function inputLabel(key) {
  const suffix = INPUT_LABEL_KEY[key];
  return suffix ? t("recipes.input." + suffix) : String(key);
}
export function backendLabel(key) {
  const suffix = BACKEND_LABEL_KEY[key];
  return suffix ? t("recipes.backend." + suffix) : t("recipes.backend.generic", { name: String(key) });
}
export function rowLabelOf(rowKey, rowsIndex) {
  const row = !rowsIndex ? null : typeof rowsIndex.get === "function" ? rowsIndex.get(rowKey) : rowsIndex[rowKey];
  return (row && row.label) || rowLabelText(rowKey) || String(rowKey);
}
export function provenanceLine(prov) {
  if (!prov) return "";
  const parts = [t("recipes.provenanceLabel"), prov.date, prov.note || prov.ref].filter(Boolean);
  return parts.join(" · ");
}

export class Recipes {
  constructor(callbacks) {
    this.cb = callbacks || {};
    this.abort = new AbortController(); this.disposed = false; this.positionFrame = null; this.renderStamp = null;
    this.root = document.getElementById("recipe");
    this.available = null; // null=还没问过后端；true=GET /api/recipes 正常；false=404/出错（旧后端）→ 整块隐藏
    this.catalog = null; // {recipes, rows, problems}（摘要，供抽屉用）
    this.rowsIndex = {};
    this.drawerOpen = false;
    this._guideCache = new Map();
    this._lastFocused = null;
    this.root.hidden = true;
    this._build();
    // 首次取目录由 app.js 在会话令牌就绪之后调 start()；构造时就取会先吃一个 403 再重试。
    if (this.cb.autoStart !== false) this._refreshCatalog();
  }

  /** @param {object|null} state  /api/state 的返回（可能没有 .recipe 字段，视为没在用配方） */
  render(state) {
    if (this.available !== true) {
      this.root.hidden = true;
      return;
    }
    this.root.hidden = false;
    const s = state || {};
    const stamp = JSON.stringify([s.recipe || null, !!s.busy]);
    if (stamp === this.renderStamp) return;
    this.renderStamp = stamp;
    this._renderBar(s.recipe || null, !!s.busy);
  }

  // ------------------------------------------------------------ 构建 DOM
  _build() {
    this.root.innerHTML =
      '<div class="recipe-row1">' +
      `<span class="recipe-label">${t("recipes.label")}</span>` +
      `<span class="recipe-idle-hint" data-idle-hint>${t("recipes.idleHint")}</span>` +
      '<div class="recipe-active" data-active hidden>' +
      '<span class="recipe-title" data-title></span>' +
      '<div class="recipe-route" data-route></div>' +
      '<span class="recipe-progress" data-progress></span>' +
      "</div>" +
      '<span class="recipe-grow"></span>' +
      `<button type="button" class="btn-mini" data-pick>${t("recipes.pickButton")}</button>` +
      `<button type="button" class="btn-mini" data-switch hidden>${t("recipes.switchButton")}</button>` +
      `<button type="button" class="btn-mini" data-stop hidden>${t("recipes.stopButton")}</button>` +
      "</div>" +
      '<div class="recipe-row2" data-row2 hidden>' +
      '<span class="recipe-next-text" data-next-text></span>' +
      '<span class="recipe-grow"></span>' +
      `<button type="button" class="btn-mini" data-oneshot hidden>${t("recipes.oneShotButton")}</button>` +
      '<button type="button" class="btn-secondary recipe-next-btn" data-next-btn></button>' +
      "</div>" +
      `<details class="recipe-checks" data-checks hidden><summary>${t("recipes.checksTitle")}</summary><p data-scope></p><div data-check-list></div></details>` +
      '<div class="recipe-drawer" data-drawer hidden>' +
      '<div class="recipe-drawer-backdrop" data-backdrop></div>' +
      `<div class="recipe-drawer-panel" role="dialog" aria-modal="true" aria-label="${t("recipes.pickButton")}">` +
      '<div class="recipe-drawer-head">' +
      `<h3>${t("recipes.pickButton")}</h3>` +
      `<button type="button" class="recipe-drawer-close" data-close aria-label="${t("common.close")}">` +
      '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>' +
      "</button>" +
      "</div>" +
      '<div class="recipe-drawer-body" data-body></div>' +
      '<div class="recipe-drawer-problems" data-problems hidden></div>' +
      "</div>" +
      "</div>";

    this.$ = {
      idleHint: this.root.querySelector("[data-idle-hint]"),
      active: this.root.querySelector("[data-active]"),
      title: this.root.querySelector("[data-title]"),
      route: this.root.querySelector("[data-route]"),
      progress: this.root.querySelector("[data-progress]"),
      pick: this.root.querySelector("[data-pick]"),
      switchBtn: this.root.querySelector("[data-switch]"),
      stop: this.root.querySelector("[data-stop]"),
      row2: this.root.querySelector("[data-row2]"),
      nextText: this.root.querySelector("[data-next-text]"),
      nextBtn: this.root.querySelector("[data-next-btn]"),
      oneshot: this.root.querySelector("[data-oneshot]"),
      drawer: this.root.querySelector("[data-drawer]"),
      backdrop: this.root.querySelector("[data-backdrop]"),
      body: this.root.querySelector("[data-body]"),
      problems: this.root.querySelector("[data-problems]"),
      close: this.root.querySelector("[data-close]"),
      checks: this.root.querySelector("[data-checks]"),
      checkList: this.root.querySelector("[data-check-list]"),
      scope: this.root.querySelector("[data-scope]"),
    };

    this.$.pick.addEventListener("click", () => this._openDrawer());
    this.$.switchBtn.addEventListener("click", () => this._openDrawer());
    this.$.stop.addEventListener("click", () => this._use(null, this.$.stop));
    this.$.close.addEventListener("click", () => this._closeDrawer());
    this.$.backdrop.addEventListener("click", () => this._closeDrawer());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.drawerOpen) this._closeDrawer();
    }, { signal: this.abort.signal });
    const reposition = () => {
      if (!this.drawerOpen || this.positionFrame != null) return;
      this.positionFrame = requestAnimationFrame(() => { this.positionFrame = null; if (!this.disposed) this._positionDrawer(); });
    };
    window.addEventListener("resize", reposition, { signal: this.abort.signal });
    if (typeof ResizeObserver === "function") {
      this.observer = new ResizeObserver(reposition);
      this.observer.observe(document.getElementById("wb"));
    }
  }

  // ------------------------------------------------------------ 配方条
  _renderBar(recipe, busy) {
    const active = !!recipe;
    this.$.idleHint.hidden = active;
    this.$.active.hidden = !active;
    this.$.pick.hidden = active;
    this.$.switchBtn.hidden = !active;
    this.$.stop.hidden = !active;
    this.$.switchBtn.disabled = busy;
    this.$.stop.disabled = busy;

    this.$.checks.hidden = recipe?.workspace !== "tasks";
    this.$.checkList.replaceChildren();
    if (recipe?.workspace === "tasks") {
      this.$.scope.textContent = [recipe.task_title, recipe.scope_note].filter(Boolean).join(" · ");
      for (const step of recipe.steps || []) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "recipe-check-item";
        button.disabled = busy;
        button.textContent = t("recipes.checkItemLine", {
          row: rowLabelText(step.row) || step.row,
          status: checkStatusText(step.status),
          detail: step.detail || step.decide,
        });
        button.onclick = () => this.cb.onOpenRow?.(step.row, step);
        this.$.checkList.append(button);
      }
    }

    if (!active) {
      this.$.row2.hidden = true;
      return;
    }

    this.$.title.textContent = recipe.title;
    this.$.progress.textContent = progressLabel(recipe);
    this.$.route.innerHTML = "";
    for (const step of recipe.steps || []) {
      const chip = document.createElement("span");
      chip.className = "recipe-chip is-" + mapStepStatusToDotClass(step.status);
      chip.title = t("recipes.rowStatusTitle", { row: rowLabelText(step.row) || step.row, status: step.detail || step.status });
      this.$.route.appendChild(chip);
    }

    this.$.row2.hidden = false;
    const next = nextStepOf(recipe);
    if (!next) {
      this.$.nextText.textContent =
        recipe.workspace === "tasks"
          ? t("recipes.tasksStepsDone")
          : recipe.workspace === "edit"
            ? t("recipes.stepsDoneCheckExport")
            : t("recipes.routeFinished");
      this.$.nextBtn.hidden = true;
      this.$.oneshot.hidden = true;
      return;
    }
    this.$.nextText.innerHTML = t("recipes.nextStepLine", {
      row: esc(rowLabelText(next.row) || next.row),
      decide: esc(next.detail || next.decide || ""),
    });
    this.$.nextText.title = recipe.task_title ? t("recipes.checkVersionTooltip", { title: recipe.task_title, scope: recipe.scope_note }) : "";
    this.$.nextBtn.hidden = false;
    this.$.nextBtn.disabled = busy;
    this.$.nextBtn.textContent = stepButtonLabel(next);
    this.$.nextBtn.onclick = () => {
      if (stepButtonAction(next) === "open") this.cb.onOpenRow && this.cb.onOpenRow(next.row, next);
      else this.cb.onRunStep && this.cb.onRunStep(next);
    };
    const showOneShot = oneShotVisible(recipe);
    this.$.oneshot.hidden = !showOneShot;
    this.$.oneshot.disabled = busy;
    if (showOneShot) this.$.oneshot.onclick = () => this.cb.onRunOneShot && this.cb.onRunOneShot(recipe);
  }

  // ------------------------------------------------------------ 用 / 停用
  async _use(id, btn) {
    if (btn) btn.disabled = true;
    try {
      const ok = await (this.cb.onUse && this.cb.onUse(id));
      if (ok !== false) this._closeDrawer();
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ------------------------------------------------------------ 抽屉：开关 + 定位
  _openDrawer() {
    this._lastFocused = document.activeElement;
    this.drawerOpen = true;
    this.$.drawer.hidden = false;
    this._positionDrawer();
    this._refreshCatalog(); // 每次打开重新扫描，用户往 ~/.print-prep/recipes/ 里放的新配方不用重启就能看到
    const first = this.$.body.querySelector("button, [tabindex]");
    (first || this.$.close).focus();
  }
  _closeDrawer() {
    this.drawerOpen = false;
    this.$.drawer.hidden = true;
    if (this._lastFocused && typeof this._lastFocused.focus === "function") this._lastFocused.focus();
  }
  _positionDrawer() {
    const bounds = document.getElementById("wb").getBoundingClientRect();
    const width = Math.min(520, bounds.width);
    Object.assign(this.$.drawer.style, { top: bounds.top + "px", left: (bounds.right - width) + "px", width: width + "px", height: bounds.height + "px" });
  }

  // ------------------------------------------------------------ 抽屉：配方目录
  async _refreshCatalog() {
    try {
      const res = this.cb.loadList ? await this.cb.loadList() : null;
      this.catalog = { recipes: (res && res.recipes) || [], rows: (res && res.rows) || [], problems: (res && res.problems) || [] };
      this.rowsIndex = indexRows(this.catalog.rows);
      this.available = true;
    } catch (e) {
      this.available = false;
      this.catalog = null;
    }
    if (this.disposed) return;
    this._guideCache.clear();
    this._renderDrawerCatalog();
    this.root.hidden = this.available !== true;
  }

  _renderDrawerCatalog() {
    const body = this.$.body;
    body.innerHTML = "";
    const catalog = this.catalog || { recipes: [], rows: [], problems: [] };
    const { ready, needsTools } = groupRecipes(catalog.recipes);
    body.appendChild(this._buildGroup(t("recipes.group.ready"), ready, true));
    body.appendChild(this._buildGroup(t("recipes.group.needsTools"), needsTools, false));

    const problems = catalog.problems || [];
    this.$.problems.hidden = !problems.length;
    this.$.problems.innerHTML = "";
    if (!problems.length) return;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "recipe-problems-toggle";
    toggle.textContent = t("recipes.problemsToggle", { count: problems.length });
    const list = document.createElement("ul");
    list.className = "recipe-problems-list";
    list.hidden = true;
    for (const p of problems) {
      const li = document.createElement("li");
      li.textContent = t("recipes.problemLine", { dir: p.dir, error: p.error });
      list.appendChild(li);
    }
    toggle.addEventListener("click", () => {
      list.hidden = !list.hidden;
    });
    this.$.problems.appendChild(toggle);
    this.$.problems.appendChild(list);
  }

  _buildGroup(label, list, isReady) {
    const wrap = document.createElement("div");
    wrap.className = "recipe-group";
    const h = document.createElement("h4");
    h.className = "recipe-group-title";
    h.textContent = t("recipes.groupTitle", { label, count: list.length });
    wrap.appendChild(h);
    if (!list.length) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = isReady ? t("recipes.group.emptyReady") : t("recipes.group.emptyNeedsTools");
      wrap.appendChild(p);
      return wrap;
    }
    const grid = document.createElement("div");
    grid.className = "recipe-card-grid";
    for (const r of list) grid.appendChild(this._buildCard(r));
    wrap.appendChild(grid);
    return wrap;
  }

  _buildCard(r) {
    const card = document.createElement("div");
    card.className = "recipe-card";

    const title = document.createElement("button");
    title.type = "button";
    title.className = "recipe-card-title";
    title.textContent = r.title;
    title.setAttribute("aria-expanded", "false");
    const guideBox = document.createElement("pre");
    guideBox.className = "recipe-card-guide";
    guideBox.hidden = true;
    title.addEventListener("click", () => this._toggleGuide(r.id, title, guideBox));
    card.appendChild(title);

    const goal = document.createElement("p");
    goal.className = "recipe-card-goal";
    goal.textContent = r.goal || "";
    card.appendChild(goal);

    const route = document.createElement("div");
    route.className = "recipe-route recipe-route-static";
    for (const rowKey of r.route || []) {
      const chip = document.createElement("span");
      const exists = rowChipExists(rowKey, this.rowsIndex);
      chip.className = "recipe-step-name " + (exists ? "is-exists" : "is-missing");
      chip.textContent = rowLabelOf(rowKey, this.rowsIndex);
      if (!exists) chip.title = t("recipes.rowNotOnPanel");
      route.appendChild(chip);
    }
    card.appendChild(route);

    const badges = document.createElement("div");
    badges.className = "recipe-badges";
    for (const inp of r.inputs || []) badges.appendChild(this._badge(inputLabel(inp)));
    for (const be of r.backends || []) badges.appendChild(this._badge(backendLabel(be)));
    if (r.source === "user") badges.appendChild(this._badge(t("recipes.badge.thirdParty")));
    card.appendChild(badges);

    const prov = (r.provenance || [])[0];
    if (prov) {
      const p = document.createElement("p");
      p.className = "recipe-card-provenance";
      p.textContent = provenanceLine(prov);
      p.title = prov.ref || "";
      card.appendChild(p);
    }

    card.appendChild(guideBox);

    const foot = document.createElement("div");
    foot.className = "recipe-card-foot";
    if (r.availability === "ready") {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-secondary";
      btn.textContent = t("recipes.useThisRecipeButton");
      btn.addEventListener("click", () => this._use(r.id, btn));
      foot.appendChild(btn);
    } else {
      const span = document.createElement("span");
      span.className = "hint recipe-missing-hint";
      span.textContent = formatMissingTools(r.missing_tools);
      foot.appendChild(span);
    }
    card.appendChild(foot);
    return card;
  }

  _badge(text) {
    const span = document.createElement("span");
    span.className = "recipe-badge";
    span.textContent = text;
    return span;
  }

  dispose() {
    this.disposed = true; this.abort.abort(); this.observer?.disconnect();
    if (this.positionFrame != null) cancelAnimationFrame(this.positionFrame);
  }

  /** 会话令牌就绪后由 app.js 调一次：取配方目录，决定整块要不要显示。 */
  start() {
    return this._refreshCatalog();
  }

  async _toggleGuide(id, titleBtn, box) {
    const willShow = box.hidden;
    box.hidden = !willShow;
    titleBtn.setAttribute("aria-expanded", String(willShow));
    if (!willShow) return;
    if (this._guideCache.has(id)) {
      box.textContent = this._guideCache.get(id);
      return;
    }
    box.textContent = t("common.loading");
    try {
      const res = this.cb.loadRecipe ? await this.cb.loadRecipe(id) : null;
      const text = (res && res.recipe && res.recipe.guide_md) || "";
      this._guideCache.set(id, text);
      box.textContent = text;
    } catch (e) {
      box.textContent = t("recipes.guideLoadFailed", { detail: e && e.message ? e.message : String(e) });
    }
  }
}
