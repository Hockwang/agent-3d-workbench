import { createScenePanel } from './scene-panel.js';
import { createCityPanel } from './city-panel.js';
import { createMotionPanel } from './motion-panel.js';
import { createStudioShell } from "./studio-shell.js";
import { EditorViewport } from "./editor-viewport.js";
import { icon } from './vendor/ui/icons.js';
import { createPartChatUI } from './part-chat.js';
import { t } from './i18n.js';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (x) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[x]));
const vector = (id, value = 0) => `<div class="ed-vector">${["X", "Y", "Z"].map((axis) => `<label><span class="axis-${axis.toLowerCase()}">${axis}</span><input aria-label="${({"ed-translate":t('editor.tool.translate'),"ed-rotate":t('editor.tool.rotate'),"ed-scale":t('editor.tool.scale')})[id]} ${axis}" id="${id}-${axis}" type="number" step="any" value="${value}"></label>`).join("")}</div>`;
const actionIcons = {undo:'undo-2', redo:'redo-2', save:'save'};
const button = (action, text, extra = "") => `<button type="button" data-edit="${action}" aria-label="${text}" title="${text}" ${extra}>${icon(actionIcons[action])}<span>${text}</span></button>`;

export function createEditor(api, options = {}) {
  let state = null, busy = false, active = true, disposed = false, timer = null, refreshPromise = null, module = "edit", selectionStamp = "";
  let firstState = true, printSources = [], renderStamp = "";
  let region = null, nameDirty = false;
  $("editor-space").innerHTML = `
    <div class="ed-toolbar"><div><strong id="ed-name">${t('editor.toolbar.title')}</strong><span id="ed-stats">${t('editor.toolbar.stats')}</span><small id="ed-folder" hidden></small></div>
      <div class="ed-actions">${button("undo", t('editor.toolbar.undo'))}${button("redo", t('editor.toolbar.redo'))}${button("save", t('editor.toolbar.save'))}</div></div>
    <div class="ed-main">
      <section class="ed-stage" aria-label="${t('editor.stage.ariaLabel')}"><div id="editor-viewport"></div>
        <div class="ed-view-tools">${[ ["select", t('editor.tool.select'), "mouse-pointer-2"], ["translate", t('editor.tool.translate'), "move"], ["rotate", t('editor.tool.rotate'), "rotate-3d"], ["scale", t('editor.tool.scale'), "scaling"] ].map(([m,label,i]) => `<button data-gizmo="${m}" aria-label="${label}" title="${label}" aria-pressed="${m === "select"}">${icon(i)}<span>${label}</span></button>`).join("")}<button id="ed-fit" aria-label="${t('editor.tool.fitView')}" title="${t('editor.tool.fitView')}">${icon('maximize')}</button></div>
        <div id="ed-empty"><span class="ed-cube">${icon('box')}</span><h2>${t('editor.empty.title')}</h2><p>${t('editor.empty.body')}</p><div class="ed-start-actions"><button type="button" id="ed-open-file" class="ed-primary">${t('entry.openFile')}</button><button type="button" id="ed-recent-results">${t('entry.recent')}</button></div><div>${button("box", t('editor.empty.newCube'))}${button("sphere", t('editor.empty.newSphere'))}</div><p class="ed-muted">${t('editor.empty.footnote')}</p></div>
        <div class="ed-view-meta"><span id="ed-selection-info">${t('editor.stage.selectHint')}</span><span>mm · Z ↑</span></div>
        <div id="ed-working" hidden>${t('editor.status.working')}</div>
      </section>
      <div class="ed-panels">
      <details class="ed-browser studio-card" open><summary>${icon('layers')}<span>${t('editor.browser.title')}</span><span id="ed-object-count" class="studio-count"></span></summary><div class="studio-card-body">
        <details class="ed-section" id="ed-import" open><summary>${t('editor.import.title')}</summary>
          <label id="ed-upload-wrap">${t('editor.import.chooseFile')}<input id="ed-upload" type="file" multiple accept=".glb,.gltf,.stl,.obj,.ply,.3mf"></label>
          <details class="ui-paths"><summary>${t('editor.import.byPath')}</summary><label>${t('editor.import.pathsLabel')}<textarea id="ed-paths" rows="2" placeholder="${t('editor.import.pathPlaceholder')}"></textarea></label>
          <div class="ed-row"><select id="ed-units" aria-label="${t('editor.import.unitsAriaLabel')}"><option value="auto">${t('editor.import.unit.auto')}</option><option value="mm">${t('editor.import.unit.mm')}</option><option value="cm">${t('editor.import.unit.cm')}</option><option value="m">${t('editor.import.unit.m')}</option></select>${button("import", t('editor.import.submit'), 'class="ed-primary"')}</div></details>
          <p class="ed-muted">${t('editor.import.unitsNote')}</p>
          <div class="ed-row">${button("box", t('editor.import.addCube'))}${button("sphere", t('editor.import.addSphere'))}</div>
          ${button("from_print", t('editor.import.fromPrint'), 'class="ed-wide"')}
          <details class="ui-paths"><summary>${t('editor.import.openProject')}</summary><label>${t('editor.import.projectPathLabel')}<input id="ed-project-path" placeholder="${t('editor.import.projectPathPlaceholder')}"></label>${button("open", t('editor.import.openButton'))}</details>
        </details>
        <section class="ed-section"><div class="ed-section-head"><h2>${t('editor.scene.title')}</h2>${button("show_all", t('editor.scene.showAll'))}</div>
          <div id="ed-tree" class="ed-tree"></div><div class="ed-row">${button("all", t('editor.scene.selectAll'))}${button("isolate", t('editor.scene.isolate'))}${button("duplicate", t('editor.scene.duplicate'))}${button("delete", t('common.delete'))}</div>
        </section>
      </div></details>
      <details class="ed-inspector studio-card" open><summary>${icon('sliders-horizontal')}<span>${t('editor.props.title')}</span></summary><div class="studio-card-body">
        <div id="ed-error" role="alert" hidden></div>
        <nav class="ed-tabs" aria-label="${t('editor.props.tabsAriaLabel')}">${[["edit",t('editor.props.tab.edit')],["cut",t('editor.props.tab.cut')],["repair",t('editor.props.tab.repair')],["material",t('editor.props.tab.material')]].map(([id,label]) => `<button data-module="${id}" aria-pressed="${id === "edit"}">${label}</button>`).join("")}</nav>
        <section class="ed-section" data-ed-panel="edit">
          <label>${t('editor.props.nameLabel')}<div class="ed-row"><input id="ed-object-name" placeholder="${t('editor.props.namePlaceholder')}">${button("rename", t('editor.props.renameButton'))}</div></label>
          <p id="ed-dimensions" class="ed-muted">${t('editor.props.dimensionsHint')}</p>
          <label>${t('editor.props.translateLabel')}</label>${vector("ed-translate")}
          <label>${t('editor.props.rotateLabel')}</label>${vector("ed-rotate")}
          <label>${t('editor.props.scaleLabel')}</label>${vector("ed-scale", 1)}
          ${button("transform", t('editor.props.applyTransform'), 'class="ed-primary ed-wide"')}
        </section>
        <section class="ed-section" data-ed-panel="cut" hidden>
          <h2>${t('editor.cut.title')}</h2><label class="ed-inline"><input id="ed-region-pick" type="checkbox">${t('editor.cut.regionPickLabel')}</label>
          <label>${t('editor.cut.regionRadiusLabel')}<input id="ed-region-radius" type="number" min="0.1" step="0.5" value="5"></label>
          <p id="ed-region-status" class="ed-muted">${t('editor.cut.regionHint')}</p>
          ${button("extract_faces", t('editor.cut.extractButton'), 'class="ed-wide"')}
          <h2>${t('editor.cut.planeTitle')}</h2><p class="ed-muted">${t('editor.cut.planeHint')}</p>
          <div class="ed-row"><label>${t('editor.cut.normalLabel')}<select id="ed-cut-axis"><option value="2">Z</option><option value="0">X</option><option value="1">Y</option></select></label><label>${t('editor.cut.offsetLabel')}<input id="ed-cut-offset" type="number" step="any" value="0"></label></div>
          ${button("plane_cut", t('editor.cut.planeCutButton'), 'class="ed-primary ed-wide"')}
          <div class="ed-row">${button("split_components", t('editor.cut.splitComponents'))}${button("merge", t('editor.cut.mergeButton'))}</div>
          <h2>${t('editor.cut.booleanTitle')}</h2><div class="ed-row"><select id="ed-boolean" aria-label="${t('editor.cut.booleanAriaLabel')}"><option value="union">${t('editor.cut.boolean.union')}</option><option value="difference">${t('editor.cut.boolean.difference')}</option><option value="intersection">${t('editor.cut.boolean.intersection')}</option></select>${button("boolean", t('editor.cut.booleanButton'))}</div>
          <p class="ed-muted">${t('editor.cut.differenceHint')}</p>
        </section>
        <section class="ed-section" data-ed-panel="repair" hidden>
          <div class="ed-row">${button("inspect", t('editor.repair.inspectButton'))}${button("repair", t('editor.repair.repairButton'))}</div>
          <p class="ed-muted">${t('editor.repair.hint')}</p>
          <label>${t('editor.repair.ratioLabel')}<input id="ed-ratio" type="number" min="0.01" max="0.99" step="0.05" value="0.5"></label>${button("simplify", t('editor.repair.simplifyButton'))}
          <div id="ed-reports"></div>
        </section>
        <section class="ed-section" data-ed-panel="material" hidden>
          <label>${t('editor.material.targetLabel')}<select id="ed-material-target" aria-label="${t('editor.material.targetAriaLabel')}"></select></label>
          <label>${t('editor.material.colorLabel')}<input id="ed-color" type="color" value="#bec7d5"></label>
          <label>${t('editor.material.roughnessLabel')}<input id="ed-roughness" type="range" min="0" max="1" step="0.01" value="0.6"></label>
          <label>${t('editor.material.metallicLabel')}<input id="ed-metallic" type="range" min="0" max="1" step="0.01" value="0"></label>
          <p id="ed-material-info" class="ed-muted">${t('editor.material.initialInfo')}</p>
          <label>${t('editor.material.replaceTextureLabel')}<input id="ed-texture-upload" type="file" accept=".png,.jpg,.jpeg,.webp"></label>
          <div class="ed-row">${button("clear_texture", t('editor.material.clearTextureButton'))}<span id="ed-texture-status" class="ed-muted"></span></div>
          ${button("material", t('editor.material.applyButton'), 'class="ed-primary"')}
        </section>
        <label class="ed-consent" id="ed-geometry-consent" hidden><input type="checkbox" id="ed-plain">${t('editor.consent.allowPlain')}</label>
        <details class="ed-section" id="ed-delivery"><summary>${t('editor.delivery.title')}</summary>
          <label>${t('editor.delivery.outputPathLabel')}<input id="ed-output" placeholder="${t('editor.delivery.outputPathPlaceholder')}"></label>
          <label class="ed-inline"><input id="ed-export-selected" type="checkbox">${t('editor.delivery.exportSelectedLabel')}</label>
          <div class="ed-row">${button("export_glb", t('editor.delivery.exportGlb'))}${button("export_stl", t('editor.delivery.exportStl'))}</div>
          ${button("print_copy", t('editor.delivery.printCopyButton'), 'class="ed-wide"')}
          <div id="ed-result" role="status"></div>
        </details>
        <details class="ed-section" id="ed-records"><summary>${t('editor.records.title')} <span id="ed-history-count"></span></summary><ol id="ed-history"></ol></details>
      </div></details>
      </div>
    </div>`;
  const shell = createStudioShell($("editor-space"), { layout: '.ed-main', stage: '.ed-stage', library: '.ed-browser', settings: '.ed-inspector', title: t('editor.shell.title'), sections: ['.ed-toolbar', '#ed-delivery', '#ed-records'], footer: ['[data-edit="print_copy"]'] });
  const viewport = new EditorViewport($("editor-viewport"), {
    loadAsset: (obj) => api.editorAsset(obj),
    onSelect: (id, multiple) => {
      if (!state || busy) return;
      let ids = id ? [id] : [];
      if (multiple && id) ids = state.selection.includes(id) ? state.selection.filter((x) => x !== id) : [...state.selection, id];
      run("select", { ids });
    },
    onTransform: (id, matrix, revision, versions) => run("transform", { ids: [id], matrix }, revision, versions),
    onContext: openPartMenu,
    onRegion: async (id, point) => {
      if (!state || busy) return;
      if (!await run('select', { ids: [id] })) return;
      const obj = state.objects.find((x) => x.id === id);
      region = { id, point, asset: obj.asset, transform: JSON.stringify(obj.transform) };
      viewport.setRegion(point, Number($('ed-region-radius').value));
      $('ed-region-status').textContent = t('editor.cut.regionCenter', { point: point.map((x) => x.toFixed(2)).join(', ') });
    },
    onError: showError,
  });
  viewport.setMode("select");
  const motionPanel = createMotionPanel({ api, viewport, host: document.querySelector('.ed-inspector > .studio-card-body'), stage: document.querySelector('.ed-stage'), getState: () => state, run, onError: showError });
  const scenePanel = createScenePanel({api, viewport, browser: document.querySelector('.ed-browser > .studio-card-body'), inspector: document.querySelector('.ed-inspector > .studio-card-body'), getState: () => state, run, onMotion: options.onMotion, onError: showError});
  const cityPanel = createCityPanel({api,viewport,browser:document.querySelector('.ed-browser > .studio-card-body'),stage:document.querySelector('.ed-stage'),getState:()=>state,run,onError:showError});
  const partMenu = document.createElement('div'); partMenu.className = 'ed-part-menu'; partMenu.hidden = true;
  const partChat = createPartChatUI(api);
  partMenu.setAttribute('role', 'menu'); document.body.append(partMenu);
  function closePartMenu(event) { if (!event || !partMenu.contains(event.target)) partMenu.hidden = true; }
  function openPartMenu(id, event) {
    const object = state?.objects.find(o => o.id === id); if (!object) return;
    event.preventDefault(); partMenu.replaceChildren();
    const title = document.createElement('strong'); title.textContent = object.name; partMenu.append(title);
    const create = document.createElement('button'); create.type = 'button'; create.setAttribute('role', 'menuitem');
    create.textContent = t('editor.partMenu.createChat');
    create.disabled = busy || (object.lease && object.lease.session !== state.collaboration?.session_id) ||
      (state.collaboration?.scope && !state.collaboration.scope.includes(id));
    create.onclick = async () => {
      partMenu.hidden = true;
      await partChat.create(object, state.revision);
    };
    partMenu.append(create);
    const disallowed = create.disabled; create.disabled = true; create.textContent = t('editor.partMenu.checkingChat');
    partChat.status().then(policy => {
      const existing = policy.operations?.some(o => o.object_id === id);
      create.textContent = existing ? t('editor.partMenu.viewChat') : t('editor.partMenu.createChat');
      create.disabled = (!existing && disallowed) || !policy.available || policy.decision === 'denied';
      create.title = policy.decision === 'denied' ? t('editor.partMenu.deniedTitle') : policy.message || '';
    }).catch(error => { create.textContent = t('editor.partMenu.unavailable'); create.title = error.message; });
    const settings = document.createElement('button'); settings.type = 'button'; settings.textContent = t('editor.partMenu.settingsButton');
    settings.setAttribute('role', 'menuitem'); settings.onclick = () => { partMenu.hidden = true; partChat.settings(object, state.revision); };
    partMenu.append(settings);
    if (object.lease?.session === state.collaboration?.session_id && api.collaboration) {
      const release = document.createElement('button'); release.type = 'button'; release.textContent = t('editor.partMenu.releaseButton'); release.setAttribute('role', 'menuitem');
      release.onclick = async () => { partMenu.hidden = true; try { await api.collaboration({ action: 'release', ids: [id] }); await refresh(); } catch (error) { showError(error); } };
      partMenu.append(release);
    }
    partMenu.hidden = false;
    partMenu.style.left = Math.max(8, Math.min(event.clientX, innerWidth - partMenu.offsetWidth - 8)) + 'px';
    partMenu.style.top = Math.max(8, Math.min(event.clientY, innerHeight - partMenu.offsetHeight - 8)) + 'px';
    create.focus();
  }
  $('ed-tree').oncontextmenu = event => {
    const row = event.target.closest('.ed-object'); const id = row?.querySelector('[data-select]')?.dataset.select;
    if (id) openPartMenu(id, event);
  };
  document.addEventListener('pointerdown', closePartMenu);
  function showError(error) {
    shell.reveal($("ed-error")); $("ed-error").hidden = false; $("ed-error").textContent = error.message || String(error);
    const retry = document.createElement('button'); retry.textContent = t('editor.error.retryButton'); retry.type = 'button';
    retry.onclick = () => { $("ed-error").hidden = true; viewport.retryFailed(); refresh(); };
    $("ed-error").append(retry);
  }
  function getVector(id) { return ["X", "Y", "Z"].map((axis) => Number($(id + "-" + axis).value)); }
  function selection() { return state?.objects.filter((o) => state.selection.includes(o.id)) || []; }
  let materialStamp = '', materialChanges = {};
  function materialValues() {
    materialChanges = {}; $('ed-texture-status').textContent = '';
    const value = $('ed-material-target').value;
    const [id, index] = value.split(':');
    const mat = state.objects.find(o => o.id === id)?.materials?.find(m => m.slot === Number(index));
    if (mat) {
      $('ed-color').value = mat.color; $('ed-roughness').value = mat.roughness; $('ed-metallic').value = mat.metallic;
      $('ed-material-info').textContent = t('editor.material.selectedInfo', { name: mat.name, state: t(mat.base_color_texture ? 'editor.material.textureState.embedded' : 'editor.material.textureState.plain') });
    } else $('ed-material-info').textContent = t('editor.material.allMaterialsInfo');
  }
  function materialOptions(selected) {
    const signature = JSON.stringify(selected.map(o => [o.id, o.name, o.asset]));
    if (materialStamp === signature) return;
    materialStamp = signature;
    const previous = $('ed-material-target').value;
    const select = $('ed-material-target'); select.replaceChildren(new Option(t('editor.material.allOption'), 'all'));
    for (const obj of selected) for (const mat of obj.materials || []) {
      if (mat.editable) select.append(new Option(`${obj.name} / ${mat.name} · ${mat.slot + 1}`, `${obj.id}:${mat.slot}`));
    }
    select.value = [...select.options].some(o => o.value === previous) ? previous : select.options.length === 2 ? select.options[1].value : 'all';
    materialValues();
  }
  function cutPlane() {
    const obj = selection()[0];
    if (!obj || selection().length !== 1) return null;
    const axis = Number($("ed-cut-axis").value), normal = [0, 0, 0]; normal[axis] = 1;
    const point = obj.bounds_mm[0].map((v, i) => (v + obj.bounds_mm[1][i]) / 2);
    point[axis] += Number($("ed-cut-offset").value);
    return { point_mm: point, normal, size: Math.max(...obj.extents_mm, 1) * 1.6 };
  }
  function previewPlane() {
    const plane = module === "cut" && !$('ed-region-pick').checked ? cutPlane() : null;
    viewport.setPlane(plane?.point_mm, plane?.normal, plane?.size);
  }
  function setState(next) {
    if (!next?.workbench || disposed) return;
    options.onState?.(next);
    state = next.workbench;
    shell.setWelcome(state.objects.length === 0);
    shell.setPopulated(state.objects.length > 0);
    if (region && !state.objects.some((o) => o.id === region.id && o.asset === region.asset && JSON.stringify(o.transform) === region.transform)) {
      region = null; viewport.setRegion(null); $('ed-region-status').textContent = t('editor.cut.regionChanged');
    }
    printSources = next.print_sources || [];
    if (firstState) { $("ed-import").open = state.objects.length === 0; firstState = false; }
    busy = Boolean(next.busy) || working;
    render();
  }
  function render() {
    if (!state) return;
    const nextStamp = JSON.stringify([state.revision, state.view_revision, state.selection, state.objects.map(o => o.lease), busy, printSources]);
    if (renderStamp === nextStamp) return;
    renderStamp = nextStamp;
    $("ed-name").textContent = state.name;
    $('ed-folder').hidden = !state.project_folder;
    $('ed-folder').textContent = state.project_folder ? t('editor.status.projectFolder', { folder: state.project_folder }) : '';
    $('ed-folder').title = state.project_folder || '';
    { const count = state.objects.length, faces = state.objects.reduce((n, o) => n + o.faces, 0).toLocaleString();
      $("ed-stats").textContent = !state.collaboration ? t('editor.status.stats', { count, faces })
        : state.collaboration.scope ? t('editor.status.statsCollabScope', { count, faces, members: state.collaboration.members })
        : t('editor.status.statsCollab', { count, faces, members: state.collaboration.members }); }
    $("ed-object-count").textContent = state.objects.length;
    $("ed-empty").hidden = state.objects.length > 0;
    $("ed-import").open = state.objects.length === 0 ? true : $("ed-import").open;
    $("ed-working").hidden = !busy;
    const signature = JSON.stringify([state.objects.map((o) => [o.id, o.name, o.visible]), state.selection]);
    if ($("ed-tree").dataset.signature !== signature) {
      $("ed-tree").dataset.signature = signature;
      $("ed-tree").innerHTML = state.objects.map((o) => `<div class="ed-object ${state.selection.includes(o.id) ? "selected" : ""}"><label><input type="checkbox" data-select="${o.id}" ${state.selection.includes(o.id) ? "checked" : ""}><span title="${esc(o.name)}">${esc(o.name)}</span></label><button data-visible="${o.id}" aria-label="${esc(t(o.visible ? 'editor.scene.hideAriaLabel' : 'editor.scene.showAriaLabel', { name: o.name }))}">${o.visible ? "◉" : "○"}</button></div>`).join("") || `<p class="ed-muted">${t('editor.scene.empty')}</p>`;
    }
    const selected = selection();
    materialOptions(selected);
    const stamp = state.selection.join();
    if (stamp !== selectionStamp) nameDirty = false;
    if (!nameDirty) $("ed-object-name").value = selected.length === 1 ? selected[0].name : "";
    selectionStamp = stamp;
    $("ed-selection-info").textContent = selected.length ? t('editor.stage.selectedCount', { count: selected.length }) : t('editor.stage.selectHint');
    $("ed-dimensions").textContent = selected.some(o=>o.city) ? t('editor.props.cityDimensionsHint') : selected.length === 1 ? t('editor.props.dimensions', { extents: selected[0].extents_mm.map((v) => v.toFixed(2)).join(" × ") }) : selected.length ? t('editor.props.multiSelectDimensions', { count: selected.length }) : t('editor.props.dimensionsHint');
    for (const btn of $("editor-space").querySelectorAll("[data-edit]")) {
      const action = btn.dataset.edit;
      const global = ["box","sphere","import","from_print","open","save","all","show_all","undo","redo","export_glb","export_stl","print_copy"].includes(action);
      btn.disabled = busy || (!global && !selected.length) || (action === "undo" && !state.can_undo) || (action === "redo" && !state.can_redo) || (action === "from_print" && !printSources.length);
    }
    $("ed-history-count").textContent = state.history.length;
    $("ed-history").innerHTML = [...state.history].reverse().map((h) => `<li><span>${h.actor === "human" ? t('editor.history.human') : "AI"}</span>${esc(h.summary)}</li>`).join("");
    viewport.update(state); motionPanel.update(state); scenePanel.update(state); cityPanel.update(state); previewPlane();
  }
  let working = false;
  async function refresh() {
    if (disposed) return;
    if (refreshPromise) return refreshPromise;
    refreshPromise = api.getState().then(setState).catch(showError).finally(() => { refreshPromise = null; });
    return refreshPromise;
  }
  async function run(action, params = {}, revision, versions) {
    if (!state || working || busy) return null;
    working = true; busy = true; $("ed-error").hidden = true; render();
    try {
      const result = await api.edit({ action, params, expected_revision: revision ?? state.revision,
        ...(state.collaboration ? { expected_versions: versions || Object.fromEntries(state.objects.map(o => [o.id, o.version])) } : {}) });
      if (action !== "select") {
        $("ed-result").replaceChildren();
        const text = document.createElement("p"); text.textContent = result.summary || t('editor.status.done'); $("ed-result").append(text);
        if (result.path) { const input = document.createElement("input"); input.readOnly = true; input.value = result.path; input.setAttribute("aria-label", t('editor.delivery.outputPathAriaLabel')); input.onclick = () => input.select(); $("ed-result").append(input); }
        if (result.warning) { const note = document.createElement("p"); note.textContent = result.warning; $("ed-result").append(note); }
      }
      if (result.reports) $("ed-reports").innerHTML = result.reports.map((r) => `<div class="ed-report"><strong>${esc(r.name)}</strong><p>${t('editor.repair.componentsLine', { state: t(r.watertight ? 'editor.repair.watertight' : 'editor.repair.open'), components: r.components })}</p><p>${t('editor.repair.edgesLine', { boundary: r.boundary_edges, nonmanifold: r.nonmanifold_edges })}</p></div>`).join("");
      if (["import", "primitive", "open"].includes(action)) $("ed-import").open = false;
      if (action === "print_copy") { await api.load({ files: result.files }); options.onPrint?.(); }
      return result;
    } catch (error) { showError(error); return null; }
    finally { working = false; busy = false; await refresh(); }
  }
  async function dispatch(action) {
    const geometry = { allow_material_loss: $("ed-plain").checked };
    if (action === "box" || action === "sphere") return run("primitive", { kind: action, size: [20, 20, 20] });
    if (action === "import") return run("import", { files: $("ed-paths").value.split(/\n/).map((p) => p.trim()).filter(Boolean), units: $("ed-units").value });
    if (action === "from_print") return run("import", { files: printSources, units: "mm" });
    if (action === "open") return run("open", { path: $("ed-project-path").value.trim() });
    if (action === "save") return run("save", $("ed-project-path").value.trim() ? { path: $("ed-project-path").value.trim() } : {});
    if (action === "all") return run("select", { ids: state.objects.map((o) => o.id) });
    if (action === "rename") { const result = await run(action, { name: $("ed-object-name").value }); if (result) nameDirty = false; return result; }
    if (action === "transform") {
      const result = await run(action, { translate_mm: getVector("ed-translate"), rotate_deg: getVector("ed-rotate"), scale: getVector("ed-scale") });
      if (result) for (const prefix of ["ed-translate", "ed-rotate", "ed-scale"]) for (const axis of ["X","Y","Z"]) $(prefix + "-" + axis).value = prefix === "ed-scale" ? 1 : 0;
      return;
    }
    if (action === "plane_cut") { const plane = cutPlane(); if (!plane) return showError(new Error(t('editor.error.selectObjectFirst'))); return run(action, { ...geometry, normal: plane.normal, point_mm: plane.point_mm }); }
    if (action === 'extract_faces') {
      if (!region) return showError(new Error(t('editor.error.pickRegionFirst')));
      return run(action, { ids: [region.id], point_mm: region.point, radius_mm: Number($('ed-region-radius').value) });
    }
    if (action === "boolean") return run(action, { ...geometry, operation: $("ed-boolean").value });
    if (["split_components","merge","repair","simplify"].includes(action)) return run(action, { ...geometry, ...(action === "simplify" ? { ratio: Number($("ed-ratio").value) } : {}) });
    if (action === 'clear_texture') { materialChanges.base_color_texture = null; $('ed-texture-status').textContent = t('editor.material.textureRemovePending'); return; }
    if (action === "material") {
      if (!Object.keys(materialChanges).length) return showError(new Error(t('editor.error.adjustMaterialFirst')));
      const target = $('ed-material-target').value;
      const [id, index] = target.split(':');
      return run(action, { ...materialChanges, ...(target === 'all' ? {} : { ids: [id], material_slots: [Number(index)] }) });
    }
    if (action.startsWith("export_")) {
      if ($("ed-export-selected").checked && !state.selection.length) return showError(new Error(t('editor.error.selectExportObjectsFirst')));
      return run("export", { format: action.slice(7), ...($("ed-output").value.trim() ? { path: $("ed-output").value.trim() } : {}), ...($("ed-export-selected").checked ? { ids: state.selection } : {}) });
    }
    return run(action);
  }
  const onClick = (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (button.dataset.edit) dispatch(button.dataset.edit).catch(showError);
    if (button.dataset.visible) { const obj = state.objects.find((o) => o.id === button.dataset.visible); run("visibility", { ids: [obj.id], visible: !obj.visible }); }
    if (button.dataset.gizmo) {
      $("editor-space").querySelectorAll("[data-gizmo]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      viewport.setMode(button.dataset.gizmo);
    }
    if (button.dataset.module) {
      module = button.dataset.module;
      viewport.regionPicking = module === 'cut' && $('ed-region-pick').checked;
      if (module !== 'cut') viewport.setRegion(null);
      $("editor-space").querySelectorAll("[data-module]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      $("editor-space").querySelectorAll("[data-ed-panel]").forEach((p) => { p.hidden = p.dataset.edPanel !== module; });
      $("ed-geometry-consent").hidden = !["cut", "repair"].includes(module); previewPlane();
    }
  };
  $("editor-space").addEventListener("click", onClick);
  $("ed-tree").onchange = (event) => {
    const id = event.target.dataset.select; if (!id || busy) return;
    run("select", { ids: event.target.checked ? [...state.selection, id] : state.selection.filter((x) => x !== id) });
  };
  $("ed-fit").onclick = () => viewport.fit();
  $('ed-object-name').oninput = () => { nameDirty = true; };
  $('ed-material-target').onchange = materialValues;
  for (const [id, key] of [['ed-color','color'], ['ed-roughness','roughness'], ['ed-metallic','metallic']]) {
    $(id).oninput = () => { materialChanges[key] = key === 'color' ? $(id).value : Number($(id).value); };
  }
  $('ed-texture-upload').disabled = !api.upload;
  $('ed-texture-upload').onchange = async (event) => {
    const file = event.target.files[0]; if (!file) return;
    const target = $('ed-material-target').value, stamp = materialStamp;
    try {
      const result = await api.upload(file);
      if (stamp !== materialStamp || target !== $('ed-material-target').value) throw new Error(t('editor.error.materialSelectionChanged'));
      materialChanges.base_color_texture = result.path;
      $('ed-texture-status').textContent = t('editor.material.texturePending', { name: file.name });
    } catch (error) { showError(error); }
    finally { event.target.value = ''; }
  };
  $("ed-cut-axis").onchange = previewPlane; $("ed-cut-offset").oninput = previewPlane;
  $('ed-region-pick').onchange = () => { viewport.regionPicking = $('ed-region-pick').checked; viewport.setMode('select'); previewPlane(); };
  $('ed-region-radius').oninput = () => { const radius = Number($('ed-region-radius').value); if (region && radius > 0) viewport.setRegion(region.point, radius); };
  $("ed-upload-wrap").hidden = !api.upload;
  function openFile() {
    shell.reveal($("ed-import"));
    $("ed-import").scrollIntoView({ block: 'nearest' });
    if (api.upload) $("ed-upload").click();
    else { $("ed-paths").closest('details').open = true; $("ed-paths").focus(); }
  }
  $("ed-open-file").onclick = openFile;
  $("ed-recent-results").onclick = () => options.onResults?.();
  $("ed-upload").onchange = async (event) => {
    try {
      if (!event.target.files.length) return;
      const paths = [];
      for (const file of event.target.files) { const result = await api.upload(file); paths.push(result.path); }
      $("ed-paths").value = paths.join("\n");
      await dispatch("import");
    } catch (error) { showError(error); }
    finally { event.target.value = ''; }
  };
  const keydown = (e) => {
    if (e.key === 'Escape') partMenu.hidden = true;
    if (!active || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); dispatch(e.shiftKey ? "redo" : "undo"); }
  };
  document.addEventListener("keydown", keydown);
  const ready = (async () => { await api.init(); await refresh(); })();
  let lastRefresh = 0, lastRenew = 0;
  timer = setInterval(() => {
    if (!active || document.hidden || working || viewport.dragging) return;
    const now = Date.now();
    if (now - lastRefresh >= (state?.collaboration ? 1000 : 3000)) { lastRefresh = now; refresh(); }
    if (state?.collaboration && api.collaboration && now - lastRenew > 60000) {
      lastRenew = now;
      const ids = state.objects.filter(o => o.lease?.session === state.collaboration.session_id).map(o => o.id);
      if (ids.length) api.collaboration({ action: 'renew', ids }).catch(showError);
    }
  }, 1000);
  return { ready, setState, refresh, openFile, fitView: () => viewport.fit(),
    setWorkspaceMode(mode) { if(mode==='motion')cityPanel.detailMode(); $("editor-space").classList.toggle("motion-workspace",mode === "motion"); motionPanel.setActive(mode === "motion"); },
    openAction(action) {
      const tab = { inspect: "repair", repair: "repair", simplify: "repair", plane_cut: "cut", split_components: "cut", material: "material" }[action];
      if (tab) $("editor-space").querySelector(`[data-module="${tab}"]`)?.click();
      const control = action === "export" ? "export_glb" : action;
      const target = $("editor-space").querySelector(`[data-edit="${control}"]`);
      if (target) {
        shell.reveal(target);
        for (let ancestor = target.parentElement; ancestor; ancestor = ancestor.parentElement) {
          if (ancestor.tagName === 'DETAILS') ancestor.open = true;
        }
        target.scrollIntoView({ block: "nearest" }); target.focus();
      }
    },
    setActive(value) { active = value; viewport.setActive(value); if (value) refresh(); },
    dispose() { disposed = true; clearInterval(timer); shell.dispose(); cityPanel.dispose(); scenePanel.dispose(); motionPanel.dispose(); viewport.dispose(); partMenu.remove(); document.removeEventListener('pointerdown', closePartMenu); document.removeEventListener("keydown", keydown); $("editor-space").removeEventListener("click", onClick); },
  };
}
