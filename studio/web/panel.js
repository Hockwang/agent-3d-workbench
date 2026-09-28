// panel.js — 右侧「打印计划」栏 + 视口上的悬浮卡：摆盘设置 / 模型 / 选中零件。
// 只负责收集表单输入、把动作回调交给 app.js、以及把最新 state 渲染回界面。
// 写操作是否置灰统一看 state.busy 是否非空（服务端单飞语义）。

import { t } from "./i18n.js";

function el(id) {
  return document.getElementById(id);
}

function fmtNum(v, digits) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toFixed(digits === undefined ? 1 : digits);
}

function fmtVec(v) {
  if (!v) return "—";
  return "[" + v.map((x) => fmtNum(x, 3)).join(", ") + "]";
}

function fmtSeconds(s) {
  if (s === null || s === undefined) return "—";
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.round((total % 3600) / 60);
  return t("panel.format.duration", { h, m });
}

function fmtFaces(n) {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  if (Number.isNaN(v)) return String(n);
  if (v >= 10000) return t("panel.format.facesWan", { wan: (v / 10000).toFixed(1), k: Math.round(v / 1000) });
  return t("panel.format.facesCount", { n: v });
}

function basename(p) {
  if (!p) return "";
  const parts = String(p).replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] || p;
}

const SHAPE_LABELS = () => ({
  generic: t("panel.shape.generic"),
  figurine: t("panel.shape.figurine"),
  relief: t("panel.shape.relief"),
  mechanical: t("panel.shape.mechanical"),
});
const STRATEGY_LABELS = () => ({
  auto: t("panel.strategy.auto"),
  flat: t("panel.strategy.flat"),
  support: t("panel.strategy.support"),
  upright: t("panel.strategy.upright"),
});
const MODE_LABELS = () => ({ single: t("panel.mode.single"), per_part: t("panel.mode.perPart"), auto: t("panel.mode.auto") });

// 「打印增强」清单的键名翻译表；表里没有的键原样显示（key 当 label、value 原样）。
const OVERRIDE_KEY_LABELS = () => ({
  enable_support: t("panel.override.key.enableSupport"),
  support_type: t("panel.override.key.supportType"),
  support_on_build_plate_only: t("panel.override.key.supportOnBuildPlateOnly"),
  brim_type: t("panel.override.key.brimType"),
  brim_width: t("panel.override.key.brimWidth"),
  wall_loops: t("panel.override.key.wallLoops"),
  sparse_infill_density: t("panel.override.key.sparseInfillDensity"),
});

function formatOverrideValue(key, raw) {
  const v = String(raw);
  switch (key) {
    case "enable_support":
      return v === "1" || v === "true" ? t("panel.override.value.enabled") : t("panel.override.value.off");
    case "support_type":
      if (v === "tree(auto)") return t("panel.override.value.supportTree");
      if (v === "normal(auto)") return t("panel.override.value.supportNormal");
      return v;
    case "support_on_build_plate_only":
      return v === "1" || v === "true" ? t("panel.override.value.bedOnly") : t("panel.override.value.onModel");
    case "brim_type":
      return v === "outer_only" ? t("panel.override.value.outerOnly") : v;
    case "brim_width":
      return t("panel.format.brimWidth", { v });
    default:
      return v;
  }
}

const DEFAULT_PRINTER = "Bambu Lab P1S 0.4 nozzle";

// 后端给的是代码，界面上给人看中文；没登记的代码原样显示。
const WARNING_LABELS = () => ({
  unstable_contact: t("panel.warning.unstableContact"),
});
const STRATEGY_USED_LABELS = () => ({
  flat: t("panel.strategy.flat"),
  support: t("panel.strategy.support"),
  upright: t("panel.strategy.upright"),
  manual: t("panel.strategy.manual"),
});

// -------------------------------------------------------------- 分段控件 / 单选卡
// 原生 <select> 继续是唯一真值；这里只是给它套一层按钮皮肤。
// variant "segment"：等宽分段按钮（形态 / 分盘策略）。
// variant "cards"：2×2 单选卡，标题取 option 文本，说明取 option 的 data-desc（朝向策略）。
function bindChoice(selectId, containerId, opts) {
  const variant = (opts && opts.variant) || "segment";
  const select = el(selectId);
  const container = el(containerId);

  function build() {
    container.innerHTML = "";
    container.setAttribute("role", "radiogroup");
    [...select.options].forEach((opt) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "radio");
      btn.dataset.value = opt.value;
      if (variant === "cards") {
        btn.className = "choice-card";
        const dot = document.createElement("span");
        dot.className = "choice-card-dot";
        const text = document.createElement("span");
        text.className = "choice-card-text";
        const title = document.createElement("span");
        title.className = "choice-card-title";
        title.textContent = opt.textContent;
        const desc = document.createElement("span");
        desc.className = "choice-card-desc";
        desc.textContent = opt.dataset.desc || "";
        text.appendChild(title);
        text.appendChild(desc);
        btn.appendChild(dot);
        btn.appendChild(text);
      } else {
        btn.className = "choice-seg";
        // 分段按钮位置窄：option 上有 data-short 就用短标签，完整名字放进 title。
        btn.textContent = opt.dataset.short || opt.textContent;
        if (opt.dataset.short) btn.title = opt.textContent;
      }
      btn.addEventListener("click", () => {
        if (select.value === opt.value) return;
        select.value = opt.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      container.appendChild(btn);
    });
    refresh();
  }

  function refresh() {
    const v = select.value;
    [...container.children].forEach((btn) => {
      const active = btn.dataset.value === v;
      btn.classList.toggle("is-selected", active);
      btn.setAttribute("aria-checked", String(active));
    });
  }

  select.addEventListener("change", refresh);
  build();
  return { refresh, build };
}

export class Panel {
  constructor(opts) {
    this.opts = opts || {};
    this._overrides = []; // [{key, value}]
    this._printers = [];
    this._shapes = []; // GET /api/shapes 的结果，见 §9；失败或未支持时保持 []
    this._selectedName = null;
    this._lastState = null;
    this._bindDom();
  }

  setPrinters(printers) {
    this._printers = printers || [];
    const sel = el("printer-select");
    const prev = sel.value;
    sel.innerHTML = "";
    for (const p of this._printers) {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = p.name;
      sel.appendChild(opt);
    }
    if (prev && this._printers.some((p) => p.name === prev)) sel.value = prev;
    else if (this._printers.some((p) => p.name === DEFAULT_PRINTER)) sel.value = DEFAULT_PRINTER;
    this._renderPrinterRow();
  }

  setShapes(list) {
    this._shapes = Array.isArray(list) ? list : [];
    this._renderShapeEnhance();
  }

  _syncControl(id, value) {
    if (value === null || value === undefined || value === "") return;
    if (!this._synced) this._synced = {};
    if (this._synced[id] === value) return;
    const node = el(id);
    if (node.tagName === "SELECT" && ![...node.options].some((o) => o.value === value)) return;
    node.value = value;
    this._synced[id] = value;
    const choice = { "shape-select": this._shapeChoice, "strategy-select": this._strategyChoice, "mode-select": this._modeChoice }[id];
    if (choice) choice.refresh();
    if (id === "printer-select") this._renderPrinterRow();
  }

  setSelectedPart(name) {
    this._selectedName = name;
    this._renderSelected();
    this._renderPartsTable();
  }

  render(state) {
    this._lastState = state;
    const busy = !state || !!state.busy;
    this._setButtonsDisabled(busy);

    this._renderPartsTable();

    // 打印机 / 形态 / 策略：只在后端的值「真的变了」时才回填到控件。
    // 每次重绘都回填的话，用户（或 Codex）刚选好还没提交的值会被旧状态冲掉——
    // 写操作一开始 rev 就会变、触发重绘，那时后端记的还是上一次的选项。
    this._syncControl("printer-select", state && state.printer && state.printer.name);
    const opts = (state && state.options) || {};
    this._syncControl("shape-select", opts.shape);
    this._syncControl("strategy-select", opts.strategy);
    this._syncControl("mode-select", opts.mode);
    this._syncControl("gap-input", typeof opts.gap === "number" ? String(opts.gap) : null);

    // 子渲染逐个兜底：某一块读到意料之外的状态抛了错，其余各块、三维视口和状态栏照常更新。
    const steps = [
      () => this._renderPrinterRow(),
      () => this._renderPlatesSummary(state),
      () => this._renderSendPlateOptions(state),
      () => this._renderExportPresetLabels(state),
      () => this._renderExportResult(state),
      () => this._renderCheckResult(state),
      () => this._renderSendResult(state),
      () => this._renderSelected(),
      () => this._renderModelSizeRows(state),
      () => this._renderPlanQuality(state),
      () => this._renderPrintEstimate(state),
      () => this._renderShapeEnhance(),
      () => this._applyCardDefaults(state),
    ];
    for (const step of steps) {
      try {
        step();
      } catch (e) {
        console.error(t("panel.log.renderError"), e);
      }
    }
  }

  // ---------------------------------------------------------------- 绑定
  _bindDom() {
    el("btn-load").addEventListener("click", () => this._handleLoad());
    el("drop-zone").addEventListener("dragover", (e) => {
      e.preventDefault();
      el("drop-zone").classList.add("drag-over");
    });
    el("drop-zone").addEventListener("dragleave", () => el("drop-zone").classList.remove("drag-over"));
    el("drop-zone").addEventListener("drop", (e) => {
      e.preventDefault();
      el("drop-zone").classList.remove("drag-over");
      const files = [...(e.dataTransfer ? e.dataTransfer.files : [])];
      if (files.length) this._handleUpload(files);
    });
    el("file-input").addEventListener("change", (e) => {
      const files = [...e.target.files];
      e.target.value = "";
      if (files.length) this._handleUpload(files);
    });

    el("btn-orient").addEventListener("click", () => this._handleOrient());
    el("btn-arrange").addEventListener("click", () => this._handleArrange());
    el("btn-export").addEventListener("click", () => this._handleExport());
    el("btn-check").addEventListener("click", () => this._handleCheck());
    el("btn-send").addEventListener("click", () => this._handleSend());
    el("btn-prepare").addEventListener("click", () => this._handlePrepare());
    el("btn-override-add").addEventListener("click", () => {
      this._overrides.push({ key: "", value: "" });
      this._renderOverridesTable();
    });
    this._renderOverridesTable();

    // 分段控件 / 单选卡：原生 select 仍是唯一真值。
    this._shapeChoice = bindChoice("shape-select", "shape-choice", { variant: "segment" });
    this._strategyChoice = bindChoice("strategy-select", "strategy-choice", { variant: "cards" });
    this._modeChoice = bindChoice("mode-select", "mode-choice", { variant: "segment" });

    el("printer-select").addEventListener("change", () => this._renderPrinterRow());
    el("shape-select").addEventListener("change", () => this._renderShapeEnhance());

    // 悬浮卡折叠（localStorage 记忆，读写都包 try/catch）。
    document.querySelectorAll("[data-card-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => this._toggleCard(btn.dataset.cardToggle));
    });
    this._applyCardDefaults(null);

    // 选中零件卡：右上角 × 取消选中。
    el("selected-close-btn").addEventListener("click", () => this._clearSelection());

    // 打印计划栏收起 / 重新打开。
    el("panel-collapse").addEventListener("click", () => {
      el("panel").hidden = true;
      el("plan-reopen").hidden = false;
      el("print-space").classList.add("plan-collapsed");
    });
    el("plan-reopen").addEventListener("click", () => {
      el("panel").hidden = false;
      el("plan-reopen").hidden = true;
      el("print-space").classList.remove("plan-collapsed");
    });


    // 摆盘质量 · 告警块：点击展开/收起告警清单。
    el("metric-warnings-tile").addEventListener("click", () => {
      const box = el("plan-warnings-list");
      if (box.children.length) box.hidden = !box.hidden;
    });

    // 发送盘选择：选了「全部盘」要把隐藏的 send-all-check 勾上，_handleSend 逻辑不改。
    el("send-plate-select").addEventListener("change", () => {
      this._syncSendAllFromSelect();
      const v = el("send-plate-select").value;
      if (v !== "all") {
        this._viewPlateIndex = Number(v);
        if (this.opts.onPlateChange) this.opts.onPlateChange(Number(v));
      }
      if (this._lastState) this.render(this._lastState);
    });
  }

  _setButtonsDisabled(disabled) {
    const ids = ["btn-load", "btn-orient", "btn-arrange", "btn-export", "btn-check", "btn-send", "btn-prepare", "btn-override-add"];
    for (const id of ids) el(id).disabled = disabled;
    el("file-input").disabled = disabled;
  }

  // ---------------------------------------------------------------- 悬浮卡折叠
  openCard(id) {
    this._setCardPref(id, "open");
    this._setCardCollapsed(id, false);
  }

  _cardStorageKey(id) {
    return `pp.card.${id}`;
  }

  _getCardPref(id) {
    try {
      return localStorage.getItem(this._cardStorageKey(id));
    } catch (e) {
      return null;
    }
  }

  _setCardPref(id, val) {
    try {
      localStorage.setItem(this._cardStorageKey(id), val);
    } catch (e) {
      /* 隐私模式等场景下 localStorage 可能不可用，忽略即可 */
    }
  }

  _setCardCollapsed(id, collapsed) {
    const card = el(id);
    if (!card) return;
    card.classList.toggle("collapsed", collapsed);
    const btn = card.querySelector(".card-fold-btn");
    if (btn) btn.setAttribute("aria-expanded", String(!collapsed));
  }

  _toggleCard(id) {
    const card = el(id);
    if (!card) return;
    const collapsed = !card.classList.contains("collapsed");
    this._setCardCollapsed(id, collapsed);
    this._setCardPref(id, collapsed ? "closed" : "open");
  }

  // card-arrange 默认展开；card-model 有零件时默认收起、没有零件时展开，
  // 用户手动点过之后（localStorage 里有记录）以用户为准。
  _applyCardDefaults(state) {
    // 视口列不够宽（卡片展开会盖住大半个模型）时，没有用户记录就先收起；窄屏停靠在下方滚动列里时照常展开。
    const arrangePref = this._getCardPref("card-arrange");
    let arrangeCollapsed = arrangePref === "closed";
    if (!arrangePref) {
      const col = el("stage");
      const card = el("card-arrange");
      const floating = !!(col && card && card.parentElement === col);
      arrangeCollapsed = floating && col.getBoundingClientRect().width < 560;
    }
    this._setCardCollapsed("card-arrange", arrangeCollapsed);

    const modelPref = this._getCardPref("card-model");
    let modelCollapsed;
    if (modelPref === "open") modelCollapsed = false;
    else if (modelPref === "closed") modelCollapsed = true;
    else modelCollapsed = !!(state && state.parts && state.parts.length);
    this._setCardCollapsed("card-model", modelCollapsed);
  }

  // ---------------------------------------------------------------- 打印机行
  _renderPrinterRow() {
    const sel = el("printer-select");
    const name = sel.value || "";
    const fromList = this._printers.find((p) => p.name === name);
    let bed = fromList ? fromList.bed_mm : null;
    if (!bed && this._lastState && this._lastState.printer && this._lastState.printer.name === name) {
      bed = this._lastState.printer.bed_mm;
    }
    el("printer-row-name").textContent = name || t("panel.printer.none");
    el("printer-row-bed").textContent = bed ? `${fmtNum(bed[0], 0)}×${fmtNum(bed[1], 0)} mm` : "—";
  }

  // ---------------------------------------------------------------- 1. 模型
  _readModelPaths() {
    return el("model-paths")
      .value.split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  _appendModelPath(path) {
    const ta = el("model-paths");
    const cur = ta.value.replace(/\s+$/, "");
    ta.value = cur ? cur + "\n" + path : path;
  }

  async _handleUpload(files) {
    const statusEl = el("upload-status");
    statusEl.hidden = false;
    for (const file of files) {
      statusEl.textContent = t("panel.upload.inProgress", { name: file.name });
      try {
        const res = await this.opts.onUpload(file);
        if (res && res.path) this._appendModelPath(res.path);
        statusEl.textContent = t("panel.upload.done", { name: file.name });
      } catch (e) {
        statusEl.textContent = t("panel.upload.failed", { name: file.name, detail: e.message || e });
        return;
      }
    }
    setTimeout(() => {
      statusEl.hidden = true;
    }, 4000);
  }

  _collectLoadBody() {
    const files = this._readModelPaths();
    const body = { files, printer: el("printer-select").value || undefined, merge: el("model-merge").checked };
    const scale = el("model-scale").value;
    const targetMax = el("model-target-max").value;
    if (scale) body.scale = Number(scale);
    if (targetMax) body.target_max_mm = Number(targetMax);
    return body;
  }

  _handleLoad() {
    const body = this._collectLoadBody();
    if (!body.files.length) {
      this.opts.onLocalError && this.opts.onLocalError(t("panel.error.noModelFiles"));
      return;
    }
    this.opts.onLoad(body);
  }

  _renderPartsTable() {
    const state = this._lastState;
    const parts = (state && state.parts) || [];
    const tbody = document.querySelector("#parts-table tbody");
    tbody.innerHTML = "";
    for (const p of parts) {
      const tr = document.createElement("tr");
      const warn = !p.watertight || p.components > 1 || !p.fits_bed || p.faces > 2_000_000;
      if (warn) tr.classList.add("row-warn");
      if (p.name === this._selectedName) tr.classList.add("row-selected");

      const color = typeof this.opts.getPartColor === "function" ? this.opts.getPartColor(p.name) : null;
      const dotStyle = color ? ` style="background:${escapeHtml(color)}"` : "";
      const ext = p.extents_mm ? p.extents_mm.map((v) => fmtNum(v, 1)).join(" × ") : "—";
      const sub = `${ext} mm · ${fmtFaces(p.faces)}`;

      let badgeClass = "badge-ok";
      let badgeText = "✓";
      if (!p.fits_bed) {
        badgeClass = "badge-danger";
        badgeText = p.suggested_scale ? t("panel.badge.doesNotFitScaled", { scale: p.suggested_scale }) : t("panel.badge.doesNotFit");
      } else if (!p.watertight) {
        badgeClass = "badge-warn";
        badgeText = t("panel.badge.notWatertight");
      }

      tr.innerHTML = `<td>
        <span class="part-dot"${dotStyle}></span>
        <div class="part-main"><div class="part-name">${escapeHtml(p.name)}</div><div class="part-sub">${escapeHtml(sub)}</div></div>
        <span class="part-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
      </td>`;
      tr.addEventListener("click", () => {
        this._selectedName = p.name;
        this._renderPartsTable();
        this._renderSelected();
        this.opts.onSelectPart && this.opts.onSelectPart(p.name);
      });
      tbody.appendChild(tr);
    }
    this._renderModelWarnings(state);
    this._renderModelCardSummary(parts.length);
  }

  _renderModelCardSummary(count) {
    const node = el("model-card-summary");
    if (count > 0) {
      node.hidden = false;
      node.textContent = t("panel.format.partsCount", { count });
    } else {
      node.hidden = true;
      node.textContent = "";
    }
  }

  _renderModelWarnings(state) {
    const box = el("model-warnings");
    box.innerHTML = "";
    for (const w of (state && state.warnings) || []) {
      const d = document.createElement("div");
      d.className = "warn-item";
      d.textContent = w;
      box.appendChild(d);
    }
  }

  // ---------------------------------------------------------------- 模型尺寸（合并包围盒）
  _computeAssemblyExtents(parts) {
    if (!parts || !parts.length) return null;
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (const p of parts) {
      const c = p.source_center_mm || [0, 0, 0];
      const e = p.extents_mm || [0, 0, 0];
      for (let i = 0; i < 3; i++) {
        const lo = c[i] - e[i] / 2;
        const hi = c[i] + e[i] / 2;
        if (lo < min[i]) min[i] = lo;
        if (hi > max[i]) max[i] = hi;
      }
    }
    return [max[0] - min[0], max[1] - min[1], max[2] - min[2]];
  }

  _renderModelSizeRows(state) {
    const ext = this._computeAssemblyExtents(state && state.parts);
    ["model-size-x", "model-size-y", "model-size-z"].forEach((id, i) => {
      el(id).textContent = ext ? fmtNum(ext[i], 1) : "—";
    });
  }

  // 「当前盘」：优先跟随发送区选中的盘，否则取第一盘。仅用于展示，不影响任何写操作。
  _currentPlate(state) {
    const plates = (state && state.plates) || [];
    if (!plates.length) return null;
    // 先跟视口当前显示的盘（页签或发送下拉都会更新它），找不到再退回第一盘。
    if (this._viewPlateIndex !== undefined && this._viewPlateIndex !== null) {
      const found = plates.find((p) => p.index === this._viewPlateIndex);
      if (found) return found;
    }
    return plates[0];
  }

  // 视口切盘（app.js 的盘页签）时调用：指标与发送下拉一起跟过去。plateNumber 是盘号（plates[].index）。
  setViewPlate(plateNumber) {
    if (this._viewPlateIndex === plateNumber) return;
    this._viewPlateIndex = plateNumber;
    const sel = el("send-plate-select");
    if (sel && sel.value !== "all" && [...sel.options].some((o) => o.value === String(plateNumber))) {
      sel.value = String(plateNumber);
    }
    if (this._lastState) this.render(this._lastState);
  }

  _plateSuffix(state, plate) {
    const n = ((state && state.plates) || []).length;
    return n > 1 && plate ? t("panel.plates.suffix", { index: plate.index }) : "";
  }

  // ---------------------------------------------------------------- 选中零件
  _renderSelected() {
    const state = this._lastState;
    const part = state && this._selectedName ? (state.parts || []).find((p) => p.name === this._selectedName) : null;
    const card = el("card-selected");
    if (!part) {
      card.hidden = true;
      el("selected-empty").hidden = false;
      el("selected-detail").hidden = true;
      return;
    }
    card.hidden = false;
    el("selected-empty").hidden = true;
    el("selected-detail").hidden = false;
    const o = part.orient;
    const title = el("selected-title");
    if (title) title.textContent = part.name;
    const metrics = el("selected-metrics");
    metrics.innerHTML = "";
    // 三个指标块（贴床 / 悬空 / 高度）+ 一行小字（策略与朝上方向），比逐行键值省一半高度。
    const tiles = [
      [t("panel.selected.tile.contactArea"), o ? fmtNum(o.contact_area_mm2, 0) : "—"],
      [t("panel.selected.tile.overhangArea"), o ? fmtNum(o.overhang_area_mm2, 0) : "—"],
      [t("panel.selected.tile.height"), o ? fmtNum(o.height_mm, 1) : "—"],
    ];
    for (const [k, v] of tiles) {
      const tile = document.createElement("div");
      tile.className = "mini-tile";
      const kEl = document.createElement("span");
      kEl.className = "mini-tile-label";
      kEl.textContent = k;
      const vEl = document.createElement("span");
      vEl.className = "mini-tile-value";
      vEl.textContent = v;
      tile.appendChild(kEl);
      tile.appendChild(vEl);
      metrics.appendChild(tile);
    }
    const note = document.createElement("div");
    note.className = "selected-note";
    note.textContent = o
      ? t("panel.selected.note", { strategy: STRATEGY_USED_LABELS()[o.strategy_used] || o.strategy_used || "—", up: fmtVec(o.print_up) })
      : t("panel.selected.noOrientation");
    metrics.appendChild(note);
    if (o && o.upright_rejected) {
      const rej = document.createElement("div");
      rej.className = "selected-note";
      rej.textContent = t("panel.selected.uprightRejected", { reason: o.upright_rejected_reason || t("panel.selected.uprightRejectedDefaultReason") });
      metrics.appendChild(rej);
    }

    const warnList = el("selected-warnings");
    warnList.innerHTML = "";
    const warns = (o && o.warnings) || [];
    for (const w of warns) {
      const d = document.createElement("div");
      d.className = "warn-item";
      d.textContent = WARNING_LABELS()[w] || w;
      if (WARNING_LABELS()[w]) d.title = w;
      warnList.appendChild(d);
    }

    const candList = el("selected-candidates");
    candList.innerHTML = "";
    const candidates = (o && o.top_candidates) || [];
    candidates.forEach((c, idx) => {
      const row = document.createElement("div");
      row.className = "candidate-item";
      const text = document.createElement("div");
      text.className = "candidate-text";
      const metricsSpan = document.createElement("span");
      metricsSpan.className = "candidate-metrics";
      metricsSpan.textContent = t("panel.candidate.metrics", {
        n: idx + 1,
        contact: fmtNum(c.contact_area_mm2, 0),
        overhang: fmtNum(c.overhang_area_mm2, 0),
        height: fmtNum(c.height_mm, 1),
      });
      const vecSpan = document.createElement("span");
      vecSpan.className = "candidate-vec";
      vecSpan.textContent = t("panel.candidate.up", { up: fmtVec(c.print_up) });
      text.appendChild(metricsSpan);
      text.appendChild(vecSpan);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mini-btn btn-mini";
      btn.textContent = t("panel.candidate.adoptButton");
      btn.title = t("panel.candidate.useThisOrientation");
      btn.setAttribute("aria-label", t("panel.candidate.useThisOrientation"));
      btn.disabled = !!(state && state.busy);
      btn.addEventListener("click", () =>
        this.opts.onOrientSet(part.name, c.print_up, { shape: el("shape-select").value, strategy: el("strategy-select").value })
      );
      row.appendChild(text);
      row.appendChild(btn);
      candList.appendChild(row);
    });
    if (!candidates.length) {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = t("panel.selected.noCandidatesYet");
      candList.appendChild(hint);
    }
  }

  _clearSelection() {
    this._selectedName = null;
    this._renderSelected();
    this._renderPartsTable();
    this.opts.onSelectPart && this.opts.onSelectPart(null);
  }

  // ---------------------------------------------------------------- 2. 打印机与形态
  _handleOrient() {
    this.opts.onOrient(this.bodyFor("orient"));
  }

  /** 某一步按当前控件取值拼出来的请求体；「把后面的步骤重做一遍」与各行自己的按钮共用。取值不合法时返回 null。 */
  bodyFor(step) {
    if (step === "orient") return { strategy: el("strategy-select").value, shape: el("shape-select").value };
    if (step === "arrange") {
      const gap = Number(el("gap-input").value || 0);
      if (gap < 0) {
        this.opts.onLocalError && this.opts.onLocalError(t("panel.error.gapNegative"));
        return null;
      }
      return { mode: el("mode-select").value, gap };
    }
    if (step === "export") {
      const body = { shape: el("shape-select").value, set: this._collectOverrides(), no_project: el("no-project-check").checked };
      const process = el("process-input").value.trim();
      const filament = el("filament-input").value.trim();
      if (process) body.process = process;
      if (filament) body.filament = filament;
      return body;
    }
    if (step === "check") return {};
    return null;
  }

  // ---------------------------------------------------------------- 3. 分盘
  _handleArrange() {
    const body = this.bodyFor("arrange");
    if (body) this.opts.onArrange(body);
  }

  _renderPlatesSummary(state) {
    const box = el("plates-summary");
    const plates = state && state.plates;
    if (!plates || !plates.length) {
      box.textContent = t("panel.plates.none");
      return;
    }
    box.textContent = t("panel.plates.summary", {
      count: plates.length,
      list: plates.map((p) => t("panel.plates.item", { index: p.index, parts: (p.parts || []).length })).join(t("panel.plates.itemSeparator")),
    });
  }

  // ---------------------------------------------------------------- 摆盘质量 / 打印预估（打印计划栏）
  _renderPlanQuality(state) {
    const parts = (state && state.parts) || [];
    const plates = (state && state.plates) || [];

    el("metric-parts-plates").textContent = parts.length
      ? plates.length
        ? t("panel.metric.partsPlates", { parts: parts.length, plates: plates.length })
        : t("panel.metric.partsNoPlates", { parts: parts.length })
      : "—";

    const cur = this._currentPlate(state);
    const bedUtilEl = el("metric-bed-util");
    const bedLabel = el("metric-bed-util-label");
    if (bedLabel) bedLabel.textContent = t("panel.metric.bedUtilLabel") + this._plateSuffix(state, cur);
    if (cur && state && state.printer && state.printer.bed_mm) {
      const bedArea = state.printer.bed_mm[0] * state.printer.bed_mm[1];
      const used = (cur.placements || []).reduce((sum, pl) => sum + (pl.footprint_mm ? pl.footprint_mm[0] * pl.footprint_mm[1] : 0), 0);
      bedUtilEl.textContent = bedArea > 0 ? `${Math.round((used / bedArea) * 100)}%` : "—";
    } else {
      bedUtilEl.textContent = "—";
    }

    const hasOrient = parts.some((p) => p.orient);
    let contact = 0;
    let overhang = 0;
    for (const p of parts) {
      if (p.orient) {
        contact += p.orient.contact_area_mm2 || 0;
        overhang += p.orient.overhang_area_mm2 || 0;
      }
    }
    el("metric-contact-area").textContent = hasOrient ? `${Math.round(contact)} mm²` : "—";
    el("metric-overhang-area").textContent = hasOrient ? `${Math.round(overhang)} mm²` : "—";

    let warnCount = (state && state.warnings ? state.warnings.length : 0) || 0;
    for (const p of parts) {
      if (p.orient && p.orient.warnings) warnCount += p.orient.warnings.length;
    }
    const warnEl = el("metric-warnings");
    warnEl.textContent = String(warnCount);
    warnEl.classList.toggle("metric-warn", warnCount > 0);
    this._renderPlanWarningsList(state, warnCount);
  }

  _renderPlanWarningsList(state) {
    const box = el("plan-warnings-list");
    box.innerHTML = "";
    const items = [...((state && state.warnings) || [])];
    for (const p of (state && state.parts) || []) {
      if (p.orient && p.orient.warnings) {
        for (const w of p.orient.warnings) items.push(t("panel.warning.partLine", { name: p.name, warning: WARNING_LABELS()[w] || w }));
      }
    }
    for (const w of items) {
      const d = document.createElement("div");
      d.className = "warn-item";
      d.textContent = w;
      box.appendChild(d);
    }
    if (!items.length) box.hidden = true;
  }

  _renderPrintEstimate(state) {
    const ext = this._computeAssemblyExtents(state && state.parts);
    el("metric-final-size").textContent = ext ? `${fmtNum(ext[0], 1)} × ${fmtNum(ext[1], 1)} × ${fmtNum(ext[2], 1)} mm` : "—";

    const plate = this._currentPlate(state);
    const plateLabel = el("metric-plate-size-label");
    if (plateLabel) plateLabel.textContent = t("panel.metric.plateSizeLabel") + this._plateSuffix(state, plate);
    if (plate && (plate.placements || []).length) {
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      let maxH = 0;
      for (const pl of plate.placements) {
        const fp = pl.footprint_mm || [0, 0];
        // x_mm / y_mm is the lower-left corner of the footprint (see print_prep/arrange.py), not its center.
        const x0 = pl.x_mm;
        const x1 = pl.x_mm + fp[0];
        const y0 = pl.y_mm;
        const y1 = pl.y_mm + fp[1];
        if (x0 < minX) minX = x0;
        if (x1 > maxX) maxX = x1;
        if (y0 < minY) minY = y0;
        if (y1 > maxY) maxY = y1;
        const part = ((state && state.parts) || []).find((p) => p.name === pl.part);
        const h = part && part.orient ? part.orient.height_mm || 0 : 0;
        if (h > maxH) maxH = h;
      }
      const sizeTxt = `${fmtNum(maxX - minX, 1)} × ${fmtNum(maxY - minY, 1)}` + (maxH > 0 ? ` × ${fmtNum(maxH, 1)}` : "");
      el("metric-plate-size").textContent = sizeTxt + " mm";
    } else {
      el("metric-plate-size").textContent = "—";
    }

    const chk = state && state.check;
    const filEl = el("metric-filament");
    const timeEl = el("metric-time");
    if (chk && chk.plates && chk.plates.length) {
      const gramsOk = chk.plates.filter((p) => typeof p.grams === "number");
      const secondsOk = chk.plates.filter((p) => typeof p.seconds === "number");
      const grams = gramsOk.reduce((acc, p) => acc + p.grams, 0);
      const seconds = secondsOk.reduce((acc, p) => acc + p.seconds, 0);
      const missing = chk.plates.length - Math.min(gramsOk.length, secondsOk.length);
      filEl.textContent = gramsOk.length ? `${missing ? "≥ " : ""}${fmtNum(grams, 1)} g` : "—";
      filEl.classList.remove("metric-pending");
      timeEl.textContent = secondsOk.length ? (missing ? "≥ " : "") + fmtSeconds(seconds) : "—";
      timeEl.classList.remove("metric-pending");
      el("metric-time-sub").textContent = missing
        ? t("panel.metric.timeSubMissing", { missing })
        : chk.plates.length > 1
          ? t("panel.metric.timeSubTotal", { count: chk.plates.length })
          : "";
    } else {
      filEl.textContent = t("panel.metric.notChecked");
      filEl.classList.add("metric-pending");
      timeEl.textContent = t("panel.metric.notChecked");
      timeEl.classList.add("metric-pending");
      el("metric-time-sub").textContent = "";
    }
  }

  // ---------------------------------------------------------------- 打印增强（形态表）
  _renderShapeEnhance() {
    const titleEl = el("shape-enhance-title");
    const listEl = el("shape-enhance-list");
    const shape = el("shape-select").value || "generic";
    titleEl.textContent = t("panel.shapeEnhance.title", { shape: SHAPE_LABELS()[shape] || shape });
    listEl.innerHTML = "";

    const fail = () => {
      const d = document.createElement("div");
      d.className = "hint";
      d.textContent = t("panel.shapeEnhance.loadFailed");
      listEl.appendChild(d);
    };

    if (!this._shapes || !this._shapes.length) {
      fail();
      return;
    }
    const entry = this._shapes.find((s) => s.label === shape);
    if (!entry) {
      fail();
      return;
    }

    const exportOverrides = (this._lastState && this._lastState.export && this._lastState.export.overrides) || {};
    const merged = Object.assign({}, entry.process_overrides || {}, exportOverrides);
    const keys = Object.keys(merged);

    if (shape === "generic" && !keys.length) {
      const d = document.createElement("div");
      d.className = "hint";
      d.textContent = t("panel.shapeEnhance.genericNote");
      listEl.appendChild(d);
      return;
    }

    const rows = [];
    rows.push([t("panel.shapeEnhance.layerHeight"), entry.layer_height_mm !== undefined && entry.layer_height_mm !== null ? `${fmtNum(entry.layer_height_mm, 2)} mm` : "—"]);
    rows.push([t("panel.shapeEnhance.orientStrategy"), STRATEGY_LABELS()[entry.orient_strategy] || entry.orient_strategy || "—"]);
    for (const k of keys) {
      rows.push([OVERRIDE_KEY_LABELS()[k] || k, formatOverrideValue(k, merged[k])]);
    }
    for (const [label, value] of rows) {
      const row = document.createElement("div");
      row.className = "enhance-row";
      const labelSpan = document.createElement("span");
      labelSpan.className = "enhance-row-label";
      const check = document.createElement("span");
      check.className = "enhance-check";
      check.textContent = "✓";
      labelSpan.appendChild(check);
      labelSpan.appendChild(document.createTextNode(label));
      const valueSpan = document.createElement("span");
      valueSpan.className = "enhance-row-value";
      valueSpan.textContent = String(value);
      row.appendChild(labelSpan);
      row.appendChild(valueSpan);
      listEl.appendChild(row);
    }
  }

  // ---------------------------------------------------------------- 4. 工艺与导出
  _renderOverridesTable() {
    const tbody = document.querySelector("#overrides-table tbody");
    tbody.innerHTML = "";
    this._overrides.forEach((row, idx) => {
      const tr = document.createElement("tr");
      const keyTd = document.createElement("td");
      const keyInput = document.createElement("input");
      keyInput.type = "text";
      keyInput.value = row.key;
      keyInput.placeholder = "enable_support";
      keyInput.addEventListener("input", () => (row.key = keyInput.value));
      keyTd.appendChild(keyInput);

      const valTd = document.createElement("td");
      const valInput = document.createElement("input");
      valInput.type = "text";
      valInput.value = row.value;
      valInput.placeholder = "1";
      valInput.addEventListener("input", () => (row.value = valInput.value));
      valTd.appendChild(valInput);

      const rmTd = document.createElement("td");
      const rmBtn = document.createElement("button");
      rmBtn.type = "button";
      rmBtn.className = "mini-btn btn-mini";
      rmBtn.textContent = "×";
      rmBtn.addEventListener("click", () => {
        this._overrides.splice(idx, 1);
        this._renderOverridesTable();
      });
      rmTd.appendChild(rmBtn);

      tr.appendChild(keyTd);
      tr.appendChild(valTd);
      tr.appendChild(rmTd);
      tbody.appendChild(tr);
    });
    this._renderOverridesCount();
  }

  _renderOverridesCount() {
    el("overrides-count").textContent = t("panel.override.count", { count: this._overrides.length });
    el("overrides-table").hidden = this._overrides.length === 0;
  }

  _collectOverrides() {
    const out = {};
    for (const row of this._overrides) {
      if (row.key.trim()) out[row.key.trim()] = row.value;
    }
    return out;
  }

  _handleExport() {
    this.opts.onExport(this.bodyFor("export"));
  }

  _renderMfPrinterRow(state) {
    const printer = state && state.printer;
    el("mf-printer-name").textContent = printer && printer.name ? printer.name : "—";
    el("mf-printer-bed").textContent = printer && printer.bed_mm ? printer.bed_mm.map((v) => fmtNum(v, 0)).join("×") + " mm" : "—";
  }

  _renderExportPresetLabels(state) {
    const proc = el("export-process-name");
    const fil = el("export-filament-name");
    const note = el("export-process-note");
    if (state && state.export) {
      proc.textContent = state.export.process_preset || "—";
      fil.textContent = state.export.filament_preset || "—";
      note.textContent = "";
    } else {
      proc.textContent = t("panel.export.defaultProcessNote");
      fil.textContent = t("panel.export.defaultFilamentNote");
      note.textContent = t("panel.export.chosenAtExportTime");
    }
    this._renderMfPrinterRow(state);
  }

  _renderExportResult(state) {
    const box = el("export-result");
    box.innerHTML = "";
    const exp = state && state.export;
    if (!exp) {
      box.innerHTML = `<div class="hint">${t("panel.export.notYet")}</div>`;
      return;
    }
    for (const p of exp.plates || []) {
      const div = document.createElement("div");
      div.className = "result-plate";
      const moved = p.bambu_moved_objects ? `<div class="flag-bad">${t("panel.export.bambuMovedObjects")}</div>` : "";
      const unmatched = p.unmatched_parts && p.unmatched_parts.length
        ? `<div class="flag-bad">${t("panel.export.unmatchedParts", { names: escapeHtml(p.unmatched_parts.join(t("common.listSeparator"))) })}</div>`
        : "";
      div.innerHTML = `
        <div>${t("panel.plate.label", { index: p.index })}</div>
        <div class="path">${t("panel.export.geometry3mf", { path: escapeHtml(p.geometry_3mf || "—") })}</div>
        <div class="path">${t("panel.export.project3mf", { path: escapeHtml(p.project_3mf || t("panel.export.notGenerated")) })}</div>
        ${moved}${unmatched}`;
      box.appendChild(div);
    }
    for (const note of exp.notes || []) {
      const d = document.createElement("div");
      d.className = "hint";
      d.textContent = note;
      box.appendChild(d);
    }
  }

  // ---------------------------------------------------------------- 5. 试切
  _handleCheck() {
    this.opts.onCheck({});
  }

  _renderCheckResult(state) {
    const box = el("check-result");
    box.innerHTML = "";
    const chk = state && state.check;
    if (!chk || !chk.plates || !chk.plates.length) {
      // 没试切时上面的「耗材 / 时长」指标块已经写着「未试切」，这里不再重复一句。
      box.hidden = true;
      return;
    }
    box.hidden = false;
    for (const p of chk.plates) {
      const div = document.createElement("div");
      div.className = "result-plate";
      const failed = p.returncode !== 0;
      div.innerHTML = `
        <div>${t("panel.plate.label", { index: p.index })}${failed ? ` <span class="flag-bad">${t("panel.check.failed")}</span>` : ""}</div>
        <div>${t("panel.check.grams", { value: p.grams === null || p.grams === undefined ? "—" : fmtNum(p.grams, 2) + " g" })}</div>
        <div>${t("panel.check.duration", { value: fmtSeconds(p.seconds) })}</div>
        ${(p.warnings || []).map((w) => `<div class="hint">${escapeHtml(w)}</div>`).join("")}
      `;
      box.appendChild(div);
    }
  }

  // ---------------------------------------------------------------- 6. 发送
  _renderSendPlateOptions(state) {
    const sel = el("send-plate-select");
    const prev = sel.value;
    sel.innerHTML = "";
    const plates = (state && state.plates) || [];
    for (const p of plates) {
      const opt = document.createElement("option");
      opt.value = String(p.index);
      opt.textContent = t("panel.plate.label", { index: p.index });
      sel.appendChild(opt);
    }
    const optAll = document.createElement("option");
    optAll.value = "all";
    optAll.textContent = t("panel.plate.all");
    sel.appendChild(optAll);
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
    this._syncSendAllFromSelect();
  }

  _syncSendAllFromSelect() {
    el("send-all-check").checked = el("send-plate-select").value === "all";
  }

  _handleSend() {
    const all = el("send-all-check").checked;
    const body = { all };
    if (!all) body.plate = Number(el("send-plate-select").value || 1);
    this.opts.onSend(body);
  }

  _renderSendResult(state) {
    const box = el("send-result");
    box.innerHTML = "";
    const sent = state && state.sent;
    if (!sent) return;
    const projectNames = (sent.plates || [])
      .map((idx) => {
        const p = state.export && (state.export.plates || []).find((pp) => pp.index === idx);
        return p && p.project_3mf ? basename(p.project_3mf) : `plate_${String(idx).padStart(2, "0")}.project.3mf`;
      })
      .join(t("common.listSeparator"));
    const div = document.createElement("div");
    div.className = "result-plate";
    let msg = sent.launched
      ? t("panel.send.launched", { names: projectNames })
      : t("panel.send.dryRun");
    if (sent.was_running_before) msg += t("panel.send.wasRunningSuffix");
    div.textContent = msg;
    box.appendChild(div);
  }

  // ---------------------------------------------------------------- 7. 一键准备
  _handlePrepare() {
    const loadBody = this._collectLoadBody();
    if (!loadBody.files.length) {
      this.opts.onLocalError && this.opts.onLocalError(t("panel.error.noModelFiles"));
      return;
    }
    const body = Object.assign({}, loadBody, {
      shape: el("shape-select").value,
      strategy: el("strategy-select").value,
      mode: el("mode-select").value,
      gap: Number(el("gap-input").value || 4),
      export_set: this._collectOverrides(),
      no_project: el("no-project-check").checked,
    });
    const process = el("process-input").value.trim();
    const filament = el("filament-input").value.trim();
    if (process) body.process = process;
    if (filament) body.filament = filament;
    this.opts.onPrepare(body);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
