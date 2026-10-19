import { t } from './i18n.js';
import { icon } from './vendor/ui/icons.js';

// The start screen reads metadata only. It never creates an editor or loads
// saved geometry until the user chooses a model or explicitly resumes.
export function createStart({ onOpen, onResults, onResume }) {
  const root = document.createElement('section'); root.id = 'start-space';
  root.setAttribute('aria-label', t('start.workspace'));
  root.innerHTML = `<div class="start-content"><span class="start-symbol" aria-hidden="true">${icon('box')}</span>
    <h1>${t('start.title')}</h1><p>${t('start.body')}</p>
    <div class="start-actions"><button type="button" data-start="open" class="start-primary">${t('start.open')}</button><button type="button" data-start="results">${t('entry.recent')}</button></div>
    <button type="button" data-start="resume" class="start-resume" hidden>${t('start.resume')}</button>
    <small class="start-saved" hidden></small><p class="start-status" role="status"></p>
    <input type="file" multiple accept=".glb,.gltf,.stl,.obj,.ply,.3mf" hidden></div>`;
  const find = selector => root.querySelector(selector);
  const input = find('input'), status = find('.start-status'), resume = find('[data-start="resume"]');
  let busy = false, state = null;
  const render = () => {
    for (const button of root.querySelectorAll('button')) button.disabled = busy || Boolean(state?.busy);
    const count = state?.workbench?.objects?.length || 0;
    resume.hidden = !count;
    find('.start-saved').hidden = !count;
    find('.start-saved').textContent = count ? t('start.saved', { count }) : '';
  };
  find('[data-start="open"]').onclick = () => input.click();
  find('[data-start="results"]').onclick = onResults;
  resume.onclick = onResume;
  input.onchange = async () => {
    const files = [...input.files]; if (!files.length || busy) return;
    busy = true; render(); status.textContent = t('start.loading');
    try { await onOpen(files); status.textContent = ''; }
    catch (error) { status.textContent = error.message; }
    finally { busy = false; input.value = ''; render(); }
  };
  return { root, setState(next) { state = next; render(); }, openFile() { input.click(); }, dispose() { root.remove(); } };
}
