// Guards the "no hard-coded Chinese in UI source" rule that the locale tables
// (studio/web/locales/*.js) exist for. Chinese is allowed in comments; every
// string a person can see must come from t() / data-i18n so the `en` locale is
// complete. mock.js is the ?mock=1 offline fixture (sample part names), not UI
// copy, and is skipped on purpose. The offline delivery template in
// scripts/build_delivery.mjs is not scanned either: its static text keeps
// Chinese defaults with data-i18n hooks, like index.html.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import zhCN from "../studio/web/locales/zh-CN.js";
import en from "../studio/web/locales/en.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// CJK ideographs plus CJK / full-width punctuation ("：", "、", "（"), which a
// hard-coded `${name}：${x}` would otherwise smuggle past the scan.
const CJK = /[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]/;
// A "\u6b63\u5728" escape is Chinese too.
const CJK_ESCAPE = /\\u(?:30[0-3][0-9a-f]|4[e-f][0-9a-f]{2}|[5-9][0-9a-f]{3}|ff[0-9a-e][0-9a-f])/i;
const SKIP_FILES = new Set(["mock.js"]);

function listFiles() {
  const out = [];
  for (const dir of ["studio/web", "studio/app"]) {
    for (const name of readdirSync(path.join(root, dir))) {
      if (SKIP_FILES.has(name) || !/\.(js|html|css)$/.test(name)) continue;
      out.push(path.join(dir, name));
    }
  }
  return out.sort();
}

// Blank out JS comments while keeping line structure. A small tokenizer walks
// strings, template literals (including `${ ... }` holes, which may nest
// further template literals) and regex literals, so a `//` inside a URL
// string, a quote inside a character class (/[<>"']/) or a `</span>` inside a
// nested template does not derail the scan.
const REGEX_PRECEDER = /[(,=:[!&|?{};+\-*%<>~^]$/;
function stripJsComments(src) {
  let out = "", i = 0;
  const stack = [{ type: "code", depth: 0 }];
  const ctx = () => stack[stack.length - 1];
  while (i < src.length) {
    const c = src[i], n = src[i + 1], top = ctx();
    if (top.type === "string") {
      out += c;
      if (c === "\\") { out += n ?? ""; i += 2; continue; }
      if (c === top.quote || c === "\n") stack.pop();
      i += 1;
      continue;
    }
    if (top.type === "template") {
      if (c === "\\") { out += c + (n ?? ""); i += 2; continue; }
      if (c === "`") { out += c; stack.pop(); i += 1; continue; }
      if (c === "$" && n === "{") { out += "${"; stack.push({ type: "code", depth: 0 }); i += 2; continue; }
      out += c;
      i += 1;
      continue;
    }
    // code
    if (c === "'" || c === '"') { stack.push({ type: "string", quote: c }); out += c; i += 1; continue; }
    if (c === "`") { stack.push({ type: "template" }); out += c; i += 1; continue; }
    if (c === "{") { top.depth += 1; out += c; i += 1; continue; }
    if (c === "}") {
      if (top.depth === 0 && stack.length > 1) stack.pop(); // end of a `${ ... }` hole
      else top.depth -= 1;
      out += c;
      i += 1;
      continue;
    }
    if (c === "/" && n !== "/" && n !== "*") {
      // Regex literal iff the previous significant character cannot end an operand.
      const prev = out.replace(/\s+$/, "");
      if (prev === "" || REGEX_PRECEDER.test(prev) || /\b(return|typeof|case|in|of)$/.test(prev)) {
        let j = i + 1, cls = false;
        for (; j < src.length && src[j] !== "\n"; j += 1) {
          if (src[j] === "\\") { j += 1; continue; }
          if (src[j] === "[") cls = true;
          else if (src[j] === "]") cls = false;
          else if (src[j] === "/" && !cls) break;
        }
        out += src.slice(i, j + 1);
        i = j + 1;
        continue;
      }
    }
    if (c === "/" && n === "/") { while (i < src.length && src[i] !== "\n") i += 1; continue; }
    if (c === "/" && n === "*") {
      const end = src.indexOf("*/", i + 2);
      const stop = end === -1 ? src.length : end + 2;
      out += src.slice(i, stop).replace(/[^\n]/g, " ");
      i = stop;
      continue;
    }
    out += c;
    i += 1;
  }
  return out;
}

// HTML: comments are blanked, and so is the text of an element that carries
// data-i18n (its static text is only the pre-hydration default; the key is
// what must exist) plus the attribute values that data-i18n-attr replaces.
function stripHtml(src) {
  return src
    .replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/(<[a-zA-Z][^>]*\sdata-i18n="[^"]*"[^>]*>)([^<]*)/g, (m, tag, text) => tag + text.replace(/[^\n]/g, " "))
    .replace(/<[a-zA-Z][^>]*\sdata-i18n-attr="([^"]*)"[^>]*>/g, (tag, spec) => {
      let out = tag;
      for (const pair of spec.split(/\s+/)) {
        const attr = pair.slice(0, pair.indexOf("="));
        if (attr) out = out.replace(new RegExp(`\\s${attr}="[^"]*"`), (a) => a.replace(/[^\n]/g, " "));
      }
      return out;
    });
}
const stripCssComments = (src) => src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));

function offenders(file) {
  const src = readFileSync(path.join(root, file), "utf8");
  const clean = file.endsWith(".js") ? stripJsComments(src) : file.endsWith(".html") ? stripHtml(src) : stripCssComments(src);
  return clean.split("\n").flatMap((line, i) => (CJK.test(line) || (file.endsWith(".js") && CJK_ESCAPE.test(line)) ? [`${file}:${i + 1}: ${line.trim().slice(0, 120)}`] : []));
}

test("no hard-coded Chinese outside comments in studio/web + studio/app sources (mock.js excepted)", () => {
  const found = listFiles().flatMap(offenders);
  assert.deepEqual(found, [], `hard-coded Chinese found; move it into the locale tables:\n${found.join("\n")}`);
});

// The language toggle names the language you switch TO in that language, so
// the English table legitimately says "中文" there.
const EN_CJK_ALLOWED = new Set(["nav.localeToggle"]);

test("the en locale table carries no Chinese (except the toggle's own label)", () => {
  const bad = Object.entries(en).filter(([k, v]) => CJK.test(v) && !EN_CJK_ALLOWED.has(k)).map(([k]) => k);
  assert.deepEqual(bad, []);
});

test("every literal key passed to t() or named by data-i18n exists in zh-CN", () => {
  const missing = new Set();
  for (const file of listFiles()) {
    const raw = readFileSync(path.join(root, file), "utf8");
    // Comments hold examples, not keys; a literal ending in "." is a dynamic
    // prefix (t("x." + kind)) whose members are covered by the table diff.
    const src = file.endsWith(".js") ? stripJsComments(raw) : file.endsWith(".html") ? raw.replace(/<!--[\s\S]*?-->/g, "") : "";
    for (const m of src.matchAll(/\bt\(\s*(["'])([A-Za-z0-9_.-]+)\1/g)) if (!m[2].endsWith(".") && !(m[2] in zhCN)) missing.add(`${file}: ${m[2]}`);
    for (const m of src.matchAll(/data-i18n="([^"]+)"/g)) if (!(m[1] in zhCN)) missing.add(`${file}: ${m[1]}`);
    for (const m of src.matchAll(/data-i18n-attr="([^"]+)"/g)) {
      for (const pair of m[1].split(/\s+/)) {
        const key = pair.slice(pair.indexOf("=") + 1);
        if (pair.indexOf("=") <= 0 || !(key in zhCN)) missing.add(`${file}: ${pair}`);
      }
    }
  }
  assert.deepEqual([...missing].sort(), []);
});

// zh "{wan} 万面" vs en "{k}k faces": the caller passes both, on purpose.
const PLACEHOLDER_EXEMPT = new Set(["panel.format.facesWan"]);
const placeholders = (v) => [...String(v).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");

test("every key uses the same {placeholders} in zh-CN and en", () => {
  const bad = Object.keys(zhCN).filter((k) => !PLACEHOLDER_EXEMPT.has(k) && placeholders(zhCN[k]) !== placeholders(en[k]));
  assert.deepEqual(bad, []);
});
