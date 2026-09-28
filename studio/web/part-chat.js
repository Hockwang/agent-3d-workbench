// Direct, user-authorized backend requests. Never send a prompt to the parent.
import { t } from './i18n.js';
export function operationId(cryptoProvider = globalThis.crypto) {
  if (cryptoProvider.randomUUID) return cryptoProvider.randomUUID();
  // Sandboxed srcdoc hosts may omit randomUUID even with getRandomValues.
  const bytes = cryptoProvider.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(n => n.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export function createPartChatController(api, uuid = operationId) {
  const pending = new Map(), ids = new Map();
  return {
    status: () => api.partChat({ action: 'status' }),
    permission: allowed => api.partChat({ action: allowed ? 'allow' : 'deny' }),
    create(object, revision, existing) {
      if (pending.has(object.id)) return pending.get(object.id);
      const operationId = existing || ids.get(object.id) || uuid();
      ids.set(object.id, operationId);
      const work = api.partChat({ action: 'create', object_id: object.id,
        expected_revision: revision, operation_id: operationId }).finally(() => pending.delete(object.id));
      pending.set(object.id, work); return work;
    },
  };
}

export function createPartChatUI(api) {
  const controller = createPartChatController(api);
  const dialog = document.createElement('dialog'); dialog.className = 'ed-chat-dialog';
  dialog.setAttribute('aria-labelledby', 'ed-chat-title'); document.body.append(dialog);
  let working = false;
  function button(text, click, primary = false) {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = text;
    if (primary) b.className = 'primary'; b.onclick = click; return b;
  }
  function show(title, text) {
    dialog.replaceChildren();
    const h = document.createElement('h2'); h.id = 'ed-chat-title'; h.textContent = title;
    const p = document.createElement('p'); p.textContent = text;
    const actions = document.createElement('div'); actions.className = 'ed-chat-actions';
    dialog.append(h, p, actions); if (!dialog.open) dialog.showModal(); return actions;
  }
  function error(e, retry) {
    const actions = show(t('partChat.error.title'), e.message || String(e));
    actions.append(button(t('common.close'), () => dialog.close()));
    if (retry) actions.append(button(t('partChat.retryStatusButton'), retry, true));
  }
  async function create(object, revision, operationId) {
    if (working) return;
    working = true;
    show(t('partChat.creatingTitle'), t('partChat.creatingBody', { name: object.name }));
    try {
      const result = await controller.create(object, revision, operationId);
      const bound = result.status === 'bound';
      const actions = show(bound ? t('partChat.readyTitle') : t('partChat.notBoundTitle'), result.message || t('partChat.confirmingMessage'));
      actions.append(button(t('common.close'), () => dialog.close()));
      if (result.status === 'binding_failed') actions.append(button(t('partChat.retryBindButton'), () => create(object, revision, result.operation_id)));
      if (result.url) {
        const link = document.createElement('a'); link.href = result.url; link.textContent = t('partChat.taskLinkText'); dialog.insertBefore(link, actions);
        actions.append(button(bound ? t('partChat.openBranchButton') : t('partChat.viewCreatedTaskButton'), async () => {
          try { await api.openPartChat(result.url); dialog.close(); }
          catch (e) { const warning = document.createElement('p'); warning.textContent = e.message; dialog.insertBefore(warning, actions); }
        }, true));
      }
    } catch (e) { error(e, () => create(object, revision, operationId)); }
    finally { working = false; }
  }
  async function settings(object, revision, createAfter = false) {
    try {
      const state = await controller.status();
      if (!state.available) {
        const actions = show(t('partChat.unavailableTitle'), state.message || t('partChat.unavailableMessage'));
        actions.append(button(t('common.close'), () => dialog.close())); return;
      }
      const actions = show(t('partChat.permission.title'), t('partChat.permission.body'));
      actions.append(button(state.enabled ? t('partChat.revokeButton') : t('common.deny'), async () => {
        try { await controller.permission(false); dialog.close(); } catch (e) { error(e); }
      }));
      actions.append(button(t('common.cancel'), () => dialog.close()));
      actions.append(button(createAfter ? t('partChat.allowAndCreateButton') : t('common.allow'), async () => {
        actions.querySelectorAll('button').forEach(b => b.disabled = true);
        try { await controller.permission(true); dialog.close(); if (createAfter) await create(object, revision); }
        catch (e) { error(e); }
      }, true));
    } catch (e) { error(e); }
  }
  return {
    status: controller.status, settings,
    async create(object, revision) {
      try {
        const state = await controller.status();
        if (!state.enabled) return settings(object, revision, true);
        const previous = state.operations?.find(o => o.object_id === object.id);
        return create(object, revision, previous?.operation_id);
      } catch (e) { error(e); }
    },
  };
}
