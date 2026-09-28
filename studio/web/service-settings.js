// Credentials are encrypted here before crossing the MCP tool bridge.
import { t } from './i18n.js';

const bytes = value => Uint8Array.from(atob(value), c => c.charCodeAt(0));
const base64 = value => btoa(String.fromCharCode(...new Uint8Array(value)));
export async function sealCredential(secret, encryption, baseUrl) {
  if (!globalThis.crypto?.subtle) throw new Error(t('serviceSettings.error.noSecureCredentialSupport'));
  const rsa = await crypto.subtle.importKey('spki', bytes(encryption.spki), { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['wrapKey']);
  const aes = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const context = encryption.key_id + '\n' + baseUrl.trim().replace(/\/+$/, '');
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: new TextEncoder().encode(context) }, aes, new TextEncoder().encode(secret));
  return { key_id: encryption.key_id, iv: base64(iv), ciphertext: base64(ciphertext),
    wrapped_key: base64(await crypto.subtle.wrapKey('raw', aes, rsa, 'RSA-OAEP')) };
}

export function createServiceSettings(api, onChange) {
  const dialog = document.createElement('dialog'); dialog.className = 'service-settings';
  dialog.setAttribute('aria-label', t('serviceSettings.title'));
  dialog.innerHTML = `<article><header><div><h2>${t('serviceSettings.title')}</h2><p>${t('serviceSettings.description')}</p></div><button type="button" class="service-close" aria-label="${t('serviceSettings.closeAriaLabel')}">×</button></header>
    <div class="service-body"><aside><button type="button" class="service-add">${t('serviceSettings.addConnectionButton')}</button><div class="service-list" aria-label="${t('serviceSettings.configuredConnectionsAriaLabel')}"></div></aside>
    <form class="service-form"><label>${t('serviceSettings.field.protocol')}<select name="template"></select></label><p class="service-protocol-note"></p>
    <label>${t('serviceSettings.field.connectionName')}<input name="title" required maxlength="100" autocomplete="off"></label>
    <label>${t('serviceSettings.field.apiUrl')}<input name="base_url" type="url" required autocomplete="off" spellcheck="false"></label>
    <label>API key<input name="secret" type="password" autocomplete="new-password" spellcheck="false" placeholder="${t('serviceSettings.field.apiKeyPlaceholder')}"></label><p class="service-key-note"></p>
    <details><summary>${t('serviceSettings.advancedSettings')}</summary><label>${t('serviceSettings.field.orUseEnvVar')}<input name="key_env" placeholder="${t('serviceSettings.field.envVarPlaceholder')}" autocomplete="off" spellcheck="false"></label><label class="service-check"><input name="clear_key" type="checkbox">${t('serviceSettings.field.clearCredential')}</label></details>
    <label class="service-check"><input name="enabled" type="checkbox" checked>${t('serviceSettings.field.enableConnection')}</label>
    <div class="service-actions"><button type="submit" class="btn-white-primary">${t('serviceSettings.saveButton')}</button><button type="button" class="service-probe">${t('serviceSettings.probeButton')}</button><button type="button" class="service-delete">${t('common.delete')}</button></div>
    </form></div><p class="service-status" role="status" aria-live="polite"></p>
    <footer>${t('serviceSettings.footerNote')}</footer></article>`;
  document.body.append(dialog);
  const $ = selector => dialog.querySelector(selector), form = $('.service-form');
  const field = name => form.elements.namedItem(name);
  let data, current = null, busy = false, dirty = false;
  const status = (message, failed = false) => { $('.service-status').textContent = message; $('.service-status').classList.toggle('error', failed); };
  const protocolNote = () => { $('.service-protocol-note').textContent = ['hunyuan', 'seed3d'].includes(field('template').value)
    ? t('serviceSettings.protocolNote.adapted')
    : field('template').value.startsWith('lux3d') ? t('serviceSettings.protocolNote.lux3d')
    : t('serviceSettings.protocolNote.generic'); };
  function select(profile = null) {
    current = profile; dirty = false; form.reset(); status('');
    field('template').value = profile?.template || data.templates[0].id;
    field('template').disabled = !!profile;
    const template = data.templates.find(tpl => tpl.id === field('template').value);
    field('title').value = profile?.title || template.title.split(' · ')[0];
    field('base_url').value = profile?.base_url || template.base_url;
    field('enabled').checked = profile?.enabled !== false;
    field('key_env').value = profile?.key_env || '';
    field('secret').placeholder = profile?.credential_stored ? t('serviceSettings.field.apiKeyPlaceholderStored') : t('serviceSettings.field.apiKeyPlaceholder');
    $('.service-key-note').textContent = profile?.key_env ? t('serviceSettings.keyNote.usingEnvVar', { env: profile.key_env }) : t('serviceSettings.keyNote.willEncrypt');
    $('.service-probe').disabled = !profile?.configured;
    $('.service-delete').hidden = !profile?.removable;
    for (const button of $('.service-list').children) button.classList.toggle('selected', button.dataset.id === profile?.id);
    protocolNote();
  }
  function render(result, selectedId) {
    data = result; $('.service-list').replaceChildren(); field('template').replaceChildren();
    for (const template of data.templates) { const o = document.createElement('option'); o.value = template.id; o.textContent = template.title; field('template').append(o); }
    for (const profile of data.profiles.filter(p => p.editable)) {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.id = profile.id;
      const title = document.createElement('strong'), state = document.createElement('span');
      title.textContent = profile.title; state.textContent = !profile.enabled ? t('serviceSettings.status.disabled') : profile.needs_base_url ? t('serviceSettings.status.needsBaseUrl') : profile.configured ? t('serviceSettings.status.configured') : t('serviceSettings.status.pending');
      button.append(title, state); button.onclick = () => select(profile); $('.service-list').append(button);
    }
    select(data.profiles.find(p => p.id === selectedId) || null);
  }
  const run = async fn => {
    if (busy) return; busy = true;
    // Freeze navigation as well as fields while a save/probe is in flight.
    const controls = [...dialog.querySelectorAll('button,input,select')], disabled = controls.map(c => c.disabled);
    controls.forEach(c => { c.disabled = true; });
    try { await fn(); } catch (e) { status(e.message, true); }
    finally { controls.forEach((c, i) => { if (c.isConnected) c.disabled = disabled[i]; }); busy = false;
      field('template').disabled = !!current; $('.service-probe').disabled = !current?.configured || dirty; }
  };
  field('template').onchange = () => {
    const template = data.templates.find(tpl => tpl.id === field('template').value);
    field('title').value = template.title.split(' · ')[0]; field('base_url').value = template.base_url; protocolNote();
  };
  form.oninput = () => { dirty = true; $('.service-probe').disabled = true; };
  field('base_url').onchange = () => {
    if (current && field('base_url').value.trim().replace(/\/$/, '') !== current.base_url) {
      field('key_env').value = ''; field('clear_key').checked = true;
      status(t('serviceSettings.status.urlChanged'));
    }
  };
  form.onsubmit = event => { event.preventDefault();
    // Capture before run disables inputs. Do not log, persist, or return plaintext.
    const body = { action: 'save', expected_revision: data.revision, ...(current ? { id: current.id } : {}),
      template: field('template').value, title: field('title').value.trim(), base_url: field('base_url').value.trim(),
      enabled: field('enabled').checked, key_env: field('key_env').value.trim(), clear_key: field('clear_key').checked };
    let secret = field('secret').value.trim(); field('secret').value = '';
    run(async () => {
      if (secret) { body.sealed_key = await sealCredential(secret, data.encryption, body.base_url); body.key_env = ''; }
      secret = '';
      const result = await api.services(body); render(result, result.id); await onChange(result.id);
      status(t('serviceSettings.status.saved'));
    });
  };
  $('.service-probe').onclick = () => run(async () => {
    status(t('serviceSettings.status.probing')); const result = await api.services({ action: 'probe', id: current.id });
    status(t('serviceSettings.status.probeResultSuffix', { message: result.message }));
  });
  $('.service-delete').onclick = () => run(async () => {
    const result = await api.services({ action: 'delete', id: current.id, expected_revision: data.revision });
    render(result); await onChange(); status(t('serviceSettings.status.deleted'));
  });
  $('.service-add').onclick = () => select();
  const close = () => { if (!busy) { field('secret').value = ''; dialog.close(); } };
  $('.service-close').onclick = close;
  dialog.addEventListener('cancel', e => { if (busy) e.preventDefault(); else field('secret').value = ''; });
  return { async open(id) {
    if (!dialog.open) dialog.showModal(); status(t('serviceSettings.status.loading'));
    await run(async () => render(await api.services({ action: 'list' }), id));
  }, dispose() { dialog.remove(); } };
}
