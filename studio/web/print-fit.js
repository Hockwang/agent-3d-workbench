import { t } from './i18n.js';

export function fitRecovery(error, state) {
  const automaticFailed = ['auto_cut_closed', 'auto_cut_limit', 'auto_cut_no_plan', 'auto_cut_verification'].includes(error?.code);
  if (!automaticFailed && !['part_too_large', 'single_plate_overflow'].includes(error?.code)) return null;
  const data = error.payload || {};
  const part = state?.parts?.find(p => p.name === data.part);
  return { code: automaticFailed ? 'part_too_large' : error.code, automaticFailed, message: error.message, part: part?.name || data.part,
    dims: data.dims_mm, available: data.available_mm,
    canCut: !!part && !!state.print_sources?.[state.parts.indexOf(part)],
    plates: data.needed_plates_with_auto };
}

const dimensions = values => Array.isArray(values) && values.length === 3 && values.every(Number.isFinite)
  ? values.map(n => n.toFixed(1)).join(' × ') : null;

export function createFitNotice({ onCut, onAutoCut, onOrient, onMultiPlate }) {
  const dialog = document.createElement('dialog');
  dialog.className = 'print-fit-dialog';
  dialog.setAttribute('aria-labelledby', 'print-fit-title');
  const title = document.createElement('h2'); title.id = 'print-fit-title';
  const body = document.createElement('div');
  const error = document.createElement('p'); error.setAttribute('role', 'alert'); error.hidden = true;
  const actions = document.createElement('div'); actions.className = 'print-fit-actions';
  dialog.append(title, body, error, actions);
  document.getElementById('wb').append(dialog);
  let shown = '', working = false;
  function button(label, action, primary = false) {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = t(label);
    if (primary) b.className = 'primary';
    b.onclick = async () => {
      if (working) return;
      working = true; error.hidden = true;
      const buttons = [...actions.children]; buttons.forEach(n => n.disabled = true);
      try { if (await action() !== false) dialog.close(); }
      catch (e) { error.textContent = e.message; error.hidden = false; }
      finally { working = false; buttons.forEach(n => n.disabled = false); }
    };
    actions.append(b);
  }
  function line(key, args) { const p = document.createElement('p'); p.textContent = t(key, args); body.append(p); }
  dialog.addEventListener('cancel', event => { if (working) event.preventDefault(); });
  return {
    reset() { shown = ''; if (dialog.open) dialog.close(); },
    update(failure, state, active) {
      if (!active) { if (dialog.open && !working) { dialog.close(); shown = ''; } return; }
      if (state?.busy || working) return;
      const info = fitRecovery(failure, state);
      if (!info) { shown = ''; if (dialog.open) dialog.close(); return; }
      const stamp = JSON.stringify([info, state.print_sources]);
      if (shown === stamp) return;
      shown = stamp;
      title.textContent = t(info.automaticFailed ? 'printFit.autoFailed' : info.code === 'part_too_large' ? 'printFit.tooLarge' : 'printFit.crowded');
      body.replaceChildren(); actions.replaceChildren(); error.hidden = true;
      if (info.code === 'part_too_large') {
        if (info.part) line('printFit.part', { name: info.part });
        if (dimensions(info.dims)) line('printFit.dimensions', { dims: dimensions(info.dims) });
        if (dimensions(info.available)) line('printFit.available', { dims: dimensions(info.available) });
        if (info.automaticFailed) { const p = document.createElement('p'); p.textContent = info.message; body.append(p); }
        else line('printFit.cutHint');
        if (info.canCut && onAutoCut && !info.automaticFailed) button('printFit.autoCut', async () => {
          working = false; dialog.close(); shown = '';
          await onAutoCut(); return false;
        }, true);
        if (info.canCut) button('printFit.cut', () => onCut(info.part), !onAutoCut || info.automaticFailed);
        button('printFit.orient', onOrient);
      } else {
        line('printFit.multiHint');
        if (Number.isInteger(info.plates) && info.plates > 1) line('printFit.plates', { count: info.plates });
        button('printFit.multi', async () => {
          // Close before starting the next operation so its own failure can open a fresh notice.
          working = false; dialog.close(); shown = '';
          await onMultiPlate(); return false;
        }, true);
      }
      button('printFit.back', () => {});
      if (!dialog.open) dialog.showModal();
    },
    dispose() { dialog.remove(); },
  };
}
