import assert from "node:assert/strict";
import test from "node:test";
import { t, getLocale, setLocale, onLocaleChange, availableLocales, formatNumber } from "../studio/web/i18n.js";
import zhCN from "../studio/web/locales/zh-CN.js";
import en from "../studio/web/locales/en.js";

test("default locale under plain Node (no window/document/navigator/localStorage) is zh-CN", () => {
  // This module has already been imported once at the top of this file, before
  // any setLocale() call anywhere in the process — so the value observed here
  // is exactly what a fresh import resolves to under Node.
  assert.equal(getLocale(), "zh-CN");
});

test("t() never throws and degrades to the raw key for a totally unknown key", () => {
  assert.doesNotThrow(() => t("this.key.does.not.exist"));
  assert.equal(t("this.key.does.not.exist"), "this.key.does.not.exist");
  assert.doesNotThrow(() => t());
  assert.doesNotThrow(() => t(null));
  assert.doesNotThrow(() => t(123));
});

test("t() fallback chain: active locale -> zh-CN -> the key itself", () => {
  const key = "common.close";
  assert.ok(Object.hasOwn(zhCN, key) && Object.hasOwn(en, key), "fixture key must exist in both tables");
  setLocale("en");
  try {
    assert.equal(t(key), en[key]);
    // Simulate "en" missing a key it hasn't been translated for yet: mutate the
    // live locale object (not the file on disk) and restore it afterwards.
    const original = en[key];
    delete en[key];
    try {
      assert.equal(t(key), zhCN[key]);
    } finally {
      en[key] = original;
    }
    assert.equal(t("this.key.does.not.exist"), "this.key.does.not.exist");
  } finally {
    setLocale("zh-CN");
  }
});

test("t() substitutes {name}-style placeholders and leaves unknown placeholders untouched", () => {
  assert.equal(t("metrics.mean", { value: "5" }), "均值 5");
  assert.equal(t("recipes.groupTitle", { label: "现在能用", count: 3 }), "现在能用（3）");
  // No params object at all: template returned verbatim (no placeholders to fill).
  assert.equal(t("common.close"), "关闭");
});

test("setLocale() normalises any input to a supported locale and getLocale() reflects it", () => {
  try {
    assert.equal(setLocale("zh"), "zh-CN");
    assert.equal(getLocale(), "zh-CN");
    assert.equal(setLocale("zh-TW"), "zh-CN");
    assert.equal(setLocale("zh_HK"), "zh-CN");
    assert.equal(setLocale("en-US"), "en");
    assert.equal(getLocale(), "en");
    assert.equal(setLocale("fr"), "en");
    assert.equal(setLocale(undefined), "en");
    assert.equal(setLocale(""), "en");
  } finally {
    setLocale("zh-CN");
  }
});

test("onLocaleChange fires on every actual switch and the returned unsubscribe stops delivery", () => {
  const seen = [];
  const unsubscribe = onLocaleChange((locale) => seen.push(locale));
  try {
    setLocale("en");
    setLocale("en"); // no-op: same locale, must not notify again
    assert.deepEqual(seen, ["en"]);
    unsubscribe();
    setLocale("zh-CN");
    assert.deepEqual(seen, ["en"]); // unchanged after unsubscribing
  } finally {
    setLocale("zh-CN");
  }
});

test("onLocaleChange with a non-function callback returns a harmless no-op unsubscribe", () => {
  const unsubscribe = onLocaleChange(null);
  assert.equal(typeof unsubscribe, "function");
  assert.doesNotThrow(() => unsubscribe());
});

test("availableLocales lists exactly the two supported locales", () => {
  assert.deepEqual(availableLocales().sort(), ["en", "zh-CN"]);
});

test("formatNumber never throws and degrades to a plain string on bad input", () => {
  assert.doesNotThrow(() => formatNumber(1234.5));
  assert.equal(formatNumber(Symbol("x")), "Symbol(x)");
});

test("locale files have the exact same key set and no empty values", () => {
  const zhKeys = Object.keys(zhCN).sort();
  const enKeys = Object.keys(en).sort();
  assert.deepEqual(enKeys, zhKeys, "en.js and zh-CN.js must define the same set of keys");
  for (const key of zhKeys) {
    assert.equal(typeof zhCN[key], "string", `zh-CN.${key} must be a string`);
    assert.notEqual(zhCN[key], "", `zh-CN.${key} must not be empty`);
    assert.equal(typeof en[key], "string", `en.${key} must be a string`);
    assert.notEqual(en[key], "", `en.${key} must not be empty`);
  }
});
