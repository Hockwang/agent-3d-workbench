// v0.5 feedback inside the v0.4 shell: readiness, next step, stale results and history.
// Controls remain in panel.js; navigation and operations go through workspace callbacks.
import { t } from "./i18n.js";

const STEPS = [
  { key: "model", src: "inspect", todo: t("flow.step.model.todo") },
  { key: "orient", src: "orient", todo: t("flow.step.orient.todo") },
  { key: "arrange", src: "arrange", todo: t("flow.step.arrange.todo") },
  { key: "export", src: "export", todo: t("flow.step.export.todo") },
  { key: "check", src: "check", todo: t("flow.step.check.todo") },
  { key: "deliver", src: null, todo: t("flow.step.deliver.todo") },
];
const STEP_NAME = {
  inspect: t("flow.step.model.name"), orient: t("flow.step.orient.name"), arrange: t("flow.step.arrange.name"),
  export: t("flow.step.export.name"), check: t("flow.step.check.name"),
};
const OP_TO_STEP = { load: "model", orient: "orient", arrange: "arrange", export: "export", check: "check", send: "deliver", undo: null };
const STRATEGY_LABEL = { auto: t("flow.strategy.auto"), flat: t("flow.strategy.flat"), support: t("flow.strategy.support"), upright: t("flow.strategy.upright") };
const SHAPE_LABEL = { generic: t("flow.shape.generic"), figurine: t("flow.shape.figurine"), relief: t("flow.shape.relief"), mechanical: t("flow.shape.mechanical") };
const READY_LABEL = {
  model: t("flow.step.model.name"), orient: t("flow.step.orient.name"), arrange: t("flow.step.arrange.name"),
  export: t("flow.step.export.name"), check: t("flow.step.check.name"), deliver: t("flow.step.deliver.name"),
};

const ICON = {
  ok: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-6.5"/></svg>',
  warn: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5l6 10.5H2z"/><path d="M8 6.5v3"/><path d="M8 11.3v.2"/></svg>',
  run: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="4" cy="8" r="1.1" fill="currentColor"/><circle cx="8" cy="8" r="1.1" fill="currentColor"/><circle cx="12" cy="8" r="1.1" fill="currentColor"/></svg>',
  stale: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12.5 6.5A5 5 0 1 0 13 9"/><path d="M13 3v3.5H9.5"/></svg>',
  undo: '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 6.5A5 5 0 1 1 3 9"/><path d="M3 3v3.5h3.5"/></svg>',
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function num(v, digits) {
  if (typeof v !== "number" || !isFinite(v)) return "—";
  return v.toLocaleString("zh-CN", { maximumFractionDigits: digits == null ? 0 : digits, minimumFractionDigits: 0 });
}
function cm2(mm2) {
  return num((mm2 || 0) / 100, 1);
}
function duration(seconds) {
  if (typeof seconds !== "number" || !isFinite(seconds)) return "—";
  const m = Math.round(seconds / 60);
  const h = Math.floor(m / 60);
  return h ? `${h} h ${String(m % 60).padStart(2, "0")} m` : `${m} m`;
}
function hhmm(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function sumOverhang(parts) {
  let total = 0;
  let any = false;
  for (const p of parts || []) {
    if (p.orient && typeof p.orient.overhang_area_mm2 === "number") {
      total += p.orient.overhang_area_mm2;
      any = true;
    }
  }
  return any ? total : null;
}
function checkTotals(check) {
  const plates = (check && check.plates) || [];
  let grams = 0;
  let seconds = 0;
  let warnings = 0;
  let failed = 0;
  for (const p of plates) {
    if (typeof p.grams === "number") grams += p.grams;
    if (typeof p.seconds === "number") seconds += p.seconds;
    warnings += (p.warnings || []).length;
    if (p.returncode) failed += 1;
  }
  return { plates: plates.length, grams, seconds, warnings, failed };
}

/** 后端还没给 readiness 时（演示模式、旧后端）在页面上按同一套规则算一份。规则见 SPEC_V05.md §2.2。 */
export function deriveReadiness(state) {
  const items = [];
  const steps = (state && state.steps) || {};
  const parts = (state && state.parts) || [];
  const push = (key, status, detail) => items.push({ key, status, detail: detail || "" });
  if (!steps.inspect) push("model", "todo");
  else {
    const bad = parts.filter((p) => !p.watertight).length;
    const big = parts.filter((p) => p.fits_bed === false).length;
    const warns = (state.warnings || []).length;
    push("model", bad || big || warns ? "warn" : "pass", bad ? t("flow.readiness.notWatertightCount", { count: bad }) : big ? t("flow.readiness.tooBigCount", { count: big }) : warns ? t("flow.readiness.warningsHint", { count: warns }) : "");
  }
  if (!steps.orient) push("orient", "todo");
  else push("orient", parts.some((p) => p.orient && (p.orient.warnings || []).length) ? "warn" : "pass");
  push("arrange", steps.arrange ? "pass" : "todo");
  if (!steps.export) push("export", "todo");
  else {
    const ex = (state.export && state.export.plates) || [];
    push("export", ex.some((p) => (p.unmatched_parts || []).length || p.used_slice_fallback) ? "warn" : "pass");
  }
  if (!steps.check) push("check", "todo");
  else {
    const totals = checkTotals(state.check);
    push("check", totals.warnings || totals.failed ? "warn" : "pass", totals.warnings ? t("flow.count.warnings", { count: totals.warnings }) : totals.failed ? t("flow.readiness.someFailedToSlice") : "");
  }
  const sent = state && state.sent && state.sent.launched !== false && (state.sent.plates || []).length;
  push("deliver", sent ? "pass" : "todo");
  return { passed: items.filter((i) => i.status === "pass").length, total: items.length, items };
}

/** A single status calculation for the compact plan and its expandable details. */
export function derivePlanFeedback(state) {
  const s = state || {}, readiness = s.readiness || deriveReadiness(s);
  const byKey = new Map((readiness.items || []).map(item => [item.key, item]));
  const busyKey = s.busy?.op === 'prepare'
    ? STEPS.find(step => step.src && !s.steps?.[step.src])?.key || 'check'
    : OP_TO_STEP[s.busy?.op];
  const items = STEPS.map(step => {
    const item = byKey.get(step.key) || { status: 'todo' };
    const status = busyKey === step.key ? 'run' : step.src && s.stale?.[step.src] ? 'stale' : item.status;
    return { key: step.key, src: step.src, status, detail: item.detail || '' };
  });
  const progress = { items, passed: items.filter(item => item.status === 'pass').length, total: items.length };
  if (!state) return { ...progress, label: t('flow.plan.disconnected.label'), title: t('flow.plan.disconnected.title'), detail: t('flow.plan.disconnected.detail'), key: null, tone: 'todo' };
  if (s.busy) return { ...progress, label: t('flow.plan.busy.label'), title: busyKey ? t('flow.plan.busy.titleWithStep', { step: READY_LABEL[busyKey] }) : t('flow.plan.busy.titleGeneric'), detail: t('flow.plan.busy.detail'), key: null, tone: 'run' };
  const next = items.find(item => item.status !== 'pass');
  if (!next) return { ...progress, label: t('flow.plan.done.label'), title: t('flow.plan.done.title'), detail: t('flow.plan.done.detail'), key: null, tone: 'pass' };
  const label = next.status === 'stale' ? t('flow.plan.next.label.stale') : next.status === 'warn' ? t('flow.plan.next.label.warn') : t('flow.plan.next.label.default');
  const title = next.status === 'stale' ? t('flow.plan.next.title.stale', { step: READY_LABEL[next.key] }) : next.status === 'warn' ? t('flow.plan.next.title.warn', { step: READY_LABEL[next.key] }) : ({
    model: t('flow.plan.next.title.model'), orient: t('flow.plan.next.title.orient'), arrange: t('flow.plan.next.title.arrange'),
    export: t('flow.plan.next.title.export'), check: t('flow.plan.next.title.check'), deliver: t('flow.plan.next.title.deliver'),
  }[next.key]);
  const detail = next.status === 'stale' ? t('flow.plan.next.detail.stale')
    : next.detail || STEPS.find(step => step.key === next.key).todo;
  return { ...progress, label, title, detail, key: next.key, tone: next.status };
}

export class Flow {
  constructor(opts) {
    this.opts = opts || {};
    this.openKey = null;
    this.userTouched = false;
    this._lastHistoryKey = "";
    this._rows = new Map();
    for (const li of document.querySelectorAll("#flow .step")) {
      const key = li.dataset.step;
      const head = li.querySelector(".step-head");
      this._rows.set(key, {
        li, head,
        dot: li.querySelector("[data-dot]"), ev: li.querySelector("[data-ev]"), who: li.querySelector("[data-who]"),
        detail: li.querySelector(".step-detail"), runBar: null,
      });
      head.addEventListener("click", () => {
        this.userTouched = true;
        this.open(this.openKey === key ? null : key);
      });
    }
    const pill = document.getElementById("ready-pill");
    pill.addEventListener("click", () => {
      const list = document.getElementById("ready-list");
      list.hidden = !list.hidden;
      pill.setAttribute("aria-expanded", String(!list.hidden));
    });
    document.getElementById("sel-clear")?.addEventListener("click", () => this.opts.onSelectPart && this.opts.onSelectPart(null));
    document.getElementById("btn-redo").addEventListener("click", () => {
      if (this._staleSteps && this._staleSteps.length && this.opts.onRedo) this.opts.onRedo(this._staleSteps.slice());
    });
    document.getElementById('plan-next')?.addEventListener('click', () => {
      if (this._nextKey) this.opts.onOpenStep?.(this._nextKey);
    });
    document.getElementById('ready-list')?.addEventListener('click', event => {
      const key = event.target.closest('[data-readiness-step]')?.dataset.readinessStep;
      if (STEPS.some(step => step.key === key)) this.opts.onOpenStep?.(key);
    });
  }

  open(key) {
    this.openKey = key;
    for (const [k, row] of this._rows) {
      const on = k === key;
      row.li.classList.toggle("open", on);
      row.detail.hidden = !on;
      row.head.setAttribute("aria-expanded", String(on));
    }
  }

  /** @param {object|null} state  /api/state  @param {{selectedName: string|null}} ui */
  render(state, ui) {
    const s = state || {};
    const readiness = derivePlanFeedback(state);
    const byKey = {};
    for (const it of readiness.items || []) byKey[it.key] = it;

    const actors = s.step_actors || {};
    const staleSteps = readiness.items.filter(item => item.status === 'stale').map(item => item.src);
    let firstOpen = null;

    for (const def of STEPS) {
      const row = this._rows.get(def.key);
      if (!row) continue;
      const item = byKey[def.key] || { status: "todo" };
      const status = item.status === 'pass' ? 'ok' : item.status;

      row.li.className = "step is-" + status + (this.openKey === def.key ? " open" : "");
      row.dot.innerHTML = ICON[status] || String(STEPS.indexOf(def) + 1);
      row.ev.innerHTML = this._evidence(def, status, s, item);
      this._renderWho(row.who, def, status, actors, s);
      this._renderRunBar(row, status === "run");
      if (!firstOpen && (status === "todo" || status === "stale" || status === "warn")) firstOpen = def.key;
    }

    if (!this.userTouched) {
      const want = (s.parts || []).length ? firstOpen : "model";
      if (want !== this.openKey) this.open(want);
    }

    this._staleSteps = staleSteps;
    const banner = document.getElementById("stale-banner");
    banner.hidden = !staleSteps.length || !!s.busy;
    if (staleSteps.length) {
      document.getElementById("stale-text").textContent =
        t("flow.staleBanner.text", { steps: staleSteps.map((k) => STEP_NAME[k]).join(t("common.listSeparator")) });
      document.getElementById("btn-redo").disabled = !!s.busy;
    }

    this._renderCtx(s, readiness);
    this._renderPlanFeedback(s, readiness);
    this._renderOrientParts(s, ui && ui.selectedName);
    this._renderSelection(s, ui && ui.selectedName);
    this._renderHistory(s);
  }

  _renderPlanFeedback(s, feedback) {
    const card = document.getElementById('plan-feedback');
    if (!card) return;
    // An active recipe already owns the next-step guidance in the top strip.
    card.hidden = !!s.recipe;
    card.dataset.tone = feedback.tone;
    for (const key of ['label', 'title', 'detail']) {
      const node = document.getElementById(`plan-next-${key}`);
      if (node.textContent !== feedback[key]) node.textContent = feedback[key];
    }
    this._nextKey = feedback.key;
    const button = document.getElementById('plan-next');
    button.hidden = !feedback.key;
    button.textContent = feedback.key ? t('flow.plan.next.viewButton', { step: READY_LABEL[feedback.key] }) : '';
  }

  _renderRunBar(row, on) {
    if (on && !row.runBar) {
      row.runBar = document.createElement("div");
      row.runBar.className = "step-run-bar";
      row.runBar.innerHTML = "<i></i>";
      row.head.insertAdjacentElement("afterend", row.runBar);
    } else if (!on && row.runBar) {
      row.runBar.remove();
      row.runBar = null;
    }
  }

  _renderWho(node, def, status, actors, s) {
    let text = "";
    let cls = "";
    if (status === "stale") [text, cls] = [t("flow.who.redo"), "stale"];
    else if (status === "run") [text, cls] = s.busy && s.busy.actor === "human" ? [t("flow.who.you"), "me"] : s.busy && s.busy.actor === "ai" ? ["AI", "ai"] : ["", ""];
    else if (status === "todo") {
      const prev = STEPS[STEPS.indexOf(def) - 1];
      const prevDone = !prev || !prev.src || (s.steps || {})[prev.src];
      [text, cls] = [prevDone ? t("flow.who.notDone") : t("flow.who.waitingForPrevious"), "todo"];
    } else if (def.src && actors[def.src]) [text, cls] = actors[def.src] === "human" ? [t("flow.who.you"), "me"] : ["AI", "ai"];
    node.textContent = text;
    node.className = "who" + (cls ? " " + cls : "");
  }

  _evidence(def, status, s, item) {
    if (status === "run") return t("flow.evidence.running", { verb: ({ model: t("flow.verb.model"), orient: t("flow.verb.orient"), arrange: t("flow.step.arrange.name"), export: t("flow.verb.export"), check: t("flow.step.check.name"), deliver: t("flow.verb.deliver") })[def.key] });
    if (status === "todo") return esc(def.todo);
    if (status === "stale") {
      const was = (s.stale || {})[def.src] || {};
      if (def.key === "arrange" && was.plates != null) return t("flow.evidence.stale.lastPlates", { n: num(was.plates) });
      if (def.key === "export") return t("flow.evidence.stale.lastShape", { shape: esc(SHAPE_LABEL[was.shape] || was.shape || t("flow.shape.defaultProcess")) });
      if (def.key === "check" && was.grams_total != null) return t("flow.evidence.stale.lastCheck", { grams: num(was.grams_total), duration: duration(was.seconds_total) });
      return t("flow.evidence.stale.expired");
    }
    const parts = s.parts || [];
    const opts = s.options || {};
    if (def.key === "model") {
      const maxExt = Math.max(0, ...parts.map((p) => Math.max(...(p.extents_mm || [0]))));
      const bad = parts.filter((p) => !p.watertight).length;
      const big = parts.filter((p) => p.fits_bed === false).length;
      const key = bad && big ? "flow.evidence.model.summary.notWatertightAndTooBig" : bad ? "flow.evidence.model.summary.notWatertight" : big ? "flow.evidence.model.summary.tooBig" : "flow.evidence.model.summary.allGood";
      return t(key, { count: num(parts.length), maxExt: num(maxExt), bad: num(bad), big: num(big) });
    }
    if (def.key === "orient") {
      const now = sumOverhang(parts);
      const last = (s.history || []).find((h) => h.op === "orient" && h.ok && !h.undone);
      const before = last && last.summary ? last.summary.overhang_mm2_before : null;
      const manual = parts.filter((p) => p.orient && p.orient.strategy_used === "manual").length;
      let text = esc(STRATEGY_LABEL[opts.strategy] || opts.strategy || "");
      if (now != null) {
        text += before != null && Math.abs(before - now) > 1
          ? t("flow.evidence.orient.overhangChanged", { before: cm2(before), afterMarkup: `<b class="${now < before ? "good" : ""}">${cm2(now)}</b>` })
          : t("flow.evidence.orient.overhangSimple", { now: cm2(now) });
      }
      if (manual) text += t("flow.evidence.orient.manualCount", { count: manual });
      return text;
    }
    if (def.key === "arrange") {
      const n = (s.plates || []).length;
      return t("flow.evidence.arrange.summary", { plates: num(n), gap: num(opts.gap, 1) });
    }
    if (def.key === "export") {
      const ex = s.export || {};
      const preset = ex.process_preset ? esc(String(ex.process_preset).replace(/\s*@.*$/, "")) : t("flow.shape.defaultProcess");
      return t("flow.evidence.export.summary", { shape: esc(SHAPE_LABEL[opts.shape] || opts.shape || ""), preset }) + (item.status === "warn" ? t("flow.evidence.export.unmatchedWarning") : "");
    }
    if (def.key === "check") {
      const totals = checkTotals(s.check);
      const tail = totals.failed ? t("flow.count.platesFailedToSlice", { count: totals.failed }) : totals.warnings ? t("flow.count.warnings", { count: totals.warnings }) : t("flow.count.noWarnings");
      return t("flow.evidence.check.summary", { grams: num(totals.grams), duration: duration(totals.seconds), tail });
    }
    if (def.key === "deliver") {
      const plates = (s.sent && s.sent.plates) || [];
      return plates.length ? t("flow.evidence.deliver.opened", { plates: plates.map((p) => num(p)).join(t("common.listSeparator")) }) : esc(def.todo);
    }
    return "";
  }

  _renderCtx(s, readiness) {
    const parts = s.parts || [];
    const lastLoad = (s.history || []).find((h) => h.op === "load" && h.ok);
    const files = (lastLoad && lastLoad.summary && lastLoad.summary.files) || [];
    const title = !parts.length ? t("flow.ctx.noModel") : files.length ? files[0] + (files.length > 1 ? t("flow.ctx.andMoreFiles", { count: files.length }) : "") : parts.length === 1 ? parts[0].name : t("flow.ctx.partsCount", { count: parts.length });
    document.getElementById("ctx-file").textContent = title;
    const meta = [];
    if (parts.length) meta.push(t("flow.ctx.partsCountShort", { count: parts.length }));
    if (s.printer && s.printer.name) meta.push(String(s.printer.name).replace(/^Bambu Lab\s+/, ""));
    document.getElementById("ctx-meta").textContent = meta.join(" · ");

    const pill = document.getElementById("ready-pill");
    pill.hidden = !parts.length;
    document.getElementById("ready-text").textContent = `${readiness.passed} / ${readiness.total}`;
    const ring = document.getElementById("ready-ring");
    ring.style.setProperty("--frac", Math.round((100 * readiness.passed) / Math.max(1, readiness.total)) + "%");
    ring.classList.toggle("has-warn", (readiness.items || []).some((i) => ['warn', 'stale'].includes(i.status)));
    const list = document.getElementById("ready-list");
    if (!parts.length) { list.hidden = true; pill.setAttribute('aria-expanded', 'false'); }
    const markup = (readiness.items || [])
      .map((i) => `<button type="button" class="ready-item ${esc(i.status)}" data-readiness-step="${esc(i.key)}"><i aria-hidden="true"></i><span>${esc(READY_LABEL[i.key] || i.key)}${i.detail ? `<em>${esc(i.detail)}</em>` : ''}</span><small>${({ pass: t('flow.readinessStatus.pass'), warn: t('flow.readinessStatus.warn'), stale: t('flow.readinessStatus.stale'), run: t('flow.readinessStatus.run'), todo: t('flow.readinessStatus.todo') })[i.status] || t('flow.readinessStatus.todo')}</small></button>`)
      .join('');
    if (markup !== this._lastReadinessMarkup) { list.innerHTML = markup; this._lastReadinessMarkup = markup; }
  }

  _renderOrientParts(s, selectedName) {
    const box = document.getElementById("orient-parts");
    const parts = (s.parts || []).filter((p) => p.orient);
    if (!parts.length) {
      box.innerHTML = "";
      return;
    }
    const max = Math.max(1, ...parts.map((p) => p.orient.overhang_area_mm2 || 0));
    box.innerHTML = "";
    for (const p of parts) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "bar-row" + (p.name === selectedName ? " is-picked" : "");
      const manual = p.orient.strategy_used === "manual";
      row.innerHTML =
        `<span class="bar-name"><span>${esc(p.name)}</span>${manual ? `<span class="who me">${t('flow.who.manual')}</span>` : ""}</span>` +
        `<span class="bar-track"><i style="width:${Math.round((100 * (p.orient.overhang_area_mm2 || 0)) / max)}%"></i></span>` +
        `<span class="bar-val">${cm2(p.orient.overhang_area_mm2)} cm²</span>`;
      row.addEventListener("click", () => this.opts.onSelectPart && this.opts.onSelectPart(p.name === selectedName ? null : p.name));
      box.appendChild(row);
    }
  }

  _renderSelection(s, selectedName) {
    const chip = document.getElementById("sel-chip");
    const part = selectedName ? (s.parts || []).find((p) => p.name === selectedName) : null;
    if (!chip) {
      const shared = document.getElementById("sel-shared");
      if (shared) { shared.hidden = !s.selection; shared.textContent = t("flow.selection.aiSharedNote"); }
      return;
    }
    chip.hidden = !part;
    if (!part) return;
    document.getElementById("sel-name").textContent = part.name;
    const e = part.extents_mm || [];
    document.getElementById("sel-dims").textContent = e.length === 3 ? e.map((v) => num(v)).join(" × ") + " mm" : "";
    document.getElementById("sel-shared").hidden = !s.selection; // 后端不支持共享选区时不说这句话
    document.getElementById("sel-shared").textContent = t("flow.selection.aiSharedNote");
  }

  _renderHistory(s) {
    const list = document.getElementById("history");
    const entries = s.history || [];
    const count = document.getElementById('history-count');
    if (count) count.textContent = entries.length ? String(entries.length) : '';
    document.getElementById("history-empty").hidden = entries.length > 0;
    const key = entries.map((h) => `${h.id}:${h.undone ? 1 : 0}`).join(",") + "|" + (s.busy ? 1 : 0);
    if (key === this._lastHistoryKey) return;
    this._lastHistoryKey = key;
    list.innerHTML = "";
    const latestUndoable = entries.find((h) => h.undoable && !h.undone);
    for (const h of entries.slice(0, 30)) {
      const li = document.createElement("li");
      if (h.undone) li.classList.add("is-undone");
      if (!h.ok) li.classList.add("is-failed");
      const who = h.actor === "human" ? [t("flow.who.you"), "me"] : ["AI", "ai"];
      li.innerHTML = `<time>${esc(hhmm(h.at))}</time><span class="who ${who[1]}">${who[0]}</span><span class="what">${this._describe(h)}</span>`;
      if (h === latestUndoable) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "log-undo";
        btn.innerHTML = ICON.undo + `<span>${t("flow.op.undo")}</span>`;
        btn.disabled = !!s.busy;
        btn.addEventListener("click", () => this.opts.onUndo && this.opts.onUndo(h.id));
        li.appendChild(btn);
      } else {
        li.appendChild(document.createElement("span"));
      }
      list.appendChild(li);
    }
  }

  _describe(h) {
    const m = h.summary || {};
    const name = ({
      recipe: t("recipes.label"), load: t("flow.verb.model"), orient: t("flow.verb.orient"), arrange: t("flow.step.arrange.name"),
      export: t("flow.verb.export"), check: t("flow.step.check.name"), send: t("flow.verb.deliver"), prepare: t("flow.op.prepare"), undo: t("flow.op.undo"),
    })[h.op] || h.op;
    if (!h.ok) return t("flow.describe.failed", { name: esc(name) }) + (m.error ? t("flow.describe.errorParen", { error: esc(m.error) }) : "");
    if (h.op === "recipe") return t(m.action === "stop" ? "flow.describe.recipe.stopped" : "flow.describe.recipe.started", { title: esc(m.title || m.id || "") });
    if (h.op === "load") return t("flow.describe.load", { files: esc((m.files || []).join(t("common.listSeparator")) || t("flow.step.model.name")), parts: num(m.parts) });
    if (h.op === "orient") {
      const moved = m.overhang_mm2_before != null && m.overhang_mm2_after != null && Math.abs(m.overhang_mm2_before - m.overhang_mm2_after) > 1;
      const delta = moved
        ? t("flow.describe.orient.overhangChanged", { before: cm2(m.overhang_mm2_before), after: cm2(m.overhang_mm2_after) })
        : m.overhang_mm2_after != null ? t("flow.describe.orient.overhangSimple", { after: cm2(m.overhang_mm2_after) }) : "";
      if ((m.manual_parts || []).length) return t("flow.describe.orient.manualParts", { names: esc(m.manual_parts.join(t("common.listSeparator"))), delta });
      return t("flow.describe.orient.strategyUsed", { strategy: esc(STRATEGY_LABEL[m.strategy] || m.strategy || ""), delta });
    }
    if (h.op === "arrange") return t("flow.describe.arrange", { plates: num(m.plates) });
    if (h.op === "export") return t("flow.describe.export", { shape: esc(SHAPE_LABEL[m.shape] || m.shape || ""), plates: num(m.plates) });
    if (h.op === "check") return t("flow.describe.check", { grams: num(m.grams_total), duration: duration(m.seconds_total), tail: m.warnings_total ? t("flow.count.warnings", { count: m.warnings_total }) : t("flow.count.noWarnings") });
    if (h.op === "send") return t("flow.describe.send", { plates: esc((m.plates || []).join(t("common.listSeparator"))), dryRun: m.dry_run ? t("flow.describe.send.dryRunSuffix") : "" });
    if (h.op === "prepare") return t("flow.describe.prepare", { label: t("flow.op.prepare"), steps: esc((m.steps || []).map((k) => STEP_NAME[k] || (k === "open" ? t("flow.verb.deliver") : k)).join(t("common.listSeparator"))) });
    if (h.op === "undo") return t("flow.describe.undo", { target: esc({ orient: t("flow.verb.orient"), arrange: t("flow.step.arrange.name") }[m.target_op] || m.target_op || "") });
    return esc(name);
  }
}
