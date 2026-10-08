// v0.4's card / fixed-rail interaction, shared by the newer workspaces.
// Move existing nodes so forms, transport handlers and drafts survive docking.
import { t } from './i18n.js';
const chevron = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><path d="m4 10 4-4 4 4"/></svg>';
const cross = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><path d="m4 4 8 8m0-8-8 8"/></svg>';
const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
const write = (key, value) => { try { localStorage.setItem(key, value); } catch { /* Storage may be unavailable in embedded apps. */ } };

export function createStudioShell(root, { layout, stage, library, settings, title, sections = [], footer = [], libraryDefaultOpen = false, dockSettings = false }) {
  const find = selector => root.querySelector(selector);
  const host = find(layout), view = find(stage);
  host.classList.add('v04-layout'); view.classList.add('v04-stage');
  view.dataset.stageLabel = t(root.closest('#assembly-observe-space') ? 'shell.stageLabel.assemblyObserve' : 'shell.stageLabel.default');
  const rail = document.createElement('aside'); rail.className = 'v04-plan';
  const head = document.createElement('div'); head.className = 'panel-head';
  const label = document.createElement('span'); label.className = 'panel-title'; label.textContent = title;
  const close = document.createElement('button'); close.type = 'button'; close.className = 'card-close-btn'; close.setAttribute('aria-label', t('shell.collapsePanel', { title })); close.innerHTML = cross;
  head.append(label, close);
  const body = document.createElement('div'); body.className = 'v04-plan-body';
  const dock = document.createElement('div'); dock.className = 'v04-cards-dock'; body.append(dock);
  for (const selector of sections) { const node = find(selector); if (node) { if (node.tagName === 'DETAILS') node.open = true; body.append(node); } }
  const actions = document.createElement('div'); actions.className = 'v04-plan-actions';
  for (const selector of footer) { const node = body.querySelector(selector) || find(selector); if (node) actions.append(node); }
  rail.append(head, body); if (actions.childElementCount) rail.append(actions); host.append(rail);
  const reopen = document.createElement('button'); reopen.type = 'button'; reopen.className = 'pill-btn'; reopen.textContent = title; reopen.hidden = true; view.append(reopen);
  const setRail = hidden => { rail.hidden = hidden; reopen.hidden = !hidden; view.classList.toggle('plan-collapsed', hidden); };
  close.onclick = () => { setRail(true); reopen.focus(); };
  reopen.onclick = () => { setRail(false); close.focus(); };
  const cards = [];
  function convert(selector, side) {
    if (!selector) return null;
    const previous = find(selector), summary = previous.querySelector(':scope > summary');
    const card = document.createElement('section'); card.className = `${previous.className} float-card v04-${side}`;
    card.id = previous.id || `${root.id}-${side}`;
    const header = document.createElement('div'); header.className = 'card-head';
    const heading = document.createElement('span'); heading.className = 'card-title'; heading.append(...summary.childNodes);
    const toggle = document.createElement('button'); toggle.type = 'button'; toggle.className = 'card-fold-btn'; toggle.innerHTML = chevron;
    const cardTitle = heading.textContent.trim(); toggle.setAttribute('aria-label', t('shell.foldCard', { title: cardTitle }));
    const content = previous.querySelector(':scope > .studio-card-body'); content.classList.add('card-body'); content.id = `${card.id}-body`; toggle.setAttribute('aria-controls', content.id);
    header.append(heading, toggle); card.append(header, content); previous.replaceWith(card); view.append(card);
    const key = `pp.card.${card.id}${side === 'library' && libraryDefaultOpen ? '.outline' : ''}`; let pref = read(key);
    const set = collapsed => { card.classList.toggle('collapsed', collapsed); toggle.setAttribute('aria-expanded', String(!collapsed)); };
    const open = () => { pref = 'open'; write(key, pref); set(false); };
    toggle.onclick = () => { pref = card.classList.contains('collapsed') ? 'open' : 'closed'; write(key, pref); set(pref === 'closed'); };
    const record = { card, set, open, defaults(populated) { if (pref) set(pref === 'closed'); else set(welcome || (side === 'library' ? populated && !libraryDefaultOpen : card.parentElement === view && view.clientWidth < 560)); } };
    cards.push(record); return record;
  }
  const libraryCard = convert(library, 'library'), settingsCard = convert(settings, 'settings');
  const mq = matchMedia('(max-width: 599px)'); let populated = false, embedded = false, welcome = false, directPreview = false;
  const defaults = () => cards.forEach(card => card.defaults(populated));
  const dockCards = () => { for (const { card } of cards) ((!directPreview && mq.matches) || embedded || (dockSettings && card === settingsCard?.card) ? dock : view).append(card); defaults(); };
  mq.addEventListener('change', dockCards); dockCards();
  const observer = new ResizeObserver(defaults); observer.observe(view);
  return {
    setDirectPreview(value) { if (directPreview === value) return; directPreview = value; dockCards(); },
    setPopulated(value) { populated = value; defaults(); },
    setWelcome(value) { if (welcome === value) return; welcome = value; defaults(); setRail(value); },
    setEmbedded(value) { embedded = value; root.classList.toggle('v04-embedded', value); dockCards(); setRail(value); },
    reveal(element) {
      if (rail.contains(element)) setRail(false);
      cards.find(({ card }) => card.contains(element))?.open();
      for (let node = element; node && node !== root; node = node.parentElement) if (node.tagName === 'DETAILS') node.open = true;
    },
    openLibrary() { libraryCard?.open(); },
    dispose() { observer.disconnect(); mq.removeEventListener('change', dockCards); },
  };
}
