// i18n.js — bilingual (zh-CN / en) runtime string lookup for the workbench UI.
// zh-CN is the source of truth; en is a faithful, developer-facing translation.
// See studio/web/locales/zh-CN.js for the string tables and how to add a key.
//
// This module must also load under plain Node (no window/document/navigator/
// localStorage) so it can be imported from node:test files; it defaults to
// zh-CN in that case and every browser touchpoint is feature-detected.

import zhCN from "./locales/zh-CN.js";
import en from "./locales/en.js";

const TABLES = { "zh-CN": zhCN, en };
const SUPPORTED = Object.freeze(Object.keys(TABLES));
const STORAGE_KEY = "studio.locale";

const hasWindow = typeof window !== "undefined";
const hasDocument = typeof document !== "undefined";
const hasNavigator = typeof navigator !== "undefined";
const hasLocalStorage = (() => {
  // In an opaque-origin iframe even evaluating the property can throw.
  try { return typeof localStorage !== "undefined"; } catch { return false; }
})();

// "zh", "zh-CN", "zh-Hans", "zh_TW", ... all normalise to "zh-CN"; anything
// else (including unset/garbage) normalises to "en". This function always
// returns one of SUPPORTED, so callers never need to validate its result.
function normalizeLocale(value) {
  const s = typeof value === "string" ? value.toLowerCase() : "";
  if (s === "zh" || s.startsWith("zh-") || s.startsWith("zh_")) return "zh-CN";
  return "en";
}

function readStoredLocale() {
  if (!hasLocalStorage) return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return typeof raw === "string" && raw ? raw : null;
  } catch (e) {
    return null;
  }
}

// The local server stamps its own default language (STUDIO_LANG, see
// studio/i18n.py) into <meta name="studio-language"> when it serves the page
// (browser page: studio/shell/server.py; MCP App: studio/shell/app_resources.py),
// so the install-time choice reaches the panel too. A stored preference (the
// toggle) still wins; ?mock=1 pages and Node have no such meta and fall through.
function readServerHint() {
  if (!hasDocument || typeof document.querySelector !== "function") return null;
  try {
    const meta = document.querySelector('meta[name="studio-language"]');
    const value = meta ? meta.getAttribute("content") : null;
    return typeof value === "string" && value.trim() ? value.trim() : null;
  } catch (e) {
    return null;
  }
}

function resolveInitialLocale() {
  const stored = readStoredLocale();
  if (stored) return normalizeLocale(stored);
  const hinted = readServerHint();
  if (hinted) return normalizeLocale(hinted);
  const nav = hasNavigator ? navigator.language || navigator.userLanguage : null;
  if (typeof nav === "string" && nav) return normalizeLocale(nav);
  return "zh-CN";
}

let current = resolveInitialLocale();
const listeners = new Set();

function applyDocumentLang() {
  if (hasDocument && document.documentElement) {
    document.documentElement.lang = current;
  }
}
applyDocumentLang();

export function availableLocales() {
  return SUPPORTED.slice();
}

export function getLocale() {
  return current;
}

export function setLocale(locale) {
  const next = normalizeLocale(locale);
  if (next === current) return current;
  current = next;
  applyDocumentLang();
  if (hasLocalStorage) {
    try {
      localStorage.setItem(STORAGE_KEY, current);
    } catch (e) {
      /* private-mode / quota errors are not fatal — locale still switches in memory */
    }
  }
  for (const cb of listeners) {
    try {
      cb(current);
    } catch (e) {
      /* a broken listener must not break the locale switch for everyone else */
    }
  }
  return current;
}

export function onLocaleChange(cb) {
  if (typeof cb !== "function") return () => {};
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function lookup(table, key) {
  if (!table || typeof key !== "string") return undefined;
  return Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined;
}

function interpolate(template, params) {
  if (!params || typeof template !== "string") return template;
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
  );
}

// Looks up `key` in the active locale, falls back to zh-CN, then to the key
// itself. Never throws — a lookup failure should degrade to visible text,
// not break rendering.
export function t(key, params) {
  try {
    let value = lookup(TABLES[current], key);
    if (value === undefined && current !== "zh-CN") value = lookup(TABLES["zh-CN"], key);
    if (value === undefined) value = key;
    return interpolate(value, params);
  } catch (e) {
    return typeof key === "string" ? key : "";
  }
}

export function formatNumber(n, opts) {
  try {
    return new Intl.NumberFormat(current, opts).format(n);
  } catch (e) {
    return String(n);
  }
}

export function formatDate(d, opts) {
  try {
    return new Intl.DateTimeFormat(current, opts).format(d);
  } catch (e) {
    return String(d);
  }
}

// Static markup hooks (studio/web/index.html, studio/app/index.html):
//   data-i18n="key"                          -> element.textContent = t(key)
//   data-i18n-attr="title=key aria-label=key2" -> setAttribute(name, t(key)) per pair
//   data-locale-toggle                       -> click switches zh-CN <-> en and reloads
// DOM built at run time in the JS modules calls t() directly instead. Runs once
// when the document is ready. Re-run it only on a newly injected subtree: several
// JS-owned elements (#plan-next-title, #busy-card-title, ...) also carry data-i18n
// as their pre-hydration default, and a document-wide re-run would reset their
// live text. Nothing here re-renders module-built DOM: the modules read t() at
// render time, so the toggle reloads the page rather than patching it in place.
// The toggle is hidden where localStorage cannot be written (a sandboxed iframe
// without same-origin storage): the choice could not survive the reload.
function storageWritable() {
  if (!hasLocalStorage) return false;
  try {
    localStorage.setItem(STORAGE_KEY + ".probe", "1");
    localStorage.removeItem(STORAGE_KEY + ".probe");
    return true;
  } catch (e) {
    return false;
  }
}

export function applyTranslations(root) {
  if (!hasDocument) return;
  const scope = root || document;
  try {
    for (const el of scope.querySelectorAll("[data-i18n]")) {
      const key = el.getAttribute("data-i18n");
      if (key) el.textContent = t(key);
    }
    for (const el of scope.querySelectorAll("[data-i18n-attr]")) {
      for (const pair of (el.getAttribute("data-i18n-attr") || "").split(/\s+/)) {
        const eq = pair.indexOf("=");
        if (eq > 0) el.setAttribute(pair.slice(0, eq), t(pair.slice(eq + 1)));
      }
    }
    for (const el of scope.querySelectorAll("[data-locale-toggle]")) {
      if (!storageWritable()) {
        el.hidden = true;
        continue;
      }
      if (el.dataset.localeToggleBound) continue;
      el.dataset.localeToggleBound = "1";
      el.addEventListener("click", () => {
        setLocale(current === "zh-CN" ? "en" : "zh-CN");
        if (hasWindow && window.location && typeof window.location.reload === "function") window.location.reload();
      });
    }
  } catch (e) {
    /* a broken hook must not break the page */
  }
}

if (hasDocument) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => applyTranslations(document), { once: true });
  } else {
    applyTranslations(document);
  }
}

if (hasWindow) {
  window.studioI18n = { t, setLocale, getLocale, applyTranslations };
}
