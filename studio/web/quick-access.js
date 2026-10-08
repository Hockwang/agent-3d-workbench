import { modelArtifacts } from './model-browser.js';
import { t } from './i18n.js';
import { recentResults, primaryArtifact, resultGroups, resultIdentity, resultTimeLabel, thumbnailArtifact } from './result-model.js';

const node = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (className) el.className = className;
  return el;
};

export { recentResults, primaryArtifact, resultDate } from './result-model.js';
export function orderedArtifacts(artifacts = []) {
  const first = primaryArtifact(artifacts);
  const priority = a => a === first ? 0 : /\.zip$/i.test(a.name) ? 1 : !a.name.includes('/') ? 2 : 3;
  return [...artifacts].sort((a, b) => priority(a) - priority(b));
}

export function browserEntry(search = '') {
  const params = new URLSearchParams(search);
  const mode = params.get('mode');
  return {
    mode: ['edit', 'assembly', 'motion', 'tasks', 'observe', 'print'].includes(mode) ? mode : 'edit',
    taskId: params.get('task') || null,
  };
}

export function selectionCount(mode, state) {
  const editing = ['edit', 'motion'].includes(mode);
  if (!editing && mode !== 'print') return 0;
  const objects = editing ? state?.workbench?.objects : state?.parts;
  const ids = new Set(editing ? state?.workbench?.selection : state?.selection?.parts);
  return (objects || []).filter(o => ids.has(editing ? o.id : o.name)).length;
}

export function createQuickAccess({ api, onModel, onOpenFile, onOpenResult, onOpenHistory, onAttachSelection }) {
  let state = null, results = [], groups = [], loaded = false, loadError = '', stamp = '', disposed = false;
  let mode = 'edit', viewing = null;
  const thumbnails = new Map();
  const bar = node('section', null, 'quick-access');
  bar.setAttribute('aria-label', t('entry.ariaLabel'));
  const location = node('div', null, 'quick-location');
  const project = node('small', t('entry.thisProject'));
  const identity = node('strong', t('entry.editScene'), 'quick-identity');
  const context = node('span', '', 'quick-context');
  context.setAttribute('aria-live', 'polite');
  const detail = node('small', '', 'quick-detail');
  location.append(project, identity, context, detail);
  const actions = node('div', null, 'quick-actions');
  const model = node('button', t('entry.backToEditor'));
  model.type = 'button'; model.id = 'quick-current'; model.onclick = onModel;
  const attach = node('button', t('entry.attachSelection'));
  attach.type = 'button'; attach.id = 'quick-attach'; attach.disabled = true;
  attach.onclick = () => { if (!attach.disabled) onAttachSelection?.(); };
  if (onAttachSelection) actions.append(attach);
  const open = node('button', t('entry.openFile'));
  open.type = 'button'; open.id = 'quick-open'; open.onclick = onOpenFile;
  const recent = node('button', t('entry.recent'));
  recent.type = 'button'; recent.id = 'quick-recent'; recent.setAttribute('aria-haspopup', 'dialog');
  actions.append(model, open, recent); bar.append(location, actions);
  document.getElementById('workbench-nav').after(bar);

  const shelf = node('section', null, 'result-shelf');
  shelf.setAttribute('aria-label', t('entry.latestDelivery'));
  const shelfHead = node('div', null, 'result-shelf-head');
  const shelfTitle = node('strong', t('entry.latestDelivery'));
  const shelfStatus = node('small'); shelfStatus.setAttribute('role', 'status');
  shelfHead.append(shelfTitle, shelfStatus);
  const shelfCards = node('div', null, 'result-shelf-cards');
  shelf.append(shelfHead, shelfCards); bar.after(shelf);

  const dialog = node('dialog', null, 'quick-results');
  dialog.setAttribute('aria-labelledby', 'quick-results-title');
  const head = node('header'), title = node('h2', t('entry.recent'));
  title.id = 'quick-results-title';
  const close = node('button', t('common.close')); close.type = 'button'; close.onclick = () => dialog.close();
  head.append(title, close);
  const scope = node('p', '', 'quick-results-scope');
  const search = node('input'); search.type = 'search'; search.placeholder = t('entry.search');
  search.setAttribute('aria-label', t('entry.search'));
  const status = node('p'); status.setAttribute('role', 'status');
  const list = node('div', null, 'quick-result-list');
  const retry = node('button', t('entry.retry')); retry.type = 'button'; retry.hidden = true;
  retry.onclick = async () => {
    retry.disabled = true;
    try { setResults((await api.tasks()).tasks); } catch (e) { setError(e); }
    finally { retry.disabled = false; }
  };
  const history = node('button', t('entry.allTasks'), 'result-history-link');
  history.type = 'button'; history.onclick = () => { dialog.close(); onOpenHistory?.(); };
  dialog.append(head, scope, search, status, retry, list, history); document.getElementById('wb').append(dialog);
  dialog.addEventListener('click', event => { if (event.target === dialog) {
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  } });
  dialog.addEventListener('close', () => recent.focus());
  recent.onclick = () => { renderList(); dialog.showModal(); search.focus(); };
  search.oninput = renderList;

  function thumbnail(task) {
    const frame = node('span', '◇', 'result-thumb'); frame.setAttribute('aria-hidden', 'true');
    const artifact = thumbnailArtifact(task);
    if (!artifact) return frame;
    const key = `${task.id}:${artifact.id}:${artifact.sha256}`;
    if (!thumbnails.has(key)) thumbnails.set(key, api.taskAsset(task.id, artifact).then(data => {
      if (disposed) return null;
      return URL.createObjectURL(new Blob([data], { type: artifact.mime }));
    }).catch(() => null));
    thumbnails.get(key).then(url => {
      if (disposed || !url || !frame.isConnected) return;
      const image = node('img'); image.alt = ''; image.src = url;
      image.onerror = () => frame.replaceChildren(node('span', '◇'));
      frame.replaceChildren(image);
    });
    return frame;
  }
  function card(task, compact = false) {
    const info = resultIdentity(task), row = node('article', null, compact ? 'result-card' : 'quick-result');
    row.dataset.resultId = task.id;
    const view = node('button', null, 'result-open'); view.type = 'button';
    view.setAttribute('aria-label', t('entry.openNamed', { name: [info.title, task.result?.variant, task.result?.version].filter(Boolean).join(' · ') }));
    const text = node('span', null, 'quick-result-info');
    text.append(node('strong', compact ? task.result?.variant || info.title : info.title));
    const models = modelArtifacts(task).length;
    text.append(node('small', [!compact && task.result?.variant, task.result?.version, models ? t('models.count', { count: models }) : null, resultTimeLabel(task)].filter(Boolean).join(' · ')));
    if (!compact) text.append(node('small', info.note, 'result-note'));
    view.append(thumbnail(task), text); view.onclick = () => { if (dialog.open) dialog.close(); onOpenResult(task.id, false); };
    row.append(view);
    if (!compact) {
      const files = node('button', t('entry.files')); files.type = 'button';
      files.onclick = () => { dialog.close(); onOpenResult(task.id, true); };
      row.append(files);
    }
    return row;
  }
  function markViewing() {
    for (const row of [...shelfCards.querySelectorAll('[data-result-id]'), ...list.querySelectorAll('[data-result-id]')]) {
      const selected = mode === 'tasks' && viewing?.task.id === row.dataset.resultId;
      row.classList.toggle('is-viewing', selected);
      row.querySelector('.result-open')?.setAttribute('aria-pressed', String(selected));
    }
  }
  function renderShelf() {
    shelfCards.replaceChildren();
    const latest = groups[0];
    shelfTitle.textContent = latest ? `${t('entry.latestDelivery')} · ${latest.title}` : t('entry.latestDelivery');
    shelfStatus.textContent = loadError ? t('entry.loadFailed', { detail: loadError }) : !loaded ? t('entry.loading') : !latest ? t('entry.emptyResults') : t('entry.previewKeepsEditor');
    if (latest) for (const task of latest.latest) shelfCards.append(card(task, true));
    markViewing();
  }
  function renderList() {
    if (disposed) return;
    list.replaceChildren(); retry.hidden = !loadError;
    if (loadError) { status.textContent = t('entry.loadFailed', { detail: loadError }); return; }
    const query = search.value.trim().toLocaleLowerCase();
    const matches = results.filter(task => `${task.title} ${Object.values(task.result || {}).join(' ')} ${(task.artifacts || []).map(a => a.name).join(' ')}`.toLocaleLowerCase().includes(query));
    status.textContent = !loaded ? t('entry.loading') : !results.length ? t('entry.emptyResults') : !matches.length ? t('entry.noMatches') : t('entry.resultCount', { count: matches.length });
    for (const group of resultGroups(matches)) {
      const section = node('section', null, 'result-group');
      section.append(node('h3', group.title));
      for (const task of group.latest) section.append(card(task));
      if (group.older.length) {
        const older = node('details'); older.append(node('summary', t('entry.olderVersions', { count: group.older.length })));
        older.addEventListener('toggle', () => { if (older.open && older.childElementCount === 1) { for (const task of group.older) older.append(card(task)); markViewing(); } });
        section.append(older);
      }
      list.append(section);
    }
    markViewing();
  }
  function setResults(tasks) {
    if (disposed) return;
    const next = recentResults(tasks), nextStamp = JSON.stringify(next.map(task => [task.id, task.title, task.finished, task.result, task.artifacts]));
    const changed = nextStamp !== stamp || !loaded || !!loadError;
    results = next; groups = resultGroups(next); loaded = true; loadError = ''; stamp = nextStamp;
    recent.textContent = t('entry.recentCount', { count: groups.length });
    if (changed) { renderShelf(); if (dialog.open) renderList(); }
  }
  function setError(error) {
    if (disposed) return;
    loadError = error.message || String(error); renderShelf();
    if (dialog.open) renderList();
  }
  function renderIdentity() {
    const wb = state?.workbench, previewing = mode === 'tasks' && viewing;
    shelf.hidden = mode !== 'tasks' || Boolean(previewing);
    const count = wb?.objects?.length || 0;
    model.hidden = mode === 'edit' || mode === 'motion';
    if (previewing) {
      const info = resultIdentity(viewing.task, viewing.artifact);
      identity.textContent = viewing.displayName ? `${viewing.displayName} · ${info.title}` : info.title;
      context.textContent = t(viewing.loading ? 'entry.previewLoading' : 'entry.previewMode');
      detail.textContent = info.detail;
    } else if (['edit', 'motion'].includes(mode)) {
      identity.textContent = wb?.name && wb.name !== 'scene' ? wb.name : t('entry.editScene');
      context.textContent = t('entry.editingCount', { count, revision: wb?.revision || 0 });
      detail.textContent = count ? t('entry.editorScope') : t('entry.noModel');
    } else {
      identity.textContent = t(`entry.mode.${mode}`); context.textContent = ''; detail.textContent = '';
    }
    bar.dataset.viewMode = previewing ? 'preview' : mode;
    markViewing();
  }
  function renderSelection() {
    const count = selectionCount(mode, state);
    attach.disabled = !count || Boolean(state?.busy);
    attach.textContent = count ? t('entry.attachSelectionCount', { count }) : t('entry.attachSelection');
    attach.title = t(count ? 'entry.attachSelectionHelp' : 'entry.selectBeforeAttach');
  }
  renderShelf();
  return {
    setResults, setError,
    setPreview(next) { viewing = next; renderIdentity(); },
    setState(next) {
      state = next;
      const folder = state?.workbench?.project_folder;
      project.textContent = folder ? t('entry.project', { name: folder.replace(/[\\/]+$/, '').split(/[\\/]/).pop() }) : t('entry.thisChat');
      project.title = folder || api.workspaceId || '';
      scope.textContent = folder ? t('entry.resultsInProject', { folder }) : t('entry.resultsInChat');
      open.disabled = Boolean(state?.busy); renderIdentity(); renderSelection();
    },
    setMode(nextMode) { mode = nextMode; renderIdentity(); renderSelection(); },
    openResults() { recent.click(); },
    dispose() {
      disposed = true; dialog.remove(); shelf.remove(); bar.remove();
      for (const pending of thumbnails.values()) pending.then(url => { if (url) URL.revokeObjectURL(url); });
      thumbnails.clear();
    },
  };
}
