import { t, getLocale } from './i18n.js';

const node = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (className) el.className = className;
  return el;
};

// Keep the recent list scoped to outputs that the task workspace can open.
export function recentResults(tasks = []) {
  return tasks.filter(task => task.status === 'completed' && task.artifacts?.length &&
    task.category !== 'observation' && !['merge-review', 'a8-review'].includes(task.template))
    .sort((a, b) => (resultDate(b.created)?.getTime() || 0) - (resultDate(a.created)?.getTime() || 0));
}

export function resultDate(created) {
  if (created == null) return null;
  const date = new Date(typeof created === 'number' ? created * 1000 : created);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function primaryArtifact(artifacts = []) {
  return artifacts.find(a => a.name === 'scene.glb') ||
    artifacts.find(a => a.name === 'index.html') ||
    artifacts.find(a => !a.name.includes('/') && /\.glb$/i.test(a.name)) ||
    artifacts.find(a => /\.glb$/i.test(a.name)) ||
    artifacts.find(a => /\.(html|png|jpe?g|webp|json|svg)$/i.test(a.name));
}

export function orderedArtifacts(artifacts = []) {
  const first = primaryArtifact(artifacts);
  const priority = a => a === first ? 0 : /\.zip$/i.test(a.name) ? 1 : !a.name.includes('/') ? 2 : 3;
  return [...artifacts].sort((a, b) => priority(a) - priority(b));
}

export function browserEntry(search = '') {
  const params = new URLSearchParams(search);
  const mode = params.get('mode');
  return {
    mode: ['edit', 'motion', 'tasks', 'observe', 'print'].includes(mode) ? mode : 'edit',
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

export function createQuickAccess({ api, onModel, onOpenFile, onOpenResult, onAttachSelection }) {
  let state = null, results = [], loaded = false, loadError = '', stamp = '', disposed = false;
  let mode = 'edit';
  const bar = node('section', null, 'quick-access');
  bar.setAttribute('aria-label', t('entry.ariaLabel'));
  const location = node('div', null, 'quick-location');
  const project = node('small', t('entry.thisProject'));
  const model = node('button', t('entry.currentModel'));
  model.type = 'button'; model.id = 'quick-current'; model.onclick = onModel;
  location.append(project, model);
  const actions = node('div', null, 'quick-actions');
  const attach = node('button', t('entry.attachSelection'));
  attach.type = 'button'; attach.id = 'quick-attach'; attach.disabled = true;
  attach.onclick = () => { if (!attach.disabled) onAttachSelection?.(); };
  if (onAttachSelection) actions.append(attach);
  const open = node('button', t('entry.openFile'), 'quick-primary');
  open.type = 'button'; open.id = 'quick-open'; open.onclick = onOpenFile;
  const recent = node('button', t('entry.recent'));
  recent.type = 'button'; recent.id = 'quick-recent'; recent.setAttribute('aria-haspopup', 'dialog');
  actions.append(open, recent); bar.append(location, actions);
  document.getElementById('workbench-nav').after(bar);

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
    try { setResults((await api.tasks()).tasks); }
    catch (e) { setError(e); }
    finally { retry.disabled = false; }
  };
  dialog.append(head, scope, search, status, retry, list); document.getElementById('wb').append(dialog);
  dialog.addEventListener('click', event => { if (event.target === dialog) {
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  } });
  dialog.addEventListener('close', () => recent.focus());
  recent.onclick = () => { renderList(); dialog.showModal(); search.focus(); };
  search.oninput = renderList;

  function renderList() {
    if (disposed) return;
    list.replaceChildren();
    retry.hidden = !loadError;
    if (loadError) { status.textContent = t('entry.loadFailed', { detail: loadError }); return; }
    const query = search.value.trim().toLocaleLowerCase();
    const matches = results.filter(task => `${task.title} ${(task.artifacts || []).map(a => a.name).join(' ')}`.toLocaleLowerCase().includes(query));
    status.textContent = !loaded ? t('entry.loading') : !results.length ? t('entry.emptyResults') : !matches.length ? t('entry.noMatches') : t('entry.resultCount', { count: matches.length });
    for (const task of matches) {
      const row = node('article', null, 'quick-result');
      const info = node('div', null, 'quick-result-info');
      info.append(node('h3', task.title || t('entry.untitled')));
      const date = resultDate(task.created);
      info.append(node('small', [date?.toLocaleString(getLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }), t('entry.filesCount', { count: task.artifacts.length })].filter(Boolean).join(' · ')));
      const buttons = node('div', null, 'quick-result-actions');
      for (const files of [false, true]) {
        if (!files && !primaryArtifact(task.artifacts)) continue;
        const button = node('button', t(files ? 'entry.files' : 'entry.view'));
        button.type = 'button';
        button.onclick = () => { dialog.close(); onOpenResult(task.id, files); };
        buttons.append(button);
      }
      row.append(info, buttons); list.append(row);
    }
  }
  function setResults(tasks) {
    if (disposed) return;
    const next = recentResults(tasks), nextStamp = JSON.stringify(next.map(task => [task.id, task.title, task.artifacts]));
    const changed = nextStamp !== stamp || !loaded || !!loadError;
    results = next; loaded = true; loadError = ''; stamp = nextStamp;
    recent.textContent = t('entry.recentCount', { count: results.length });
    if (changed && dialog.open) renderList();
  }
  function setError(error) {
    if (disposed) return;
    loadError = error.message || String(error);
    if (dialog.open) renderList();
  }
  function renderSelection() {
    const count = selectionCount(mode, state);
    attach.disabled = !count || Boolean(state?.busy);
    attach.textContent = count ? t('entry.attachSelectionCount', { count }) : t('entry.attachSelection');
    attach.title = t(count ? 'entry.attachSelectionHelp' : 'entry.selectBeforeAttach');
  }
  return {
    setResults, setError,
    setState(next) {
      state = next;
      const wb = state?.workbench, folder = wb?.project_folder;
      project.textContent = folder ? t('entry.project', { name: folder.replace(/[\\/]+$/, '').split(/[\\/]/).pop() }) : t('entry.thisChat');
      project.title = folder || api.workspaceId || '';
      model.textContent = wb?.objects?.length ? t('entry.modelCount', { count: wb.objects.length }) : t('entry.noModel');
      scope.textContent = folder ? t('entry.resultsInProject', { folder }) : t('entry.resultsInChat');
      open.disabled = Boolean(state?.busy);
      renderSelection();
    },
    setMode(nextMode) { mode = nextMode; model.setAttribute('aria-pressed', String(mode === 'edit')); renderSelection(); },
    openResults() { recent.click(); },
    dispose() { disposed = true; dialog.remove(); bar.remove(); },
  };
}
