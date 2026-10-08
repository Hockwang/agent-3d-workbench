import { primaryArtifact } from './result-model.js';
import { TaskPreview } from './task-preview.js';
import { t } from './i18n.js';
import { displayLabel } from './display-label.js';

// Keep diagnostic meshes out of the first-use model chooser.
export function modelArtifacts(task) {
  const artifacts = task.artifacts || [], primary = primaryArtifact(artifacts, task.result);
  return artifacts.filter(a => /\.glb$/i.test(a.name) && (!a.name.includes('/') || a === primary));
}
export function modelLabel(artifact, saved) {
  return displayLabel(saved?.trim() || artifact.name.split('/').pop().replace(/\.glb$/i, '').replace(/[_-]+/g, ' '));
}
const node = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
export function createModelBrowser(api, onSelect, onRename) {
  const element = node('section', null, 'model-browser'); element.hidden = true;
  const heading = node('div', null, 'model-browser-heading'), count = node('strong');
  heading.append(count, node('small', t('models.chooseHint')));
  const cards = node('div', null, 'model-cards'); cards.setAttribute('aria-label', t('models.choose'));
  element.append(heading, cards);
  let task = null, signature = '', disposed = false, generation = 0;
  const memory = new Map(), images = new Map();
  const key = (a, source = task) => `studio.model.${api.workspaceId || 'local'}.${source.id}.${a.id}.${a.sha256 || ''}`;
  const selectionKey = source => `studio.preview.${api.workspaceId || 'local'}.${source.id}`;
  function label(a, source = task) {
    let value = memory.get(key(a, source));
    try { value ??= localStorage.getItem(key(a, source)); } catch { /* Sandboxed hosts can use session memory. */ }
    const generic = /^(scene|model|output|result)\.glb$/i.test(a.name.split('/').pop());
    return modelLabel(a, value || (generic && modelArtifacts(source).length === 1 ? source.title : ''));
  }
  function rename(a, value, source = task) {
    value = value.trim().slice(0, 80);
    if (!value) return false;
    memory.set(key(a, source), value);
    try { localStorage.setItem(key(a, source), value); } catch { /* Names still work during this session. */ }
    for (const button of cards.children) if (source.id === task.id && button.dataset.artifactId === a.id) {
      button.querySelector('strong').textContent = displayLabel(value);
      button.setAttribute('aria-label', t('entry.openNamed', { name: displayLabel(value) }));
    }
    onRename?.(displayLabel(value)); return true;
  }
  function setTask(next) {
    task = next;
    const models = modelArtifacts(task), nextSignature = JSON.stringify([task.id, models.map(a => [a.id, a.sha256])]);
    element.hidden = !models.length;
    if (signature === nextSignature) return;
    signature = nextSignature; const token = ++generation;
    cards.replaceChildren(); count.textContent = t('models.count', { count: models.length });
    for (const artifact of models) {
      const button = node('button', null, 'model-card'); button.type = 'button'; button.dataset.artifactId = artifact.id;
      button.setAttribute('aria-pressed', 'false'); button.setAttribute('aria-label', t('entry.openNamed', { name: label(artifact) }));
      const thumb = node('span', '◇', 'model-thumb'); thumb.setAttribute('aria-hidden', 'true');
      const info = node('span', null, 'model-info');
      info.append(node('strong', label(artifact)), node('small', t(artifact.animations ? 'models.actions' : 'models.static', { count: artifact.animations })));
      button.append(thumb, info); button.onclick = () => onSelect(next, artifact); cards.append(button);
      const cached = images.get(`${task.id}:${artifact.id}:${artifact.sha256}`);
      if (cached) showImage(thumb, cached);
    }
    // One temporary renderer, bounded work, no autoplay and no model mutation.
    renderThumbnails(next, models, token).catch(() => {});
  }
  function showImage(target, src) { const image = node('img'); image.alt = ''; image.src = src; target.replaceChildren(image); }
  async function renderThumbnails(source, models, token) {
    const host = node('div', null, 'model-thumbnail-stage'); document.body.append(host);
    let renderer;
    try {
      for (const artifact of models.slice(0, 12)) {
        if (disposed || generation !== token) return;
        const cacheKey = `${source.id}:${artifact.id}:${artifact.sha256}`;
        if (images.has(cacheKey)) continue;
        try {
          const bytes = await api.taskAsset(source.id, artifact);
          if (disposed || generation !== token) return;
          renderer ||= new TaskPreview(host, { insets: { bottom: 0 } });
          await renderer.load(bytes, { isCurrent: () => !disposed && generation === token });
          if (disposed || generation !== token) return;
          const src = renderer.snapshot(); images.set(cacheKey, src);
          const card = [...cards.children].find(el => el.dataset.artifactId === artifact.id);
          if (card) showImage(card.querySelector('.model-thumb'), src);
        } catch { /* A failed thumbnail never prevents opening the model. */ }
      }
    } finally { renderer?.dispose(); host.remove(); }
  }
  return {
    element, label, rename, setTask,
    preferred(source) { try { return localStorage.getItem(selectionKey(source)); } catch { return null; } },
    select(artifact, loading = false, source = task) {
      if (!loading && task && source.id === task.id && modelArtifacts(task).some(a => a.id === artifact?.id)) {
        try { localStorage.setItem(selectionKey(task), artifact.id); } catch { /* Optional preference. */ }
      }
      for (const button of cards.children) {
        const selected = source?.id === task?.id && button.dataset.artifactId === artifact?.id;
        button.setAttribute('aria-pressed', String(selected)); button.setAttribute('aria-busy', String(selected && loading));
      }
    },
    dispose() { disposed = true; ++generation; images.clear(); },
  };
}
