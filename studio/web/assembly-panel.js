import { t } from './i18n.js';

// Only the HTTP transport exposes this bridge. The MCP app stays self-contained.
export function supportsAssemblyWorkspace(api) {
  return typeof api?.assemblyProject === 'function';
}

export function assemblyBackendOrigin(search = '') {
  const requested = Number(new URLSearchParams(search).get('assemblyBackendPort'));
  const port = Number.isInteger(requested) && requested >= 1024 && requested <= 65535 ? requested : 8766;
  return `http://127.0.0.1:${port}`;
}

const ROUTES = {
  manual: ['manual.html?embed=1', 'manual.html'],
  parametric: ['manual.html?embed=1&mode=parametric', 'manual.html?mode=parametric'],
  presets: ['presets.html?embed=1', 'presets.html'],
  legacy: ['index.html?embed=1', 'index.html'],
};

const node = (tag, text, id) => {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (id) element.id = id;
  return element;
};

export function createAssembly(api, { onImport } = {}) {
  // Check before touching the DOM or constructing a localhost iframe.
  if (!supportsAssemblyWorkspace(api)) throw new Error(t('assembly.error.unavailable'));
  const root = document.getElementById('assembly-space');
  const backendOrigin = assemblyBackendOrigin(globalThis.location?.search || '');
  let disposed = false;
  const bar = node('div'); bar.className = 'assembly-bridge';
  const workflow = node('select', null, 'assembly-workflow');
  workflow.setAttribute('aria-label', t('assembly.workflowAriaLabel'));
  for (const flow of Object.keys(ROUTES)) {
    const option = node('option', t('assembly.workflow.' + flow));
    option.value = flow; workflow.append(option);
  }
  workflow.value = 'manual';
  const button = node('button', t('assembly.import'), 'assembly-import'); button.type = 'button';
  const independent = node('a', t('assembly.openIndependent'), 'assembly-independent');
  independent.target = '_blank'; independent.rel = 'noopener';
  bar.append(node('strong', t('assembly.title')), workflow, button, independent);
  const status = node('p', null, 'assembly-bridge-status'); status.setAttribute('role', 'status');
  const hint = node('p', t('assembly.serviceHint', { origin: backendOrigin })); hint.className = 'assembly-service-hint';
  const frame = node('iframe', null, 'assembly-frame');
  frame.title = t('assembly.frameTitle'); frame.setAttribute('allow', 'clipboard-write');
  root.replaceChildren(bar, status, hint, frame);

  function showWorkflow(flow, navigate = true) {
    if (!ROUTES[flow]) return;
    workflow.value = flow;
    const [embedded, standalone] = ROUTES[flow];
    if (navigate) frame.src = `${backendOrigin}/${embedded}`;
    independent.href = `${backendOrigin}/${standalone}`;
    status.textContent = t('assembly.status.workflow', { name: t('assembly.workflow.' + flow) });
  }
  showWorkflow('manual');
  workflow.onchange = () => showWorkflow(workflow.value);
  frame.onerror = () => { if (!disposed) status.textContent = t('assembly.error.serviceUnavailable', { origin: backendOrigin }); };
  const onFrameMessage = (event) => {
    if (disposed || event.source !== frame.contentWindow || event.origin !== backendOrigin) return;
    if (event.data?.type !== 'assembly:connector-flow' || !['manual', 'parametric'].includes(event.data.flow)) return;
    // The iframe already switched its own view; keep its unsaved work intact.
    showWorkflow(event.data.flow, false);
  };
  window.addEventListener('message', onFrameMessage);

  button.onclick = async () => {
    if (disposed || button.disabled) return;
    button.disabled = true; workflow.disabled = true;
    status.textContent = t('assembly.status.importing');
    try {
      const source = workflow.value === 'parametric' ? 'manual' : workflow.value;
      const project = await api.assemblyProject(source);
      if (disposed) return;
      if (typeof project?.import_file !== 'string' || !project.import_file || project.units !== 'm') {
        throw new Error(t('assembly.error.invalidProject'));
      }
      const state = await api.getState();
      if (disposed) return;
      await api.edit({ action: 'import', params: { files: [project.import_file], units: 'm' }, expected_revision: state.workbench.revision });
      if (disposed) return;
      status.textContent = t('assembly.status.imported', { revision: project.revision });
      onImport?.();
    } catch (error) {
      if (disposed) return;
      const unavailable = ['network_error', 'http_404', 'not_found'].includes(error.code);
      status.textContent = unavailable
        ? t('assembly.error.serviceUnavailable', { origin: backendOrigin })
        : t('assembly.error.importFailed', { detail: error.message });
    } finally {
      if (!disposed) { button.disabled = false; workflow.disabled = false; }
    }
  };

  return {
    ready: Promise.resolve(),
    setState() {},
    setActive(active) { frame.style.visibility = active ? 'visible' : 'hidden'; },
    dispose() {
      disposed = true;
      window.removeEventListener('message', onFrameMessage);
      button.onclick = null; workflow.onchange = null; frame.onerror = null;
      root.replaceChildren();
    },
  };
}
