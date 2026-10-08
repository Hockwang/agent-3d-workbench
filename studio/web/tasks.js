import { createStudioShell } from "./studio-shell.js";
import { TaskPreview } from './task-preview.js';
import { uploadFile } from './upload.js';
import { createServiceSettings } from './service-settings.js';
import { t } from './i18n.js';
import { primaryArtifact, orderedArtifacts } from './quick-access.js';
import { resultIdentity, resultGroups, resultTimeLabel } from './result-model.js';
import { createModelBrowser } from './model-browser.js';
import { sandboxedHtml } from './sandboxed-html.js';

const STATUS = () => ({ queued: t('tasks.status.queued'), running: t('tasks.status.running'), cancelling: t('tasks.status.cancelling'), completed: t('tasks.status.completed'), failed: t('tasks.status.failed'), cancelled: t('tasks.status.cancelled'), interrupted: t('tasks.status.interrupted') });
const live = (task) => ['queued', 'running', 'cancelling'].includes(task.status);
const node = (tag, text, className) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (className) e.className = className; return e; };
export function createTasks(api, options = {}) {
  const root = options.root || document.getElementById('task-space');
  const reviewOnly = options.reviewOnly === true;
  const isReview = task => ['merge-review', 'a8-review'].includes(task.template || task.id);
  const inScope = task => reviewOnly ? isReview(task) : task.category !== 'observation' && !isReview(task);
  root.innerHTML = `<div class="task-head"><div><h2>${t('tasks.header.title')}</h2><span class="task-eyebrow">${t('tasks.header.eyebrow')}</span></div><span class="task-runtime"></span></div>
    <div class="task-layout"><aside class="task-controls">
    <details class="task-setup studio-card" open><summary>${t('tasks.section.setup')}</summary><div class="studio-card-body"><form class="task-form"><label>${t('tasks.field.executionMethod')}<select class="task-provider"><option value="">${t('tasks.option.localProcessing')}</option></select></label><details class="task-local-guide"><summary>${t('tasks.section.localGuide')}</summary><p>${t('tasks.localGuide.intro')}</p><ul><li>${t('tasks.localGuide.example1')}</li><li>${t('tasks.localGuide.example2')}</li><li>${t('tasks.localGuide.example3')}</li></ul><p>${t('tasks.localGuide.outro')}</p></details><label>${t('tasks.field.task')}<select class="task-template"></select></label><p class="task-description"></p><div class="task-params"></div><details class="task-advanced"><summary>${t('tasks.section.advancedParams')}</summary><label>${t('tasks.field.extraParamsJson')}<textarea class="task-extra" rows="3" placeholder="{}"></textarea></label></details><details class="ui-paths"><summary>${t('tasks.section.addInputByPath')}</summary><label>${t('tasks.field.inputFilePath')}<textarea class="task-inputs" rows="2" placeholder="${t('tasks.placeholder.inputPaths')}"></textarea></label></details><button class="btn-white-primary" type="submit">${t('tasks.button.startTask')}</button></form></div></details>
    <details class="task-library studio-card" open><summary>${t('tasks.section.taskLibrary')}</summary><div class="studio-card-body"><div class="task-list" aria-label="${t('tasks.ariaLabel.taskList')}"></div><details class="task-files"><summary>${t('tasks.section.outputFiles')}</summary><div class="task-artifacts"></div></details><details class="task-records"><summary>${t('tasks.section.runLog')}</summary><pre class="task-log"></pre></details></div></details></aside>
    <section class="task-result"><p class="task-empty">${t('tasks.empty.selectTaskHint')}</p><div class="task-canvas" hidden></div><div class="task-animation" hidden><button type="button">${t('tasks.button.play')}</button><select aria-label="${t('tasks.ariaLabel.animationClip')}"></select><input aria-label="${t('tasks.ariaLabel.animationTime')}" type="range" min="0" value="0" step="0.01"></div></section></div><p class="task-error" role="alert" hidden></p>`;
  if (reviewOnly) {
    root.querySelector('.task-head h2').textContent = t('tasks.reviewOnly.headerTitle');
    root.querySelector('.task-eyebrow').textContent = t('tasks.reviewOnly.eyebrow');
    root.querySelector('.task-setup>summary').textContent = t('tasks.reviewOnly.setupSummary');
    root.querySelector('.task-library>summary').textContent = t('tasks.reviewOnly.librarySummary');
    root.querySelector('.task-provider').closest('label').hidden = true;
    root.querySelector('.task-template').closest('label').firstChild.textContent = t('tasks.reviewOnly.templateLabel');
    root.querySelector('.task-list').setAttribute('aria-label', t('tasks.reviewOnly.librarySummary'));
    root.querySelector('.task-form button[type=submit]').textContent = t('tasks.reviewOnly.openButton');
    root.querySelector('.task-empty').textContent = t('tasks.reviewOnly.emptyHint');
  }
  const shell = createStudioShell(root, { layout: '.task-layout', stage: '.task-result', library: '.task-library', settings: '.task-setup', title: reviewOnly ? t('tasks.shellTitle.review') : t('tasks.shellTitle.default'), sections: ['.task-head', '.task-files', '.task-records'] });
  const $ = (selector) => root.querySelector(selector);
  $('.task-records').open = false;
  const settings = !reviewOnly && api.services ? createServiceSettings(api, async id => {
    caps = await api.capabilities(); populateProviders(id);
  }) : null;
  if (settings) {
    const button = node('button', t('tasks.button.manageServices'), 'task-service-settings'); button.type = 'button';
    button.onclick = () => settings.open($('.task-provider').value);
    $('.task-provider').closest('label').after(button);
  }
  const description = $('.task-description');
  const fit = node('button', t('tasks.button.fitView'), 'task-fit'); fit.type = 'button'; fit.onclick = () => preview?.fit(); $('.task-canvas').append(fit);
  const upload = node('input'); upload.type = 'file'; upload.multiple = true;
  upload.accept = '.glb,.stl,.obj,.ply,.blend,.fbx,.bvh,.step,.png,.jpg,.jpeg,.webp,.json,.npy,.npz';
  const uploadLabel = node('label', t('tasks.field.selectInputFiles')); uploadLabel.append(upload); $('.task-inputs').closest('.ui-paths').before(uploadLabel);
  const selectionLabel = node('label', t('tasks.field.useCurrentSelection'), 'task-check'), fromSelection = node('input'); fromSelection.type = 'checkbox'; selectionLabel.prepend(fromSelection); uploadLabel.before(selectionLabel);
  selectionLabel.hidden = reviewOnly; // Reviews require catalogs with adjacent assets, not a selection GLB.
  const revisionNote = node('p', '', 'task-description'); revisionNote.hidden = true; $('.task-form').prepend(revisionNote);
  const luxControls = node('div', null, 'task-lux-controls'); luxControls.hidden = true;
  const balanceButton = node('button', t('tasks.button.checkBalance')), quoteButton = node('button', t('tasks.button.getQuote'));
  const recovery = node('input'); recovery.placeholder = t('tasks.placeholder.existingLux3dTaskId'); recovery.setAttribute('aria-label', t('tasks.ariaLabel.lux3dRemoteTaskId'));
  const recoverButton = node('button', t('tasks.button.resumeRetrieval')), historyButton = node('button', t('tasks.button.queryRemoteTasks'));
  const quoteNote = node('p', '', 'task-description'); quoteNote.setAttribute('role', 'status');
  for (const button of [balanceButton, quoteButton, recoverButton, historyButton]) button.type = 'button';
  luxControls.append(balanceButton, quoteButton, quoteNote, recovery, recoverButton, historyButton);
  $('.task-form button[type=submit]').before(luxControls);
  let luxQuote = null;
  const clearQuote = () => { luxQuote = null; quoteNote.textContent = ''; };
  $('.task-form').addEventListener('input', clearQuote);
  const resetRevision = node('button', t('tasks.button.cancelParamEdit')); resetRevision.type = 'button'; resetRevision.hidden = true; revisionNote.after(resetRevision);
  const speed = node('select'); speed.setAttribute('aria-label', t('tasks.ariaLabel.previewPlaybackSpeed'));
  for (const rate of [.25,.5,1,1.5,2,4]) { const option = node('option', rate+'×'); option.value = rate; speed.append(option); }
  speed.value = 1; speed.onchange = () => preview?.setSpeed(Number(speed.value)); $('.task-animation').append(speed);
  const newTask = node('button', t('entry.newTask'), 'task-new-button'); newTask.type = 'button';
  $('.task-result').append(newTask);
  newTask.onclick = () => { root.classList.remove('result-browsing', 'direct-preview'); shell.setDirectPreview(false); clearRebuild(); shell.reveal($('.task-form')); };
  const primaryActions = node('div', null, 'task-primary-actions');
  $('.task-files').before(primaryActions);
  $('.task-files').open = false; $('.task-records').open = false;
  const media = node('div', null, 'task-media'); media.hidden = true; $('.task-canvas').after(media);
  let active = true, disposed = false, busy = false, selected = null, stamp = '', timer = null, preview = null, previewKey = '', previewType = '', mediaUrl = '', html = '', caps;
  let rebuildId = null, taskList = [], previewRequest = 0, lastPreview = null;
  let reviewTask = null;
  const remembered = new Map();
  const browser = createModelBrowser(api, (task, artifact) => showArtifact(task, artifact).catch(error), () => {
    if (lastPreview) { lastPreview.displayName = browser.label(lastPreview.artifact, lastPreview.task); renderCurrent(lastPreview.task, lastPreview.artifact); options.onPreview?.(lastPreview); }
  });
  const current = node('div', null, 'model-current'), currentName = node('strong'), currentStatus = node('small');
  current.setAttribute('aria-live', 'polite'); current.append(currentName, currentStatus);
  const rename = node('button', t('models.rename')); rename.type = 'button'; current.append(rename);
  const nameForm = node('form', null, 'model-name-form'); nameForm.hidden = true;
  const nameInput = node('input'); nameInput.maxLength = 80; nameInput.required = true; nameInput.setAttribute('aria-label', t('models.displayName'));
  const saveName = node('button', t('tasks.button.save')); saveName.type = 'submit';
  const cancelName = node('button', t('common.cancel')); cancelName.type = 'button'; cancelName.onclick = () => { nameForm.hidden = true; rename.focus(); };
  nameForm.append(nameInput, saveName, cancelName);
  rename.onclick = () => { if (!lastPreview) return; nameInput.value = browser.label(lastPreview.artifact, lastPreview.task); nameForm.hidden = false; nameInput.focus(); nameInput.select(); };
  nameForm.onsubmit = event => { event.preventDefault(); if (lastPreview && browser.rename(lastPreview.artifact, nameInput.value, lastPreview.task)) { nameForm.hidden = true; rename.focus(); } };
  const stage = node('div', null, 'model-stage'); stage.append($('.task-empty'), $('.task-canvas'), media);
  const loading = node('div', null, 'model-loading'); loading.hidden = true; loading.setAttribute('role', 'status'); stage.append(loading);
  const status = node('p', null, 'model-status'); status.hidden = true;
  const retry = node('button', t('entry.retry')); retry.type = 'button'; retry.hidden = true;
  const clock = node('span', '0.00 / 0.00 s', 'model-clock'); $('.task-animation').append(clock);
  const secondary = node('div', null, 'model-secondary');
  const versions = node('details', null, 'model-versions'); versions.append(node('summary', t('models.history')));
  const versionList = node('div'); versions.append(versionList);
  const allTasks = node('button', t('entry.allTasks')); allTasks.type = 'button'; allTasks.onclick = () => { root.classList.toggle('result-history-open'); shell.openLibrary(); }; versions.append(allTasks);
  if (!reviewOnly) secondary.append(versions, $('.task-files'), $('.task-records'));
  $('.task-result').prepend(browser.element, current, nameForm, stage, $('.task-animation'), status, retry, primaryActions, secondary);
  function setPending(value) {
    root.classList.toggle('model-loading-active', value); loading.hidden = !value;
    for (const el of [...primaryActions.querySelectorAll('button'), ...$('.task-animation').querySelectorAll('button,select,input'), rename]) el.disabled = value;
  }
  function renderCurrent(task, artifact) {
    const isModel = /\.glb$/i.test(artifact.name), name = isModel ? browser.label(artifact, task) : artifact.name;
    currentName.textContent = name; rename.hidden = !isModel; nameForm.hidden = true;
    currentStatus.textContent = t(isModel ? (artifact.animations ? 'models.previewReady' : 'models.static') : 'models.filePreview');
    status.hidden = !isModel; status.textContent = [!artifact.animations && t('models.noAnimation'), task.result?.note || (artifact.animations && t('models.animationDraft'))].filter(Boolean).join(' ');
    primaryActions.replaceChildren();
    if (isModel) {
      const save = node('button', t('models.download', { name }), 'model-download'); save.type = 'button';
      save.onclick = () => action(async () => {
        const bytes = await api.taskAsset(task.id, artifact), url = URL.createObjectURL(new Blob([bytes], { type: artifact.mime }));
        const link = node('a'); link.href = url; link.download = artifact.name.split('/').pop(); link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      }); primaryActions.append(save);
      if (!(artifact.animations || artifact.skins)) {
        const add = node('button', t('entry.addToEditor')); add.type = 'button';
        add.onclick = () => action(async () => { const state = await api.getState(); await api.task({ action: 'import', id: task.id, artifact_id: artifact.id, expected_revision: state.workbench.revision }); options.onImport?.(); });
        primaryActions.append(add);
      }
    }
    browser.select(artifact, false, task); versionList.replaceChildren();
    const group = resultGroups(taskList).find(group => group.tasks.some(item => item.id === task.id));
    for (const item of (group?.tasks || [task]).filter(item => (item.result?.variant || '') === (task.result?.variant || ''))) {
      const button = node('button', [item.result?.version || item.title, resultTimeLabel(item)].filter(Boolean).join(' · ')); button.type = 'button';
      button.setAttribute('aria-pressed', String(item.id === task.id));
      button.onclick = () => openResult(item.id).catch(error); versionList.append(button);
    }
  }

  const saveReview = async event => {
    const frame = media.querySelector('iframe'), data = event.data;
    if (!reviewTask || !frame || event.source !== frame.contentWindow || data?.type !== 'workbench-review-export') return;
    const task = reviewTask;
    try {
      const payload = data.payload;
      if (payload?.schema !== 'assembly-scene-curation/v1' || !Array.isArray(payload.decisions) || payload.decisions.length > 8 || !Array.isArray(payload.scope?.executionKeys) || payload.scope.executionKeys.length > 8) throw new Error(t('tasks.error.invalidReviewMarker'));
      const content = JSON.stringify(payload, null, 2);
      if (content.length > 100000) throw new Error(t('tasks.error.markerFileTooLarge'));
      const result = await uploadFile(body => api.task(body), new File([content], `review-${task}-${Date.now()}.json`, { type: 'application/json' }));
      if (frame.isConnected) frame.contentWindow.postMessage({ type: 'workbench-review-saved', path: result.path }, '*');
    } catch (e) { if (frame.isConnected) frame.contentWindow.postMessage({ type: 'workbench-review-saved', error: e.message }, '*'); }
  };
  window.addEventListener('message', saveReview);
  function clearRebuild() { rebuildId = null; revisionNote.hidden = true; resetRevision.hidden = true; $('.task-form button[type=submit]').textContent = reviewOnly ? t('tasks.reviewOnly.openButton') : t('tasks.button.startTask'); $('.task-inputs').disabled = false; upload.disabled = false; fromSelection.disabled = false; }
  resetRevision.onclick = clearRebuild;
  function clearMedia() { media.replaceChildren(); if (mediaUrl) URL.revokeObjectURL(mediaUrl); mediaUrl = ''; html = ''; }
  function mountHtml() { const frame = node('iframe'); frame.title = t('tasks.iframeTitle.interactiveResult'); frame.setAttribute('sandbox', 'allow-scripts allow-downloads'); frame.srcdoc = sandboxedHtml(html); media.append(frame); }
  const error = (e) => { $('.task-error').textContent = e.message; $('.task-error').hidden = false; };
  const service = () => caps.services?.find((x) => x.id === $('.task-provider').value);
  function sourceChoices(remote) {
    return { '': t('tasks.option.selectCompletedFbxTask'), ...Object.fromEntries(taskList.filter(t => t.status === 'completed' && t.service?.provider === remote?.id && t.service?.operation !== 'segment' && t.service?.output_formats?.includes('FBX')).map(t => [t.id, t.title])) };
  }
  function refreshSources() {
    const select = $('.task-params [name=source_task]');
    if (!select || service()?.adapter !== 'hunyuan-responses') return;
    const choices = sourceChoices(service()), signature = JSON.stringify(choices);
    if (select.dataset.sources === signature) return;
    const selected = select.value; select.replaceChildren();
    for (const [id, title] of Object.entries(choices)) { const option = node('option', title); option.value = id; select.append(option); }
    select.value = selected in choices ? selected : ''; select.dataset.sources = signature;
  }
  const operationLabels = () => ({ 'text-to-3d': t('tasks.operation.textToModel'), text_to_model: t('tasks.operation.textToModel'), 'image-to-3d': t('tasks.operation.imageToModel'), image_to_model: t('tasks.operation.imageToModel'), 'multi-image-to-3d': t('tasks.operation.multiviewToModel'), multiview_to_model: t('tasks.operation.multiviewToModel'), retexture: t('tasks.operation.retexture'), remesh: t('tasks.operation.remesh'), rigging: t('tasks.operation.autoRig'), animations: t('tasks.operation.generateCharacterAnimation'), animate_rig: t('tasks.operation.autoRig'), animate_retarget: t('tasks.operation.retargetAnimation'), texture_model: t('tasks.operation.textureModel'), convert_model: t('tasks.operation.convertFormat') });
  function templates() {
    $('.task-template').replaceChildren();
    const remote = service();
    const list = remote ? remote.operations.map((id) => remote.operation_templates?.find(x => x.id === id) || ({ id, title: operationLabels()[id] || id })) : caps.templates.filter(inScope);
    for (const template of list) { const option = node('option', template.title); option.value = template.id; $('.task-template').append(option); }
    fields();
  }
  function populateProviders(preferred) {
    const previous = $('.task-provider').value, operation = $('.task-template').value;
    const values = Object.fromEntries([...$('.task-params').querySelectorAll('[name]')].map(e => [e.name, e.type === 'checkbox' ? e.checked : e.value]));
    const extra = $('.task-extra').value;
    $('.task-provider').replaceChildren();
    const local = node('option', t('tasks.option.localProcessing')); local.value = ''; $('.task-provider').append(local);
    for (const remote of reviewOnly ? [] : caps.services || []) { const option = node('option', remote.title + (remote.configured ? '' : t('tasks.option.notConfiguredSuffix'))); option.value = remote.id; $('.task-provider').append(option); }
    const target = preferred ?? previous;
    $('.task-provider').value = caps.services?.some(s => s.id === target) ? target : '';
    templates();
    if ($('.task-provider').value === previous && [...$('.task-template').options].some(o => o.value === operation)) {
      $('.task-template').value = operation; fields(values); $('.task-extra').value = extra;
    }
  }
  function fields(values = null) {
    clearQuote();
    const remote = service(), op = $('.task-template').value;
    luxControls.hidden = remote?.adapter !== 'lux3d';
    const template = remote ? remote.operation_templates?.find(x => x.id === op) || { params: op.includes('text-to') || op === 'text_to_model' ? { prompt: '' } : op === 'animations' ? { rig_task_id: '', action_id: 0 } : {} } : caps.templates.find((x) => x.id === op);
    const inputMode = template.input_mode || remote?.input_mode;
    const remoteUrls = inputMode === 'remote_urls';
    selectionLabel.hidden = reviewOnly || remoteUrls || inputMode === 'image';
    uploadLabel.hidden = remoteUrls;
    $('.ui-paths').hidden = remoteUrls;
    $('.task-local-guide').hidden = reviewOnly || !!remote;
    if (remoteUrls || inputMode === 'image') fromSelection.checked = false;
    description.textContent = [template.description || '', remote ? remote.configured ? t('tasks.description.remoteConfigured') : remote.setup_message || t('tasks.description.remoteNotConfigured', { name: remote.key_env || t('tasks.fallback.service') }) : t('tasks.description.localTool')].filter(Boolean).join(' ');
    $('.task-params').replaceChildren();
    const labels = { diameter_mm: t('tasks.paramLabel.diameterMm'), height_mm: t('tasks.paramLabel.heightMm'), wall_mm: t('tasks.paramLabel.wallMm'), clearance_mm: t('tasks.paramLabel.clearanceMm'), width_mm: t('tasks.paramLabel.widthMm'), pin_mm: t('tasks.paramLabel.pinMm'), ratio: t('tasks.paramLabel.ratio'), thickness_mm: t('tasks.paramLabel.thicknessMm'), voxel_mm: t('tasks.paramLabel.voxelMm'), iterations: t('tasks.paramLabel.iterations'), spacing_mm: t('tasks.paramLabel.spacingMm'), operation: t('tasks.paramLabel.operation'), angle_deg: t('tasks.paramLabel.angleDeg'), frames: t('tasks.paramLabel.frames') };
    for (const [key, value] of Object.entries(template.params)) {
      const choices = key === 'source_task' && remote?.adapter === 'hunyuan-responses'
        ? sourceChoices(remote)
        : template.choices?.[key] || (key === 'operation' && op === 'mesh-process' ? { smooth: t('tasks.meshOp.smooth'), decimate: t('tasks.meshOp.decimate'), solidify: t('tasks.meshOp.solidify'), remesh: t('tasks.meshOp.remesh'), uv: t('tasks.meshOp.uv') } : null);
      const label = node('label', { prompt: t('tasks.paramLabel.prompt'), version: t('tasks.paramLabel.version'), faceCount: t('tasks.paramLabel.faceCount'), outputFormat: t('tasks.paramLabel.outputFormat'), name: t('tasks.paramLabel.name'), family: t('tasks.paramLabel.family'), rig_task_id: t('tasks.paramLabel.rigTaskId'), action_id: t('tasks.paramLabel.actionId'), layer_mm: t('tasks.paramLabel.layerMm'), margin_mm: t('tasks.paramLabel.marginMm'), depth_mm: t('tasks.paramLabel.depthMm'), inner_width_mm: t('tasks.paramLabel.innerWidthMm'), inner_depth_mm: t('tasks.paramLabel.innerDepthMm'), inner_height_mm: t('tasks.paramLabel.innerHeightMm'), floor_z_mm: t('tasks.paramLabel.floorZMm'), center_x_mm: t('tasks.paramLabel.centerXMm'), center_y_mm: t('tasks.paramLabel.centerYMm'), lip_height_mm: t('tasks.paramLabel.lipHeightMm'), opening_width_mm: t('tasks.paramLabel.openingWidthMm'), opening_depth_mm: t('tasks.paramLabel.openingDepthMm'), allow_material_loss: t('tasks.paramLabel.allowMaterialLoss'), axis: t('tasks.paramLabel.axis'), start_mm: t('tasks.paramLabel.startMm'), end_mm: t('tasks.paramLabel.endMm'), delta_mm: t('tasks.paramLabel.deltaMm'), ...labels, ...template.labels }[key] || key), input = node(choices ? 'select' : 'input');
      input.name = key;
      if (choices) for (const [id, title] of Object.entries(choices)) { const option = node('option', title); option.value = id; input.append(option); }
      else { input.type = typeof value === 'boolean' ? 'checkbox' : typeof value === 'number' ? 'number' : 'text'; input.step = 'any'; input.required = input.type !== 'checkbox' && !template.optional_params?.includes(key); }
      if (input.type === 'checkbox') { input.checked = values?.[key] ?? value; label.classList.add('task-check'); }
      else input.value = values?.[key] ?? value;
      label.append(input); $('.task-params').append(label);
    }
    if (values) $('.task-extra').value = JSON.stringify(Object.fromEntries(Object.entries(values).filter(([key]) => !(key in template.params))), null, 2);
    else $('.task-extra').value = '';
    $('.task-form button[type=submit]').disabled = !!remote && !remote.configured;
  }
  async function action(fn) {
    if (busy) return;
    busy = true; $('.task-error').hidden = true; $('.task-form button[type=submit]').disabled = true;
    try { await fn(); await refresh(); } catch (e) { error(e); }
    finally { busy = false; $('.task-form button[type=submit]').disabled = !!service() && !service().configured; }
  }
  upload.onchange = () => action(async () => {
    const paths = [];
    for (const file of upload.files) paths.push((await uploadFile((body) => api.task(body), file)).path);
    $('.task-inputs').value = [$('.task-inputs').value, ...paths].filter(Boolean).join('\n'); upload.value = '';
  });
  $('.task-provider').onchange = () => { clearRebuild(); templates(); };
  $('.task-template').onchange = () => { clearRebuild(); fields(); };
  function formParams() {
    const extra = JSON.parse($('.task-extra').value || '{}');
    if (!extra || typeof extra !== 'object' || Array.isArray(extra)) throw new Error(t('tasks.error.extraParamsMustBeJsonObject'));
    return { ...Object.fromEntries([...$('.task-params').querySelectorAll('[name]')].map((e) => [e.name, e.type === 'checkbox' ? e.checked : e.type === 'number' ? Number(e.value) : e.value])), ...extra };
  }
  const filePaths = () => $('.task-inputs').value.split('\n').map(x => x.trim()).filter(Boolean);
  balanceButton.onclick = () => action(async () => {
    const result = await api.services({ action: 'balance', id: service().id });
    quoteNote.textContent = t('tasks.status.balanceRefreshed', { credits: result.account.availableCredits });
  });
  quoteButton.onclick = () => action(async () => {
    clearQuote();
    const params = formParams(), inputs = filePaths();
    let revision = null;
    if (fromSelection.checked) {
      const state = (await api.getState()).workbench; revision = state.revision;
      if (!state.selection.length) throw new Error(t('tasks.error.selectModelFirst'));
      const exported = await api.edit({ action: 'export', expected_revision: revision, params: { ids: state.selection } });
      inputs.push(exported.path);
    }
    const request = { action: 'quote', id: service().id, operation: $('.task-template').value, params, inputs };
    const result = await api.services(request);
    luxQuote = { request, result, revision };
    quoteNote.textContent = t('tasks.status.quoteReady', { estimated: result.quote.estimatedCreditsTotal, available: result.account.availableCredits });
  });
  recoverButton.onclick = () => action(async () => {
    if (!/^[1-9][0-9]{0,19}$/.test(recovery.value.trim())) throw new Error(t('tasks.error.invalidRemoteTaskId'));
    const result = await api.task({ action: 'start', provider: service().id, operation: $('.task-template').value,
      timeout_seconds: 1800, params: { ...formParams(), remote_task_id: recovery.value.trim() } });
    selected = result.task.id; stamp = '';
  });
  historyButton.onclick = () => action(async () => {
    const result = await api.services({ action: 'remote_tasks', id: service().id });
    quoteNote.textContent = JSON.stringify(result.history, null, 2);
  });
  $('.task-form').onsubmit = (event) => {
    event.preventDefault();
    action(async () => {
      let params = formParams();
      const remote = service();
      const inputMode = remote?.operation_templates?.find(t => t.id === $('.task-template').value)?.input_mode || remote?.input_mode;
      let input = inputMode === 'remote_urls' ? { inputs: [] } : fromSelection.checked ? { from_selection: true, expected_revision: (await api.getState()).workbench.revision } : { inputs: filePaths() };
      if (remote?.adapter === 'lux3d') {
        if (!luxQuote) throw new Error(t('tasks.error.needLux3dQuoteFirst'));
        if (luxQuote.revision !== null && luxQuote.revision !== (await api.getState()).workbench.revision) { clearQuote(); throw new Error(t('tasks.error.selectionChangedRefetchQuote')); }
        input = { inputs: luxQuote.request.inputs };
        params = { ...params, quote_id: luxQuote.result.quote_id };
      }
      const result = await api.task(rebuildId ? { action: 'rebuild', id: rebuildId, params } : { action: 'start', ...(remote ? { provider: remote.id, operation: $('.task-template').value, ...(remote.timeout_seconds ? { timeout_seconds: remote.timeout_seconds } : {}) } : { template: $('.task-template').value }), params, ...input });
      clearRebuild();
      selected = result.task.id; stamp = '';
      clearQuote();
    });
  };
  async function showArtifact(task, artifact) {
    const key = `${task.id}:${artifact.id}`;
    const request = ++previewRequest;
    const isCurrent = () => !disposed && request === previewRequest;
    const type = /\.glb$/i.test(artifact.name) ? 'glb' : 'media';
    // Download and parse before replacing the last valid scene or media.
    root.classList.add('result-browsing');
    root.classList.toggle('direct-preview', !reviewOnly); shell.setDirectPreview(!reviewOnly);
    browser.setTask(task); browser.select(artifact, true); retry.hidden = true;
    preview?.play(false);
    if (previewKey === key) { setPending(false); renderCurrent(task, artifact); $('.task-animation button').textContent = t('models.play'); options.onPreview?.(lastPreview); return; }
    setPending(true); loading.textContent = t('models.loading', { name: browser.label(artifact) });
    options.onPreview?.({ task, artifact, displayName: browser.label(artifact), loading: true });
    let bytes, clips;
    try {
      bytes = await api.taskAsset(task.id, artifact, { presentation: /\.html$/i.test(artifact.name) });
      if (!isCurrent()) return;
      if (type === 'glb') {
        preview ||= new TaskPreview($('.task-canvas'), { insets: { bottom: reviewOnly ? 64 : 0 } });
        clips = await preview.load(bytes, { isCurrent });
        if (!isCurrent()) return;
      }
    } catch (e) {
      if (!isCurrent()) return;
      setPending(false);
      if (lastPreview) { renderCurrent(lastPreview.task, lastPreview.artifact); $('.task-animation button').textContent = t('models.play'); }
      else browser.select(null);
      retry.hidden = false; retry.textContent = t('models.retry', { name: browser.label(artifact) }); retry.onclick = () => showArtifact(task, artifact).catch(error);
      options.onPreview?.(lastPreview); throw e;
    }
    previewKey = key; previewType = type;
    setPending(false); renderCurrent(task, artifact);
    if (type === 'glb') remembered.set(task.id, artifact.id);
    lastPreview = { task, artifact, displayName: browser.label(artifact), loading: false };
    options.onPreview?.(lastPreview);
    $('.task-error').hidden = true;
    reviewTask = ['merge-review', 'a8-review'].includes(task.template) && artifact.name === 'index.html' ? task.id : null;
    shell.setEmbedded(/\.html$/i.test(artifact.name));
    clearMedia(); $('.task-empty').hidden = true;
    $('.task-animation').hidden = true; $('.task-canvas').hidden = type !== 'glb'; media.hidden = type !== 'media';
    if (type === 'media') {
      if (preview) { preview.version = (preview.version || 0) + 1; preview.setActive(false); preview.clear(); }
      if (/\.html$/i.test(artifact.name)) {
        html = new TextDecoder().decode(bytes); if (active) mountHtml();
      } else if (/\.(png|jpe?g|webp|svg)$/i.test(artifact.name)) {
        const img = node('img'); img.alt = artifact.name; mediaUrl = URL.createObjectURL(new Blob([bytes], { type: artifact.mime })); img.src = mediaUrl; media.append(img);
      } else {
        const text = new TextDecoder().decode(bytes);
        try { media.append(node('pre', JSON.stringify(JSON.parse(text), null, 2))); } catch { media.append(node('pre', text)); }
      }
      return;
    }
    preview.setActive(active); preview.loop.resize();
    preview.setSpeed(Number(speed.value));
    $('.task-animation').hidden = !clips?.length;
    const select = $('.task-animation select'); select.replaceChildren();
    for (const clip of clips || []) { const option = node('option', clip.name); option.value = clip.index; select.append(option); }
    const range = $('.task-animation input'), button = $('.task-animation button');
    range.max = clips?.[0]?.duration || 1; range.value = 0; button.textContent = t('models.play');
    const updateTime = seconds => { range.value = seconds; clock.textContent = `${Number(seconds).toFixed(2)} / ${Number(range.max).toFixed(2)} s`; };
    preview.onTime = updateTime; updateTime(0);
    select.onchange = () => { preview.play(false); range.max = clips[Number(select.value)].duration; preview.selectClip(Number(select.value)); button.textContent = t('models.play'); };
    button.onclick = () => { preview.play(!preview.playing); button.textContent = preview.playing ? t('tasks.button.pause') : t('models.play'); };
    range.oninput = () => { preview.play(false); button.textContent = t('models.play'); preview.seek(Number(range.value)); updateTime(Number(range.value)); };
  }
  async function detail(task) {
    const result = await api.tasks(task.id);
    if (disposed || selected !== task.id) return;
    task = result.task; $('.task-log').textContent = task.log || task.error || t('tasks.log.none');
    $('.task-head h2').textContent = task.title;
    const identity = resultIdentity(task);
    $('.task-eyebrow').textContent = identity.note;
    browser.setTask(task);
    $('.task-files summary').textContent = t('models.files', { count: task.artifacts?.length || 0 });
    $('.task-files').hidden = !task.artifacts?.length;
    const artifacts = $('.task-artifacts'); artifacts.replaceChildren();
    for (const artifact of orderedArtifacts(task.artifacts)) {
      const row = node('div', null, 'task-artifact'), label = node('span', artifact.name);
      label.title = artifact.path; row.append(label, node('small', `${(artifact.bytes / 1024 / 1024).toFixed(1)} MB`));
      if (/\.(blend|step|stp|png|jpg|html|svg)$/.test(artifact.name)) {
        const open = node('button', t('tasks.button.openFile')); open.onclick = () => action(() => api.task({ action: 'open', id: task.id, artifact_id: artifact.id })); row.append(open);
      }
      if (/\.(glb|png|jpe?g|webp|svg|html|json)$/i.test(artifact.name)) {
        const view = node('button', t('common.view')); view.onclick = () => showArtifact(task, artifact).catch(error); row.append(view);
      }
      if (artifact.name.endsWith('.glb')) {
        const take = node('button', artifact.animations || artifact.skins ? t('tasks.button.animationProject') : t('tasks.button.importBackToEdit'));
        take.disabled = !!(artifact.animations || artifact.skins);
        take.onclick = () => action(async () => { const state = await api.getState(); await api.task({ action: 'import', id: task.id, artifact_id: artifact.id, expected_revision: state.workbench.revision }); options.onImport?.(); });
        row.append(take);
        const replace = node('button', t('tasks.button.replaceSelectedPart'));
        replace.disabled = take.disabled;
        replace.onclick = () => action(async () => {
          const { workbench } = await api.getState();
          if (workbench.selection.length !== 1) throw new Error(t('tasks.error.selectOnePartToReplace'));
          await api.task({ action: 'import', id: task.id, artifact_id: artifact.id,
            replace_ids: workbench.selection, expected_revision: workbench.revision,
            ...(workbench.collaboration ? { expected_versions: Object.fromEntries(workbench.objects.map(o => [o.id, o.version])) } : {}) });
          options.onImport?.();
        });
        row.append(replace);
      }
      const pathDetails = node('details', null, 'task-artifact-path');
      const pathSummary = node('summary', t('entry.fileLocation'));
      const pathInput = node('input'); pathInput.readOnly = true; pathInput.value = artifact.path || '';
      pathInput.setAttribute('aria-label', t('entry.pathFor', { name: artifact.name }));
      pathInput.onclick = () => pathInput.select(); pathDetails.append(pathSummary, pathInput);
      const download = node('button', t('tasks.button.save')); download.onclick = () => action(async () => {
        const data = await api.taskAsset(task.id, artifact), url = URL.createObjectURL(new Blob([data], { type: artifact.mime }));
        const link = node('a'); link.href = url; link.download = artifact.name.split('/').pop(); link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      }); row.append(download, pathDetails); artifacts.append(row);
    }
    const review = ['merge-review', 'a8-review'].includes(task.template);
    const first = (review && task.artifacts?.find(x => x.name === 'index.html')) || task.artifacts?.find(a => a.id === (remembered.get(task.id) || browser.preferred(task))) || primaryArtifact(task.artifacts, task.result);
    if (first && (!previewKey.startsWith(`${task.id}:`) || !root.classList.contains('result-browsing'))) await showArtifact(task, first);
    else if (first && root.classList.contains('result-browsing')) { if (lastPreview) renderCurrent(task, lastPreview.artifact); options.onPreview?.(lastPreview); }
    else if (!first) { root.classList.remove('direct-preview'); shell.setDirectPreview(false); primaryActions.replaceChildren(); currentName.textContent = task.title; currentStatus.textContent = STATUS()[task.status]; rename.hidden = true; status.hidden = true; setPending(false); ++previewRequest; previewKey = ''; lastPreview = null; options.onPreview?.(null); clearMedia(); shell.setEmbedded(false); media.hidden = true; preview?.setActive(false); $('.task-empty').hidden = false; $('.task-empty').textContent = task.error || (live(task) ? t('tasks.empty.runningHint') : t('tasks.empty.noPreviewableArtifact')); $('.task-canvas').hidden = true; $('.task-animation').hidden = true; }
  }
  async function refresh() {
    if (disposed || !active || !api.tasks) return;
    const raw = await api.tasks();
    const data = { ...raw, tasks: raw.tasks.filter(inScope) };
    taskList = data.tasks;
    refreshSources();
    root.classList.toggle('task-has-history', data.tasks.length > 0);
    shell.setPopulated(data.tasks.length > 0);
    if (!selected && data.tasks.length) selected = data.tasks[0].id;
    const next = JSON.stringify(data.tasks.map((t) => [t.id, t.status, t.service?.progress, t.artifacts?.map(a => a.id), Math.floor(t.elapsed_seconds || 0)])) + selected;
    if (next !== stamp) {
      stamp = next; $('.task-list').replaceChildren();
      for (const task of data.tasks) {
        const row = node('div', null, 'task-item'), button = node('button', null, selected === task.id ? 'selected' : '');
        button.append(node('strong', task.title), node('span', `${STATUS()[task.status] || task.status} · ${Math.round(task.elapsed_seconds || 0)}s`));
        button.onclick = async () => { selected = task.id; stamp = ''; try { await refresh(); $('.task-result').scrollTop = 0; if (matchMedia('(max-width:720px)').matches) root.scrollTop = 0; } catch (e) { error(e); } }; row.append(button);
        if (live(task)) { const cancel = node('button', task.service ? t('tasks.button.stopWaiting') : t('common.cancel')); cancel.title = task.service ? t('tasks.title.remoteCancelNote') : t('tasks.title.stopLocalTask'); cancel.onclick = () => action(() => api.task({ action: 'cancel', id: task.id })); row.append(cancel); }
        if (task.can_resume) { const resume = node('button', t('tasks.button.continueRetrieval')); resume.onclick = () => action(() => api.task({ action: 'resume', id: task.id })); row.append(resume); }
        if (task.editable && !live(task)) {
          const edit = node('button', t('tasks.button.editParams')); edit.onclick = () => {
            editParameters(task);
          }; row.append(edit);
        }
        $('.task-list').append(row);
      }
      const task = data.tasks.find((x) => x.id === selected); if (task) await detail(task);
    }
  }
  function editParameters(task) {
    root.classList.remove('result-browsing', 'direct-preview'); shell.setDirectPreview(false);
    $('.task-provider').value = ''; templates(); $('.task-template').value = task.editable.template; fields(task.editable.params);
    rebuildId = task.id; fromSelection.checked = false; fromSelection.disabled = true; upload.disabled = true;
    $('.task-inputs').value = task.editable.inputs.join('\n'); $('.task-inputs').disabled = true;
    revisionNote.hidden = false; resetRevision.hidden = false; revisionNote.textContent = t('tasks.revisionNote.rebuildFromFrozenInput');
    $('.task-form button[type=submit]').textContent = t('tasks.submitButton.generateNewVersion'); shell.reveal($('.task-form')); $('.task-form').scrollIntoView({ block: 'start' });
  }
  async function openRecipe(template, taskId = null, artifactName = null) {
    await ready;
    if (taskId) {
      selected = taskId; stamp = ''; await refresh();
      if (artifactName) {
        const { task } = await api.tasks(taskId);
        if (artifactName === 'parameters' && task.editable) { editParameters(task); return; }
        const artifact = task.artifacts.find(a => a.name === artifactName) || task.artifacts.find(a => a.name === 'report.json');
        if (artifact) await showArtifact(task, artifact);
      }
    }
    else { clearRebuild(); $('.task-provider').value = ''; templates(); $('.task-template').value = template; fields(); shell.reveal($('.task-form')); }
  }
  const ready = (async () => {
    caps = await api.capabilities();
    $('.task-runtime').textContent = reviewOnly ? t('tasks.runtime.reviewOnly') : caps.blender.available ? t('tasks.runtime.blenderReady') : t('tasks.runtime.blenderMissing');
    populateProviders(); await refresh();
    timer = setInterval(() => refresh().catch(error), 2000);
  })().catch(error);
  async function openResult(id, files = false) {
    selected = id;
    root.classList.add('result-browsing');
    await openRecipe(null, id);
    if (files) {
      shell.reveal($('.task-files'));
      $('.task-files').scrollIntoView({ block: 'nearest' });
      $('.task-files summary').focus();
    }
  }
  return { ready, openRecipe, openResult, openHistory() { root.classList.add('result-history-open'); shell.openLibrary(); }, setState(state) { if (state?.focus_task_id && selected !== state.focus_task_id) { selected = state.focus_task_id; stamp = ''; refresh().catch(error); } }, setActive(value) { if (active === value) return; active = value; preview?.setActive(value && previewType === 'glb'); if (html) { media.replaceChildren(); if (value) mountHtml(); } if (value) refresh().catch(error); }, dispose() { disposed = true; settings?.dispose(); window.removeEventListener('message', saveReview); clearInterval(timer); shell.dispose(); browser.dispose(); preview?.dispose(); clearMedia(); } };
}
