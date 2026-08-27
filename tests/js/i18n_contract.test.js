"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../..");
const appSource = fs.readFileSync(path.join(ROOT, "webview/js/app.js"), "utf8");
const i18nSource = fs.readFileSync(path.join(ROOT, "webview/js/i18n.js"), "utf8");

function extractAppTranslationKeys(source) {
  return [...source.matchAll(/\bT\(\s*["']([^"']+)["']\s*,/g)].map(match => match[1]);
}

function extractDictionaryEntries(source) {
  const entries = new Map();
  for (const match of source.matchAll(/^\s*["']([^"']+)["']\s*:\s*\[(.*)\],?\s*$/gm)) {
    const values = [...match[2].matchAll(/"(?:\\.|[^"\\])*"/g)].map(value => value[0]);
    entries.set(match[1], values);
  }
  return entries;
}

test("every literal app T key has an entry in the i18n dictionary", () => {
  const appKeys = extractAppTranslationKeys(appSource);
  const dictionary = extractDictionaryEntries(i18nSource);
  const uniqueAppKeys = [...new Set(appKeys)];
  const missing = uniqueAppKeys.filter(key => !dictionary.has(key));
  const incomplete = uniqueAppKeys.filter(key => {
    const values = dictionary.get(key);
    return values && values.length !== 3;
  });

  assert.ok(appKeys.length > 0, "app.js must contain literal T() calls");
  assert.deepEqual(missing, [], "app.js has translation keys missing from i18n.js");
  assert.deepEqual(incomplete, [], "app.js keys must have zh-TW, zh-CN, and en values");
});
