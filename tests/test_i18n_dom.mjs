// The DOM side of studio/web/i18n.js (server hint, resolve order, static
// markup hooks, language toggle) exercised against a minimal fake document.
// The module reads its environment at import time, so each scenario installs
// its globals first and imports a fresh copy through a cache-busting query.
import { test } from "node:test";
import assert from "node:assert/strict";

let n = 0;
function el(attrs = {}) {
  return {
    attrs: { ...attrs }, textContent: "", dataset: {}, hidden: false, listeners: {},
    getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    addEventListener(type, cb) { (this.listeners[type] ||= []).push(cb); },
    click() { for (const cb of this.listeners.click || []) cb(); },
  };
}
function fakeDocument({ meta, elements = [] }) {
  return {
    readyState: "complete", documentElement: { lang: "" },
    querySelector(sel) { return sel.includes("studio-language") && meta !== undefined ? el({ content: meta }) : null; },
    querySelectorAll(sel) { const attr = sel.slice(1, -1); return elements.filter((e) => attr in e.attrs); },
    addEventListener() {},
  };
}
function fakeStorage({ stored = null, writable = true } = {}) {
  const data = stored === null ? {} : { "studio.locale": stored };
  return {
    getItem(k) { return k in data ? data[k] : null; },
    setItem(k, v) { if (!writable) throw new Error("no storage"); data[k] = String(v); },
    removeItem(k) { delete data[k]; },
    data,
  };
}
async function load({ meta, stored, writable, navigatorLanguage = "zh-CN", elements } = {}) {
  const reloads = [];
  globalThis.document = fakeDocument({ meta, elements });
  globalThis.window = { location: { reload: () => reloads.push(1) } };
  globalThis.localStorage = fakeStorage({ stored, writable });
  globalThis.navigator = { language: navigatorLanguage };
  const mod = await import(`../studio/web/i18n.js?case=${++n}`);
  return { mod, reloads, storage: globalThis.localStorage };
}

test("a stored choice beats the server hint and the browser language", async () => {
  const { mod } = await load({ stored: "en", meta: "zh-CN", navigatorLanguage: "zh-CN" });
  assert.equal(mod.getLocale(), "en");
});

test("the server hint beats the browser language", async () => {
  const { mod } = await load({ meta: "en", navigatorLanguage: "zh-CN" });
  assert.equal(mod.getLocale(), "en");
  assert.equal(globalThis.document.documentElement.lang, "en");
});

test("an empty hint (STUDIO_LANG unset) falls through to the browser language", async () => {
  const { mod } = await load({ meta: "", navigatorLanguage: "zh-CN" });
  assert.equal(mod.getLocale(), "zh-CN");
  const en = await load({ meta: "", navigatorLanguage: "en-US" });
  assert.equal(en.mod.getLocale(), "en");
});

test("static markup hooks are applied once the document is ready", async () => {
  const title = el({ "data-i18n": "app.title" });
  const closeBtn = el({ "data-i18n-attr": "title=common.close aria-label=common.close" });
  const { mod } = await load({ meta: "en", elements: [title, closeBtn] });
  assert.equal(title.textContent, "3D Workbench");
  assert.equal(closeBtn.attrs.title, "Close");
  assert.equal(closeBtn.attrs["aria-label"], "Close");
  const later = el({ "data-i18n": "common.cancel" });
  mod.applyTranslations({ querySelectorAll: (sel) => (sel === "[data-i18n]" ? [later] : []) });
  assert.equal(later.textContent, "Cancel");
});

test("the toggle stores the other language and reloads; its label names the target", async () => {
  const toggle = el({ "data-locale-toggle": "", "data-i18n": "nav.localeToggle" });
  const { mod, reloads, storage } = await load({ meta: "en", elements: [toggle] });
  assert.equal(toggle.textContent, "中文");
  assert.equal(toggle.hidden, false);
  toggle.click();
  assert.equal(mod.getLocale(), "zh-CN");
  assert.equal(storage.data["studio.locale"], "zh-CN");
  assert.equal(reloads.length, 1);
});

test("the toggle is hidden where localStorage cannot be written", async () => {
  const toggle = el({ "data-locale-toggle": "", "data-i18n": "nav.localeToggle" });
  const { reloads } = await load({ meta: "en", writable: false, elements: [toggle] });
  assert.equal(toggle.hidden, true);
  toggle.click();
  assert.equal(reloads.length, 0);
});

test('sandboxed frames can throw on the localStorage getter itself', async () => {
  const toggle = el({ 'data-locale-toggle': '' });
  globalThis.document = fakeDocument({ meta: 'zh-CN', elements: [toggle] });
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('SecurityError'); } });
  try {
    const mod = await import(`../studio/web/i18n.js?sandbox=${++n}`);
    assert.equal(mod.getLocale(), 'zh-CN');
    assert.equal(toggle.hidden, true);
  } finally {
    if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor);
    else delete globalThis.localStorage;
  }
});
