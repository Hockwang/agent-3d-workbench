// Shared workspace controller: transports supply API and optional geometry loading.
import { Viewport } from "./viewport.js";
import { createTasks } from "./tasks.js";
import { createObserve } from './evaluation.js';
import { icon } from './vendor/ui/icons.js';
import { Panel } from "./panel.js";
import { Flow } from "./flow.js";
import { registerPageTools } from "./tools.js";
import { createEditor } from "./editor.js";
import { Recipes } from "./recipes.js";
import { t } from "./i18n.js";
import { createQuickAccess } from "./quick-access.js";

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
  let disposed = false, active = true, events = null, resizeObserver = null, refreshPromise = null;
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
          if (!currentState || rev !== currentState.rev) refresh();
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

  async function refresh() {
    if (disposed) return;
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
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
      } finally { refreshPromise = null; }
    })();
    return refreshPromise;
  }

  function composedState() {
    if (!currentState) return null;
    if (!localBusy) return currentState;
    return Object.assign({}, currentState, { busy: localBusy });
  }

  async function runAction(op, fn) {
    const cur = composedState();
    if (!cur || cur.busy) return false; // 服务器已在忙，防御性丢弃（按钮理应已置灰）
    localBusy = { op, since: new Date().toISOString(), actor: "human" };
    renderAll();
    try {
      await fn();
      lastError = null;
    } catch (e) {
      lastError = { op, code: (e && e.code) || "error", message: (e && e.message) || String(e) };
    } finally {
      localBusy = null;
      await refresh();
      if (!disposed) renderAll();
    }
    return !lastError;
  }

  function renderAll() {
    if (disposed) return;
    const s = composedState();
    adoptRemoteSelection(s);
    panel.render(s);
    flow.render(s, { selectedName });
    if (pendingSelection) document.getElementById("sel-shared").textContent = t("workspace.selection.syncing");
    if (s) {
      const stamp = JSON.stringify(s.parts?.map((p) => p.stl_url));
      if (stamp !== geometryStamp) { geometryStamp = stamp; firstFit = true; }
      const priorView = currentView;
      maybeAutoSwitchView(s);
      viewport.update(s);
      if (priorView !== currentView) viewport.fitView();
    }
    renderPlateTabs(s);
    updateStatusBar(s);
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
    viewport.bedGroup.visible = mode === "plate";
    document.querySelectorAll(".view-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === mode)));
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
    document.getElementById("busy-card-title").textContent = t("workspace.busyCard.title", { label: OP_LABELS[busy.op] || busy.op });
    document.getElementById("busy-card-time").textContent = t("workspace.busyCard.elapsed", { seconds: elapsed });
  }

  function updateStatusBar(s) {
    const busy = localBusy || (s && s.busy);
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
    setState(next) { currentState = next; options.onState?.(next); renderAll(); },
    setActive(value) { active = value; viewport.setActive(value && !document.hidden); if (value) refresh(); },
    dispose() { disposed = true; stopPolling(); clearInterval(statusTimer); events?.close(); resizeObserver?.disconnect(); disposeCards?.(); viewport.dispose(); },
  };
}

// A recipe step's `tool` may carry a `#action`/`#template`/`#operation` suffix
// (recipes/README.md; `studio.core.recipes._step_call`, e.g. `studio_edit#plane_cut`,
// `studio_task#assembly-audit`). Every router below must compare this base name, not
// the whole string, or a suffixed step silently falls through to the wrong workspace
// (see tests/test_v04_workspace.mjs).
export function recipeStepBaseTool(step) {
  return String(step?.tool || "").split("#")[0];
}

// Each mode owns its controls and camera; they share the same transport and
// backend. A print job is a deliberate copy of editable assets, not their state.
export function createWorkspace(api, options = {}) {
  let editor = null, print = null, mode = options.mock ? "print" : "edit", active = true, nextState = null;
  let tasks = null, observe = null, previewResult = null;
  const workflow = document.createElement('details'); workflow.className = 'workspace-workflow';
  const workflowSummary = document.createElement('summary');
  const recipeElement = document.getElementById('recipe');
  recipeElement.before(workflow); workflow.append(workflowSummary, recipeElement);
  let disposed = false, updateBusy = false, updatesTimer = null;
  const access = createQuickAccess({ api,
    onModel: () => { show('edit'); editor.fitView(); },
    onOpenFile: () => { show('edit'); editor.openFile(); },
    onOpenResult: (id, files) => openResult(id, files),
    onAttachSelection: options.onAttachSelection,
    onOpenHistory: () => { show('tasks'); tasks.openHistory(); },
  });
  async function openResult(id, files = false) {
    show('tasks');
    try { await tasks.openResult(id, files); }
    catch (e) {
      const error = document.getElementById('recipe-error');
      error.textContent = e.message; error.hidden = false;
    }
  }
  async function pollUpdates() {
    if (disposed || !active || document.hidden || updateBusy || !api.tasks) return;
    updateBusy = true;
    try {
      if (mode === 'tasks' || mode === 'observe') { nextState = await api.getState(); renderRecipe(); }
      const result = await api.tasks();
      access.setResults(result.tasks);
    } catch (error) { access.setError(error); }
    finally { updateBusy = false; }
  }
  const child = () => mode === 'observe' ? observe : mode === 'tasks' ? tasks : ['edit','motion'].includes(mode) ? editor : print;
  let recipes = null, recipeBusy = false;
  const renderRecipe = () => {
    access.setState(nextState);
    recipes?.render({ ...nextState, busy: recipeBusy || nextState?.busy });
    if (mode === 'motion' || (mode === 'tasks' && previewResult)) document.getElementById('recipe').hidden = true;
    workflow.hidden = recipeElement.hidden;
    workflowSummary.textContent = t('entry.projectWorkflow', { name: nextState?.recipe?.title || nextState?.recipe?.name || t('entry.chooseWorkflow') });
  };
  const publishSelection = () => { if (nextState) options.onSelectionContext?.({ mode, state: nextState }); };
  const childOptions = { ...options, onState(next) { nextState = next; renderRecipe(); options.onState?.(next); publishSelection(); } };
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
        studio_check: "check", studio_send_to_bambu: "send" };
      const method = methods[step.tool];
      if (!method || recipeStepBaseTool(step) === "studio_edit") return openRecipeStep(step.row, step);
      return runRecipe(() => api[method](step.args || {}));
    }, onRunOneShot: (recipe) => runRecipe(() => api.prepare(recipe.one_shot.args || {})),
  });
  const buttons = [...document.querySelectorAll("[data-workspace-mode]")];
  document.querySelector('.wb-symbol').innerHTML = icon('box');
  const navIcons = {edit:'layers', motion:'clapperboard', tasks:'wand-sparkles', observe:'scan-eye', print:'printer'};
  buttons.forEach(b => { if (!b.querySelector('svg')) b.insertAdjacentHTML('afterbegin', icon(navIcons[b.dataset.workspaceMode])); });
  function show(value) {
    mode = ['edit', 'motion', 'print', 'tasks', 'observe'].includes(value) ? value : 'edit';
    workflow.open = !['edit', 'motion'].includes(mode);
    document.getElementById("editor-space").hidden = !["edit","motion"].includes(mode);
    document.getElementById("print-space").hidden = mode !== "print";
    document.getElementById('task-space').hidden = mode !== 'tasks';
    document.getElementById('observe-space').hidden = mode !== 'observe';
    renderRecipe();
    access.setMode(mode);
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.workspaceMode === mode)));
    if (["edit","motion"].includes(mode) && !editor) editor = createEditor(api, { ...childOptions, onPrint: () => show("print"), onMotion: () => show("motion"), onResults: () => access.openResults() });
    if (mode === "print" && !print) print = createPrintWorkspace(api, childOptions);
    if (mode === 'tasks' && !tasks) tasks = createTasks(api, { onImport: () => { show('edit'); editor.refresh?.(); }, onPreview: result => { previewResult = result; access.setPreview(result); renderRecipe(); } });
    if (mode === 'observe' && !observe) observe = createObserve(api);
    editor?.setWorkspaceMode(mode);
    editor?.setActive(active && ["edit","motion"].includes(mode));
    print?.setActive(active && mode === "print");
    tasks?.setActive(active && mode === 'tasks');
    observe?.setActive(active && mode === 'observe');
    if (nextState) child()?.setState(nextState);
    publishSelection();
  }
  buttons.forEach((b) => { b.onclick = () => show(b.dataset.workspaceMode); });
  show(mode);
  updatesTimer = setInterval(pollUpdates, 2000); pollUpdates();
  const ready = child().ready.then(async () => {
    if (api.getRecipes) { await recipes.start(); renderRecipe(); }
  });
  return {
    ready,
    openResult,
    setMode: show,
    setState(state) { nextState = state; renderRecipe(); if (state.workspace_mode) show(state.workspace_mode); editor?.setState(state); print?.setState(state); observe?.setState(state); tasks?.setState(state); publishSelection(); },
    setActive(value) { if (active === value) return; active = value; editor?.setActive(value && ["edit","motion"].includes(mode)); print?.setActive(value && mode === "print"); tasks?.setActive(value && mode === 'tasks'); observe?.setActive(value && mode === 'observe'); },
    dispose() { disposed = true; clearInterval(updatesTimer); access.dispose(); recipes?.dispose(); workflow.replaceWith(recipeElement); editor?.dispose(); print?.dispose(); tasks?.dispose(); observe?.dispose(); buttons.forEach((b) => { b.onclick = null; }); },
  };
}
