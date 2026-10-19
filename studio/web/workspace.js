// Shared workspace controller: transports supply API and optional geometry loading.
import { Viewport } from "./viewport.js";
import { createTasks } from "./tasks.js";
import { createServiceSettings } from "./service-settings.js";
import { createObserve } from './evaluation.js';
import { icon } from './vendor/ui/icons.js';
import { Panel } from "./panel.js";
import { Flow } from "./flow.js";
import { registerPageTools } from "./tools.js";
import { createEditor } from "./editor.js";
import { Recipes } from "./recipes.js";
import { t } from "./i18n.js";
import { createQuickAccess } from "./quick-access.js";
import { createRefreshQueue } from './refresh-queue.js';
import { createFitNotice } from './print-fit.js';
import { createLaser } from "./laser.js";
import { createManufacturing } from "./manufacturing.js";
import { createStart } from './start.js';
import { captureCamera, restoreCamera, viewModes } from './session-view.js';

const OP_LABELS = {
  load: t("flow.verb.model"),
  orient: t("flow.verb.orient"),
  arrange: t("workspace.op.arrange"),
  export: t("workspace.op.export"),
  check: t("workspace.op.check"),
  send: t("workspace.op.send"),
  prepare: t("flow.op.prepare"),
  undo: t("flow.op.undo"),
  state: t("workspace.op.state"),
  session: t("workspace.op.session"),
  local: t("workspace.op.local"),
  selectionSync: t("workspace.op.selectionSync"),
};

function createPrintWorkspace(api, options = {}) {
  const isMock = !!options.mock;
  let disposed = false, active = true, events = null, resizeObserver = null;
  const refresh = createRefreshQueue(readState);
  let selectionQueue = Promise.resolve(), pendingSelection = 0;


  let currentState = null;
  let localBusy = null; // 本页自己发起、尚未返回的写操作：{op, since}
  let lastError = null;
  let currentView = "assembly";
  let currentPlateIndex = 0;
  let autoPlateApplied = false;
  let statusTimer = null;
  let selectedName = null; // 视口、零件表、朝向行共用的选中零件
  let lastSelectionStamp = ""; // 后端 selection 的 by+at，用来判断是不是别人（AI）刚改的
  let geometryStamp = "", firstFit = true;

  const viewportEl = document.getElementById("viewport");
  const viewport = new Viewport(viewportEl, { mock: isMock, loadGeometry: options.loadGeometry });

  viewport.onSelect((name) => setSelection(name, { push: true, fromViewport: true }));
  viewport.onProgress((name, ratio, err, pending) => {
    updateLoadProgress(name, ratio, err);
    if (ratio === 1 && firstFit) {
      viewport.fitView();
      if (!pending) firstFit = false;
    }
  });
  viewport.onHover((name, x, y) => updateHoverTip(name, x, y));

  const panel = new Panel({
    onUpload: (file) => api.upload(file),
    onLoad: (body) => runAction("load", () => api.load(body)),
    onOrient: (body) => runAction("orient", () => api.orient(body)),
    onOrientSet: (name, vec, opts) =>
      runAction("orient", () => api.orient({ shape: opts && opts.shape, strategy: opts && opts.strategy, set: { [name]: vec } })),
    onArrange: (body) => runAction("arrange", () => api.arrange(body)),
    onExport: (body) => runAction("export", () => api.exportProject(body)),
    onCheck: (body) => runAction("check", () => api.check(body)),
    onSend: (body) => runAction("send", () => api.send(body)),
    onPrepare: (body) => runAction("prepare", () => api.prepare(body)),
    onSelectPart: (name) => setSelection(name, { push: true, fromPanel: true }),
    onPlateChange: (plateNumber) => {
      const plates = (composedState() && composedState().plates) || [];
      const i = plates.findIndex((pl) => pl.index === plateNumber);
      if (i < 0 || i === currentPlateIndex) return;
      currentPlateIndex = i;
      viewport.setPlateIndex(i);
      renderPlateTabs(composedState());
    },
    // viewport.getPartColor 由另一位实现者添加（SPEC.md §8），可能还没合入，做降级处理。
    getPartColor: (name) => (typeof viewport.getPartColor === "function" ? viewport.getPartColor(name) : null),
    onLocalError: (msg) => {
      lastError = { op: "local", code: "bad_arguments", message: msg };
      renderAll();
    },
  });

  const flow = new Flow({
    onSelectPart: (name) => setSelection(name, { push: true }),
    onUndo: (id) => runAction("undo", () => api.undo(id)),
    onRedo: (steps) => redoSteps(steps),
    onOpenStep: openPrintStep,
  });

  const fitNotice = createFitNotice({
    onCut: name => options.onPrintCut?.(currentState, name),
    onAutoCut: () => {
      const arrange = panel.useAutomaticArrangement();
      if (!arrange) return false;
      const settings = panel.bodyFor('export');
      return runAction('prepare', () => api.prepare({ auto_cut: true,
        expected_inspect_rev: currentState.inspect_rev, gap: arrange.gap,
        shape: settings.shape, process: settings.process, filament: settings.filament,
        export_set: settings.set, no_project: settings.no_project }), () => {
        panel.syncModelInputs(currentState, { force: true });
        currentPlateIndex = 0; viewport.setPlateIndex(0); setViewInternal('plate');
        viewport.fitView();
      });
    },
    onOrient: () => openPrintStep('orient'),
    onMultiPlate: () => {
      const body = panel.useAutomaticArrangement();
      return body ? runAction('arrange', () => api.arrange(body)) : false;
    },
  });

  wireViewportHud();
  setViewInternal("assembly");
  wireStatusBar();
  const disposeCards = wireResponsiveCards();
  wireViewInsets();
  if (!api.upload) document.getElementById("drop-zone").hidden = true;
  renderAll();
  const ready = main();

  async function main() {
    if (!isMock) {
      await initSessionWithRetry();
    }
    try {
      const printersResp = await api.getPrinters();
      panel.setPrinters(printersResp.printers || []);
      panel.setSlicers(printersResp.slicers || []);
    } catch (e) {
      lastError = { op: "session", code: e.code || "error", message: t("workspace.status.printersLoadFailed", { detail: e.message }) };
    }
    // GET /api/shapes 由另一位实现者添加（SPEC.md §9），可能还没合入；失败不致命。
    try {
      if (typeof api.getShapes === "function") {
        const shapesResp = await api.getShapes();
        panel.setShapes((shapesResp && shapesResp.shapes) || []);
      } else {
        panel.setShapes([]);
      }
    } catch (e) {
      panel.setShapes([]);
    }
    if (api.getTools) {
      try {
        const message = await registerPageTools(await api.getTools(), api);
        document.getElementById("status-tools").textContent = t("workspace.status.pageToolsPrefix", { message });
      } catch (e) {
        document.getElementById("status-tools").textContent = t("workspace.status.pageToolsUnavailable");
      }
    } else document.getElementById("status-tools").textContent = "";

    await refresh();

    if (!isMock && api.subscribeEvents) {
      events = api.subscribeEvents(
        (rev) => {
          if (!currentState || rev !== currentState.rev) refresh(true);
        },
        () => stopPolling(),
        () => startPolling()
      );
    } else if (!isMock) startPolling();
  }

  async function initSessionWithRetry() {
    while (!disposed) {
      try {
        await api.init();
        lastError = null;
        return;
      } catch (e) {
        lastError = { op: "session", code: e.code || "network_error", message: e.message || t("workspace.status.cannotReachLocalService") };
        renderAll();
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  }

  let pollTimer = null;
  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(() => { if (active && !document.hidden) refresh(); }, 3000);
  }
  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function readState() {
    if (disposed) return;
    try {
      const next = await api.getState();
      const changed = JSON.stringify(next) !== JSON.stringify(currentState);
      const recovered = lastError?.op === "state";
      currentState = next;
      if (recovered) lastError = null;
      options.onState?.(next);
      if (!disposed && (changed || recovered || lastError?.op === "preview")) renderAll();
    } catch (e) {
      lastError = { op: "state", code: e.code || "error", message: e.message || t("workspace.status.stateReadFailed") };
      if (!disposed) renderAll();
    }
  }

  function composedState() {
    if (!currentState) return null;
    if (!localBusy) return currentState;
    return Object.assign({}, currentState, { busy: { ...localBusy, detail: currentState.busy?.detail } });
  }

  async function runAction(op, fn, onSuccess) {
    const cur = composedState();
    if (!cur || cur.busy) return false; // 服务器已在忙，防御性丢弃（按钮理应已置灰）
    lastError = null;
    localBusy = { op, since: new Date().toISOString(), actor: "human" };
    fitNotice.reset();
    renderAll();
    try {
      await fn();
      lastError = null;
    } catch (e) {
      lastError = { op, code: (e && e.code) || "error", message: (e && e.message) || String(e), payload: e?.payload };
    } finally {
      // Keep controls locked until the final snapshot AND its form fields agree.
      // Unlocking before refresh lets a second click consume the previous model.
      await refresh(true);
      if (!lastError) onSuccess?.();
      localBusy = null;
      if (!disposed) renderAll();
    }
    return !lastError;
  }

  function renderAll() {
    if (disposed) return;
    const s = composedState();
    if(s && api.workspaceId) for(const part of s.parts || []) {
      if(part.stl_url && !part.stl_url.includes('workspace='))part.stl_url+=(part.stl_url.includes('?')?'&':'?')+'workspace='+encodeURIComponent(api.workspaceId);
    }
    adoptRemoteSelection(s);
    panel.render(s);
    flow.render(s, { selectedName });
    if (pendingSelection) document.getElementById("sel-shared").textContent = t("workspace.selection.syncing");
    if (s) {
      const stamp = JSON.stringify(s.parts?.map((p) => p.stl_url));
      if (stamp !== geometryStamp) { geometryStamp = stamp; firstFit = true; }
      const priorView = currentView;
      const priorPrinter = viewport._lastPrinterKey;
      maybeAutoSwitchView(s);
      viewport.update(s);
      if (priorView !== currentView || priorPrinter !== viewport._lastPrinterKey) viewport.fitView();
    }
    renderBedReference(s);
    renderPlateTabs(s);
    updateStatusBar(s);
    fitNotice.update(lastError || s?.last_error, s, active);
  }

  // ------------------------------------------------------------- 视口 HUD
  function wireViewportHud() {
    const viewButtons = [...document.querySelectorAll(".view-btn")];
    viewButtons.forEach((b) =>
      b.addEventListener("click", () => {
        setViewInternal(b.dataset.view);
        renderPlateTabs(composedState());
        viewport.fitView();
      })
    );
    document.getElementById("fit-view").addEventListener("click", () => viewport.fitView());
  }

  function setViewInternal(mode) {
    currentView = mode;
    viewport.setView(mode);
    document.querySelectorAll(".view-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === mode)));
  }

  function renderBedReference(state) {
    const label = document.getElementById('bed-reference');
    label.hidden = !state || !viewport.bedGroup.visible;
    if (label.hidden) return;
    const [width, depth, height] = state.printer.bed_mm;
    label.querySelector('strong').textContent = t('print.hud.bedReference', {
      name: state.printer.name, width, depth,
    });
    label.querySelector('small').textContent = t('print.hud.bedScale', { height: height ?? '—' });
  }

  function maybeAutoSwitchView(state) {
    const hasPlates = !!(state.plates && state.plates.length);
    if (hasPlates && !autoPlateApplied) {
      autoPlateApplied = true;
      setViewInternal("plate");
    } else if (!hasPlates) {
      autoPlateApplied = false;
      if (currentView === "plate") setViewInternal("assembly");
    }
  }

  function renderPlateTabs(state) {
    const wrap = document.getElementById("plate-tabs");
    const plates = state && state.plates;
    if (!plates || !plates.length) {
      wrap.hidden = true;
      wrap.innerHTML = "";
      return;
    }
    wrap.hidden = false;
    if (currentPlateIndex >= plates.length) currentPlateIndex = 0;
    wrap.innerHTML = "";
    plates.forEach((p, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = t("workspace.plate.label", { index: p.index });
      btn.className = "view-btn";
      btn.setAttribute("aria-pressed", String(i === currentPlateIndex));
      btn.addEventListener("click", () => {
        currentPlateIndex = i;
        viewport.setPlateIndex(i);
        renderPlateTabs(state);
        if (typeof panel.setViewPlate === "function") panel.setViewPlate(p.index);
      });
      wrap.appendChild(btn);
    });
    viewport.setPlateIndex(currentPlateIndex);
    if (typeof panel.setViewPlate === "function" && plates[currentPlateIndex]) panel.setViewPlate(plates[currentPlateIndex].index);
  }

  function updateLoadProgress(name, ratio, err) {
    if (disposed) return;
    if (err) {
      lastError = { op: "preview", code: "preview_error", message: t("workspace.status.previewLoadFailed", { detail: err.message || err }) };
      updateStatusBar(composedState());
    } else if (ratio === 1 && lastError?.op === "preview") {
      lastError = null;
      updateStatusBar(composedState());
    }
    if (!updateLoadProgress._rows) updateLoadProgress._rows = new Map();
    const rows = updateLoadProgress._rows;
    if (ratio === 1 || ratio === -1) rows.delete(name);
    else rows.set(name, { ratio, err });
    const box = document.getElementById("load-progress");
    if (!rows.size) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = "";
    for (const [n, info] of rows) {
      const row = document.createElement("div");
      row.className = "progress-row";
      const pct = Math.round((info.ratio || 0) * 100);
      row.innerHTML = `<span></span><span class="bar"><i style="width:${pct}%"></i></span><span>${pct}%</span>`;
      row.firstChild.textContent = n; // part names come from user file names: never through innerHTML
      box.appendChild(row);
    }
  }

  function updateHoverTip(name, x, y) {
    const tip = document.getElementById("hover-tip");
    if (!name) {
      tip.hidden = true;
      return;
    }
    tip.hidden = false;
    tip.textContent = name;
    tip.style.left = x + 14 + "px";
    tip.style.top = y + 14 + "px";
  }

  function wireResponsiveCards() {
    const cardIds = ["card-arrange", "card-model", "card-selected"];
    const dock = document.getElementById("cards-dock");
    const original = new Map();
    for (const id of cardIds) {
      const node = document.getElementById(id);
      original.set(id, { parent: node.parentNode, next: node.nextSibling });
    }
    function apply(isNarrow) {
      if (isNarrow) {
        for (const id of cardIds) dock.appendChild(document.getElementById(id));
      } else {
        for (const id of cardIds) {
          const node = document.getElementById(id);
          const info = original.get(id);
          if (info.next && info.next.parentNode === info.parent) info.parent.insertBefore(node, info.next);
          else info.parent.appendChild(node);
        }
      }
    }
    const mq = window.matchMedia("(max-width: 599px)");
    apply(mq.matches);
    const onChange = (e) => apply(e.matches);
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else mq.addListener(onChange);
    return () => { if (mq.removeEventListener) mq.removeEventListener("change", onChange); else mq.removeListener(onChange); };
  }


  // Floating-card insets keep the model clear without resizing the canvas.
  function wireViewInsets() {
    if (typeof viewport.setViewInsets !== "function" || typeof ResizeObserver !== "function") return;
    const col = document.getElementById("stage");
    const card = document.getElementById("card-arrange");
    const hud = document.getElementById("viewport-hud");
    let lastKey = "";
    const compute = () => {
      const colRect = col.getBoundingClientRect();
      let right = 0;
      if (card && card.parentElement === col && !card.hidden) {
        const r = card.getBoundingClientRect();
        if (r.height > 80) right = Math.max(0, colRect.right - r.left);
      }
      const bottom = hud ? Math.max(0, colRect.bottom - hud.getBoundingClientRect().top) : 0;
      viewport.setViewInsets({ left: 0, right, top: 0, bottom });
      const key = `${Math.round(right)}|${Math.round(colRect.width)}`;
      if (key !== lastKey) {
        lastKey = key;
        if (!viewport.userMoved) viewport.fitView();
      }
    };
    const ro = resizeObserver = new ResizeObserver(compute);
    ro.observe(col);
    if (card) ro.observe(card);
    compute();
  }

  // ------------------------------------------------------------- 选区：人和 AI 共用
  // 人在视口、零件表或朝向行里点中的零件会告诉后端（AI 读状态时看得到）；AI 用 studio_select 指的零件也会在这里亮起来。
  function setSelection(name, how) {
    const next = name || null;
    const changed = next !== selectedName;
    selectedName = next;
    if (!(how && how.fromViewport)) viewport.selectPart(next);
    panel.setSelectedPart(next);
    flow.render(composedState(), { selectedName });
    if (changed && how && how.push && typeof api.select === "function") {
      pendingSelection++;
      document.getElementById("sel-shared").textContent = t("workspace.selection.syncing");
      selectionQueue = selectionQueue.then(async () => {
        try {
          await api.select(next ? [next] : []);
        } catch (e) {
          lastError = { op: "selectionSync", code: e.code || "error", message: e.message };
        } finally {
          pendingSelection--;
          if (!pendingSelection) {
            lastSelectionStamp = "";
            await refresh();
            renderAll();
          }
        }
      });
    }
  }

  function adoptRemoteSelection(s) {
    const sel = s && s.selection;
    if (!sel || pendingSelection) return;
    const stamp = `${sel.by || ""}|${sel.at || ""}|${(sel.parts || []).join(",")}`;
    if (stamp === lastSelectionStamp) return;
    lastSelectionStamp = stamp;
    const remote = (sel.parts || [])[0] || null;
    if (remote === selectedName) return;
    if (remote && !(s.parts || []).some((p) => p.name === remote)) return;
    selectedName = remote;
    viewport.selectPart(remote);
    panel.setSelectedPart(remote);
  }

  // ------------------------------------------------------------- 把作废的后续步骤按顺序重做
  async function redoSteps(steps) {
    const order = ["orient", "arrange", "export", "check"];
    const call = { orient: api.orient, arrange: api.arrange, export: api.exportProject, check: api.check };
    for (const step of order.filter((k) => steps.includes(k))) {
      const body = panel.bodyFor(step);
      if (!body) return;
      const done = await runAction(step, () => call[step](body));
      if (!done) {
        if (!lastError) {
          lastError = { op: step, code: "busy", message: t("workspace.status.previousStepBusy") };
          renderAll();
        }
        return;
      }
    }
  }

  function wireStatusBar() {
    document.getElementById("status-error-close").addEventListener("click", () => {
      lastError = null;
      renderAll();
    });
  }

  function updateBusyCard(busy) {
    const card = document.getElementById("busy-card");
    if (!busy) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    const since = new Date(busy.since).getTime();
    const elapsed = Math.max(0, Math.round((Date.now() - since) / 1000));
    document.getElementById("busy-card-title").textContent = busy.detail || t("workspace.busyCard.title", { label: OP_LABELS[busy.op] || busy.op });
    document.getElementById("busy-card-time").textContent = t("workspace.busyCard.elapsed", { seconds: elapsed });
  }

  function updateStatusBar(s) {
    const busy = s?.busy || localBusy;
    updateBusyCard(busy);
    const busyEl = document.getElementById("status-busy");
    if (busy) {
      if (!statusTimer) statusTimer = setInterval(() => updateStatusBar(composedState()), 1000);
      const since = new Date(busy.since).getTime();
      const elapsed = Math.max(0, Math.round((Date.now() - since) / 1000));
      const label = OP_LABELS[busy.op] || busy.op;
      busyEl.textContent = (isMock ? t("workspace.status.mockPrefix") : "") + t("workspace.status.busyLine", { label, seconds: elapsed });
    } else {
      if (statusTimer) {
        clearInterval(statusTimer);
        statusTimer = null;
      }
      busyEl.textContent = (isMock ? t("workspace.status.mockPrefix") : "") + t("workspace.status.idle");
    }

    const errWrap = document.getElementById("status-error");
    const errText = document.getElementById("status-error-text");
    if (lastError) {
      errWrap.hidden = false;
      const label = OP_LABELS[lastError.op] || lastError.op;
      let msg = t("workspace.status.errorLine", { label, code: lastError.code, message: lastError.message });
      if (lastError.code === "busy") msg = t("workspace.status.busyRetryHint");
      errText.textContent = msg;
    } else {
      errWrap.hidden = true;
    }

    document.getElementById("status-rev").textContent = s ? `rev ${s.rev}` : isMock ? "" : t("workspace.status.notConnected");
  }

  function openPrintStep(row) {
    const controls = { model: 'btn-load', orient: 'btn-orient', arrange: 'btn-arrange', export: 'btn-export', check: 'btn-check', deliver: 'btn-send' };
    if (!controls[row]) return;
    document.getElementById('plan-reopen').click();
    const card = row === 'model' ? 'card-model' : ['orient', 'arrange'].includes(row) ? 'card-arrange' : null;
    if (card) panel.openCard(card);
    const target = document.getElementById(card ? controls[row] : ({ deliver: 'block-send', export: 'block-export', check: 'block-check' }[row]));
    (target?.classList.contains('compat-anchor') ? target.firstElementChild : target)?.scrollIntoView({ block: 'nearest' });
    document.getElementById(controls[row]).focus({ preventScroll: true });
  }

  return {
    ready, refresh, openRow: openPrintStep,
    getPresentation:()=>({camera:captureCamera(viewport),view:currentView,plate:currentPlateIndex}),
    async waitForPresentation(){const until=Date.now()+5000;while(viewport._pending && Date.now()<until)await new Promise(r=>setTimeout(r,50));await viewport._loop.waitForFrame();},
    async restorePresentation(value) {
      await ready;await refresh();autoPlateApplied=true;
      if(['assembly','plate'].includes(value?.view))currentView=value.view;
      if(Number.isInteger(value?.plate)&&value.plate>=0)currentPlateIndex=value.plate;
      setViewInternal(currentView);viewport.setPlateIndex(currentPlateIndex);renderAll();
      const until=Date.now()+5000;while(viewport._pending && Date.now()<until)await new Promise(r=>setTimeout(r,50));
      restoreCamera(viewport,value?.camera);
    },
    async syncModel() { await ready; lastError = null; fitNotice.reset(); await refresh(true); finishModelLoad(); },
    async loadTaskModel(taskId, artifactId) {
      await ready;
      const ok = await runAction('load', () => api.load({ task_id: taskId, artifact_id: artifactId, printer: document.getElementById('printer-select').value || undefined }), finishModelLoad);
      if (!ok) throw new Error(lastError?.message || t('workspace.status.busyRetryHint'));
    },
    async loadPose(files) {
      await ready;
      const ok = await runAction('load', async () => {
        const paths = [];
        for (const file of files) paths.push((await api.upload(file)).path);
        await api.load({ files: paths, printer: document.getElementById('printer-select').value || undefined });
      }, finishModelLoad);
      if (!ok) throw new Error(lastError?.message || t('workspace.status.busyRetryHint'));
    },
    setState(next) { currentState = next; options.onState?.(next); renderAll(); },
    setActive(value) { active = value; viewport.setActive(value && !document.hidden); fitNotice.update(lastError || currentState?.last_error, composedState(), active); if (value) refresh(); },
    dispose() { disposed = true; stopPolling(); clearInterval(statusTimer); events?.close(); resizeObserver?.disconnect(); disposeCards?.(); fitNotice.dispose(); viewport.dispose(); },
  };

  function finishModelLoad() {
    panel.syncModelInputs(currentState, { force: true });
    document.getElementById('plan-reopen').click();
    panel.openCard('card-model'); panel.openCard('card-arrange');
  }
}

// A recipe step's `tool` may carry a `#action`/`#template`/`#operation` suffix
// (recipes/README.md; `studio.core.recipes._step_call`, e.g. `studio_edit#plane_cut`,
// `studio_task#assembly-audit`). Every router below must compare this base name, not
// the whole string, or a suffixed step silently falls through to the wrong workspace
// (see tests/test_v04_workspace.mjs).
export function recipeStepBaseTool(step) {
  return String(step?.tool || "").split("#")[0];
}

export function recipeVisibleInWorkspace(mode, recipe, preview = null) {
  if (mode === 'home') return false;
  if (mode === 'motion' || mode === 'observe' || (mode === 'tasks' && preview)) return false;
  if (!recipe) return mode === 'tasks';
  return mode === (recipe.workspace || 'print');
}

// Each mode owns its controls and camera; they share the same transport and
// backend. A print job is a deliberate copy of editable assets, not their state.
export function createWorkspace(api, options = {}) {
  let editor = null, print = null, mode = options.mock ? "print" : "home", active = true, nextState = null;
  let editorChosen = false;
  let tasks = null, observe = null, manufacture = null, laser = null, previewResult = null;
  let savedViews={},restoringChild=Promise.resolve();
  let navigations = 0;
  const workflow = document.createElement('details'); workflow.className = 'workspace-workflow';
  const workflowSummary = document.createElement('summary');
  const recipeElement = document.getElementById('recipe');
  recipeElement.before(workflow); workflow.append(workflowSummary, recipeElement);
  let disposed = false, updateBusy = false, updatesTimer = null;
  const start = createStart({
    onResume: () => { show('edit'); editor.fitView(); },
    onResults: () => access.openResults(),
    onOpen: async files => {
      const paths = [];
      for (const file of files) paths.push((await api.upload(file)).path);
      const state = await api.getState();
      await api.edit({ action: 'import', expected_revision: state.workbench.revision,
        params: { files: paths, ...(!state.workbench.collaboration ? { new_scene: true } : {}) } });
      nextState = await api.getState();
      show('edit'); editor.endPrintCut(); editor.setState(nextState);
    },
  });
  document.getElementById('editor-space').before(start.root);
  const access = createQuickAccess({ api,
    onModel: () => { show('edit'); editor.fitView(); },
    onOpenFile: () => { if (!editorChosen) start.openFile(); else { show('edit'); editor.openFile(); } },
    onOpenResult: (id, files, artifactId) => openResult(id, files, artifactId),
    onPrintTask: async (id, artifactId) => { show('print'); await print.loadTaskModel(id, artifactId); },
    onAttachSelection: options.onAttachSelection ? async () => {
      if (mode === 'motion') editor?.pauseMotion();
      await publishSelection();
      await options.onAttachSelection();
    } : undefined,
    onOpenHistory: () => { show('tasks'); tasks.openHistory(); },
  });
  async function openResult(id, files = false, artifactId = null, artifactName = null) {
    show('tasks');
    // Restoring a saved task view is asynchronous. Let it settle before the
    // explicit result selection, so the old view cannot replace this click.
    await restoringChild.catch(() => {});
    try { await tasks.openResult(id, files, artifactId, artifactName); }
    catch (e) {
      const error = document.getElementById('recipe-error');
      error.textContent = e.message; error.hidden = false;
    }
  }
  async function pollUpdates() {
    if (disposed || !active || document.hidden || updateBusy || !api.tasks) return;
    updateBusy = true;
    try {
      if (['home', 'tasks', 'observe'].includes(mode)) { nextState = await api.getState(); renderRecipe(); }
      const result = await api.tasks();
      access.setResults(result.tasks);
    } catch (error) { access.setError(error); }
    finally { updateBusy = false; }
  }
  const child = () => mode === 'home' ? null : mode === 'laser' ? laser : mode === 'manufacture' ? manufacture : mode === 'observe' ? observe : mode === 'tasks' ? tasks : ['edit','motion'].includes(mode) ? editor : print;
  let recipes = null, recipeBusy = false;
  const renderRecipe = () => {
    start.setState(nextState);
    access.setState(nextState);
    recipes?.render({ ...nextState, busy: recipeBusy || nextState?.busy });
    if (!recipeVisibleInWorkspace(mode, nextState?.recipe, previewResult)) recipeElement.hidden = true;
    workflow.hidden = recipeElement.hidden;
    workflowSummary.textContent = t('entry.projectWorkflow', { name: nextState?.recipe?.title || nextState?.recipe?.name || t('entry.chooseWorkflow') });
  };
  const publishSelection = () => nextState && options.onSelectionContext?.({ mode, state: nextState, motion: mode === 'motion' ? editor?.getMotionContext() : null,
    modelSource:mode==='tasks'&&previewResult?.type==='glb'&&!previewResult.loading?{task_id:previewResult.task.id,artifact_id:previewResult.artifact.id}:null,
    hasModel:mode==='tasks'?previewResult?.type==='glb'&&!previewResult.loading:['edit','motion'].includes(mode)?Boolean(nextState.workbench?.objects?.length):['print','manufacture','laser'].includes(mode)?Boolean(nextState.parts?.length||nextState.workbench?.objects?.length):false });
  const childOptions = { ...options, onMotionContextChange: publishSelection, onState(next) { nextState = next; renderRecipe(); options.onState?.(next); publishSelection(); } };
  async function runRecipe(fn, viewMode = null) {
    if (recipeBusy || nextState?.busy) return false;
    recipeBusy = true; renderRecipe();
    const error = document.getElementById("recipe-error"); error.hidden = true;
    try {
      await fn();
      const state = await api.getState(); nextState = state;
      if (viewMode || state.recipe?.workspace) show(viewMode || state.recipe.workspace);
      editor?.setState(state); print?.setState(state);
      return true;
    } catch (e) { error.textContent = e.message; error.hidden = false; return false; }
    finally { recipeBusy = false; renderRecipe(); }
  }
  function openRecipeStep(row, step) {
    const base = recipeStepBaseTool(step);
    if (nextState?.recipe?.workspace === 'tasks') {
      const recipe = nextState.recipe;
      if (step.key === 'appearance' && recipe.task_id) {
        let observationId = recipe.observation_id;
        return runRecipe(async () => {
          const prior = observationId ? await api.tasks(observationId) : null;
          if (!prior || ['failed', 'cancelled', 'interrupted'].includes(prior.task.status)) {
            const { task } = await api.tasks(recipe.task_id);
            const names = ['inspection/source-reference/scene.glb', 'scene.glb'];
            const inputs = names.map((name) => task.artifacts.find((a) => a.name === name)?.path);
            if (inputs.some((p) => !p)) throw new Error(t('workspace.appearanceCompare.requiresGeneratedResult'));
            const result = await api.observe({
              action: 'start', inputs,
              labels: [t('workspace.appearanceCompare.sourceLabel'), t('workspace.appearanceCompare.resultLabel')],
              params: { views: ['front', 'iso'] },
            });
            observationId = result.task.id;
          }
        }, 'observe').then((ok) => { if (ok) observe.setState({ focus_task_id: observationId }); });
      }
      show('tasks');
      const taskId = recipe.task_id;
      return tasks
        .openRecipe(
          recipe.task_template,
          taskId,
          ['prepare', 'generate'].includes(step.key)
            ? 'parameters'
            : step.key === 'sight'
              ? 'inspection/sight/sight-samples.svg'
              : taskId
                ? 'report.json'
                : null
        )
        .catch((e) => {
          const error = document.getElementById('recipe-error');
          error.textContent = e.message;
          error.hidden = false;
        });
    }
    if (nextState?.recipe?.workspace === "edit" || base === "studio_edit") {
      show("edit"); editor.openAction(step?.args?.action || "import");
    } else if (base === "studio_task") {
      // Generic (non-workspace:"tasks") recipes can still reference a studio_task
      // step (a local template or a hosted operation, via `tool#suffix`); those have
      // no row in the print pipeline's controls map, so open the tasks workspace
      // pre-filled with the referenced template/operation instead of a no-op.
      show("tasks");
      const templateId = step?.call?.template ?? step?.call?.operation ?? step?.args?.template ?? null;
      return tasks.openRecipe(templateId, null, null).catch((e) => {
        const error = document.getElementById('recipe-error');
        error.textContent = e.message;
        error.hidden = false;
      });
    } else { show("print"); print.openRow(row); }
  }
  recipes = new Recipes({ autoStart: false, loadList: () => api.getRecipes(),
    loadRecipe: (id) => api.getRecipe(id),
    onUse: async (id) => {
      const ok = await runRecipe(() => api.useRecipe(id));
      if (ok && nextState?.recipe?.workspace === 'tasks') await tasks.openRecipe(nextState.recipe.task_template);
      return ok;
    },
    onOpenRow: openRecipeStep,
    onRunStep(step) {
      const methods = { studio_orient: "orient", studio_arrange: "arrange", studio_export: "exportProject",
        studio_check: "check", studio_send_to_bambu: "send", studio_send_to_slicer: "send" };
      const method = methods[step.tool];
      if (!method || recipeStepBaseTool(step) === "studio_edit") return openRecipeStep(step.row, step);
      return runRecipe(() => api[method](step.args || {}));
    }, onRunOneShot: (recipe) => runRecipe(() => api.prepare(recipe.one_shot.args || {})),
  });
  const serviceButton = document.getElementById('service-settings-open');
  const serviceSettings = api.services ? createServiceSettings(api, id => tasks?.refreshServices(id)) : null;
  serviceButton.hidden = !serviceSettings;
  serviceButton.onclick = () => serviceSettings?.open();
  const buttons = [...document.querySelectorAll("[data-workspace-mode]")];
  document.querySelector('.wb-symbol').innerHTML = icon('box');
  const navIcons = {edit:'layers', motion:'clapperboard', tasks:'wand-sparkles', observe:'scan-eye', print:'printer', manufacture:'package-check', laser:'scan-eye'};
  buttons.forEach(b => { if (!b.querySelector('svg')) b.insertAdjacentHTML('afterbegin', icon(navIcons[b.dataset.workspaceMode])); });
  function show(value) {
    navigations++;
    mode = ['home', 'edit', 'motion', 'print', 'tasks', 'observe', 'manufacture', 'laser'].includes(value) ? value : 'home';
    if (mode === 'home') editorChosen = false;
    if (['edit', 'motion'].includes(mode)) editorChosen = true;
    start.root.hidden = mode !== 'home';
    workflow.open = !['edit', 'motion', 'print'].includes(mode);
    document.getElementById("editor-space").hidden = !["edit","motion"].includes(mode);
    document.getElementById("print-space").hidden = mode !== "print";
    document.getElementById('task-space').hidden = mode !== 'tasks';
    document.getElementById('observe-space').hidden = mode !== 'observe';
    document.getElementById('laser-space').hidden = mode !== 'laser';
    document.getElementById('manufacture-space').hidden = mode !== 'manufacture';
    renderRecipe();
    access.setMode(mode);
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.workspaceMode === mode)));
    if (["edit","motion"].includes(mode) && !editor) editor = createEditor(api, { ...childOptions, onPrint: () => { show("print"); return print.syncModel(); }, onMotion: () => show("motion"), onResults: () => access.openResults() });
    if (mode === "print" && !print) print = createPrintWorkspace(api, { ...childOptions,
      onPrintCut: async (source, name) => {
        show('edit');
        try { await editor.openPrintCut(source, name); return true; }
        catch (error) { show('print'); throw error; }
      },
    });
    if (mode === 'tasks' && !tasks) tasks = createTasks(api, {
      serviceSettings, importIntoNewScene: () => !editorChosen,
      onImport: async () => {
        const fresh = !editorChosen;
        // Adopt the completed import before creating/showing the editor so the
        // saved scene cannot flash or start loading while a refresh is pending.
        nextState = await api.getState();
        show('edit'); if (fresh) editor.endPrintCut(); editor.setState(nextState);
      },
      onPrintTask: async (id, artifactId) => { show('print'); await print.loadTaskModel(id, artifactId); },
      onPrintPose: async files => { show('print'); await print.loadPose(files); },
      onPreview: result => { previewResult = result; access.setPreview(result); renderRecipe(); publishSelection(); },
    });
    if (mode === 'manufacture' && !manufacture) manufacture = createManufacturing(api, {
      onResult: (id, files) => openResult(id, files),
      onService: async (provider, operation) => { show('tasks'); await tasks.openService(provider, operation); },
    });
    if (mode === 'laser' && !laser) laser = createLaser(api, {onModel: async path => {
      const state=await api.getState();
      await api.edit({action:'import',expected_revision:state.workbench.revision,params:{files:[path]}});
      nextState=await api.getState();show('edit');editor.setState(nextState);
    }});
    if (mode === 'observe' && !observe) observe = createObserve(api);
    editor?.setWorkspaceMode(mode);
    editor?.setActive(active && ["edit","motion"].includes(mode));
    print?.setActive(active && mode === "print");
    tasks?.setActive(active && mode === 'tasks');
    observe?.setActive(active && mode === 'observe');
    laser?.setActive(active && mode === 'laser');
    manufacture?.setActive(active && mode === 'manufacture');
    if (nextState) child()?.setState(nextState);
    const viewKey=['edit','motion'].includes(mode)?'edit':mode;
    if(savedViews[viewKey] && child()?.restorePresentation){
      const value=savedViews[viewKey];delete savedViews[viewKey];
      const target=child();restoringChild=Promise.resolve(target.ready).then(()=>target.restorePresentation(value));
      restoringChild.catch(()=>{});
    }
    publishSelection();
  }
  buttons.forEach((b) => { b.onclick = () => show(!editorChosen && ['edit', 'motion'].includes(b.dataset.workspaceMode) ? 'home' : b.dataset.workspaceMode); });
  const brand = document.querySelector('.wb-brand');
  brand.tabIndex = 0; brand.setAttribute('role', 'button'); brand.setAttribute('aria-label', t('start.back'));
  brand.onclick = () => show('home');
  brand.onkeydown = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); show('home'); } };
  show(mode);
  updatesTimer = setInterval(pollUpdates, 2000); pollUpdates();
  const ready = (child()?.ready || (async () => { await api.init(); nextState = await api.getState(); renderRecipe(); })()).then(async () => {
    if (api.getRecipes) { await recipes.start(); renderRecipe(); }
  });
  return {
    ready,
    openResult,
    getPresentation:()=>({mode,edit:editor?.getPresentation()||savedViews.edit,print:print?.getPresentation()||savedViews.print,tasks:tasks?.getPresentation()||savedViews.tasks,
      observe:observe?.getPresentation()||savedViews.observe,manufacture:manufacture?.getPresentation()||savedViews.manufacture,laser:laser?.getPresentation()||savedViews.laser}),
    async restorePresentation(value) {
      if(!value||!viewModes.includes(value.mode))return;
      savedViews={...value};show(value.mode);await child()?.ready;await restoringChild;
      await child()?.waitForPresentation?.();
      publishSelection();
    },
    async openLaser(id,stage) {show('laser');return laser.openWorkflow(id,stage);},
    async openManufacture(id) {show('manufacture');return manufacture.openWorkflow(id);},
    get hasNavigated() { return navigations > 1; },
    setMode: show,
    setState(state) { nextState = state; renderRecipe(); if (state.workspace_mode) show(state.workspace_mode); editor?.setState(state); print?.setState(state); observe?.setState(state); tasks?.setState(state); manufacture?.setState(state); laser?.setState(state); publishSelection(); },
    setActive(value) { if (active === value) return; active = value; editor?.setActive(value && ["edit","motion"].includes(mode)); print?.setActive(value && mode === "print"); tasks?.setActive(value && mode === 'tasks'); observe?.setActive(value && mode === 'observe'); manufacture?.setActive(value && mode === 'manufacture'); laser?.setActive(value && mode === 'laser'); },
    dispose() { disposed = true; clearInterval(updatesTimer); start.dispose(); access.dispose(); serviceSettings?.dispose(); serviceButton.onclick = null; recipes?.dispose(); workflow.replaceWith(recipeElement); editor?.dispose(); print?.dispose(); tasks?.dispose(); observe?.dispose(); manufacture?.dispose(); laser?.dispose(); buttons.forEach((b) => { b.onclick = null; }); brand.onclick = null; brand.onkeydown = null; },
  };
}
