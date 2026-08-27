/**
 * capability_view.test.js — node --test for pure JS capability control state logic.
 *
 * Tests the "which control state to render" mapping in capability_view.js.
 */

"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");

const {
  controlStateForEntry,
  shouldShowEntry,
  isEntryDisabled,
  mapCapabilityToI18nKey,
  renderCode,
  resolveDisplayLang,
  partitionBackendEntries,
} = require("../../webview/js/capability_view.js");

// ---------------------------------------------------------------------------
// controlStateForEntry
// ---------------------------------------------------------------------------

test("controlStateForEntry: ready entry returns 'ready'", () => {
  assert.equal(controlStateForEntry({ state: "ready" }), "ready");
});

test("controlStateForEntry: setup_required entry returns 'setup_required'", () => {
  assert.equal(controlStateForEntry({ state: "setup_required" }), "setup_required");
});

test("controlStateForEntry: machine_unavailable entry returns 'machine_unavailable'", () => {
  assert.equal(controlStateForEntry({ state: "machine_unavailable" }), "machine_unavailable");
});

test("controlStateForEntry: platform_unsupported entry returns 'platform_unsupported'", () => {
  assert.equal(controlStateForEntry({ state: "platform_unsupported" }), "platform_unsupported");
});

test("controlStateForEntry: unknown state defaults to platform_unsupported", () => {
  assert.equal(controlStateForEntry({ state: "totally_unknown" }), "platform_unsupported");
});

test("controlStateForEntry: null entry returns platform_unsupported", () => {
  assert.equal(controlStateForEntry(null), "platform_unsupported");
});

test("controlStateForEntry: undefined entry returns platform_unsupported", () => {
  assert.equal(controlStateForEntry(undefined), "platform_unsupported");
});

// ---------------------------------------------------------------------------
// shouldShowEntry
// ---------------------------------------------------------------------------

test("shouldShowEntry: ready entry is shown", () => {
  assert.equal(shouldShowEntry({ state: "ready" }), true);
});

test("shouldShowEntry: setup_required entry is shown", () => {
  assert.equal(shouldShowEntry({ state: "setup_required" }), true);
});

test("shouldShowEntry: machine_unavailable entry is shown", () => {
  assert.equal(shouldShowEntry({ state: "machine_unavailable" }), true);
});

test("shouldShowEntry: platform_unsupported entry is NOT shown", () => {
  assert.equal(shouldShowEntry({ state: "platform_unsupported" }), false);
});

test("shouldShowEntry: null entry is NOT shown", () => {
  assert.equal(shouldShowEntry(null), false);
});

// ---------------------------------------------------------------------------
// isEntryDisabled
// ---------------------------------------------------------------------------

test("isEntryDisabled: machine_unavailable is disabled", () => {
  assert.equal(isEntryDisabled({ state: "machine_unavailable" }), true);
});

test("isEntryDisabled: ready is NOT disabled", () => {
  assert.equal(isEntryDisabled({ state: "ready" }), false);
});

test("isEntryDisabled: setup_required is NOT disabled (selectable with download action)", () => {
  assert.equal(isEntryDisabled({ state: "setup_required" }), false);
});

test("isEntryDisabled: platform_unsupported is NOT disabled (it is hidden instead)", () => {
  assert.equal(isEntryDisabled({ state: "platform_unsupported" }), false);
});

// ---------------------------------------------------------------------------
// mapCapabilityToI18nKey
// ---------------------------------------------------------------------------

test("mapCapabilityToI18nKey: returns state as suffix", () => {
  assert.equal(mapCapabilityToI18nKey("ffmpeg", { state: "setup_required" }), "setup_required");
  assert.equal(mapCapabilityToI18nKey("openvino_cpu", { state: "ready" }), "ready");
});

// ---------------------------------------------------------------------------
// resolveDisplayLang
// ---------------------------------------------------------------------------

test("resolveDisplayLang: zh-TW maps to zh", () => {
  assert.equal(resolveDisplayLang("zh-TW"), "zh");
});

test("resolveDisplayLang: zh-CN maps to zh", () => {
  assert.equal(resolveDisplayLang("zh-CN"), "zh");
});

test("resolveDisplayLang: 繁體中文 maps to zh", () => {
  assert.equal(resolveDisplayLang("繁體中文"), "zh");
});

test("resolveDisplayLang: 简体中文 maps to zh", () => {
  assert.equal(resolveDisplayLang("简体中文"), "zh");
});

test("resolveDisplayLang: English maps to en", () => {
  assert.equal(resolveDisplayLang("English"), "en");
});

test("resolveDisplayLang: en maps to en", () => {
  assert.equal(resolveDisplayLang("en"), "en");
});

test("resolveDisplayLang: null maps to en", () => {
  assert.equal(resolveDisplayLang(null), "en");
});

test("resolveDisplayLang: empty string maps to en", () => {
  assert.equal(resolveDisplayLang(""), "en");
});

// ---------------------------------------------------------------------------
// renderCode
// ---------------------------------------------------------------------------

const SAMPLE_TABLE = {
  FFMPEG_MISSING: {
    en: "FFmpeg is not on PATH. Install it with: sudo apt install ffmpeg",
    zh: "FFmpeg 不在 PATH 中。請安裝：sudo apt install ffmpeg",
    severity: "degraded",
  },
  MODEL_MISSING: {
    en: "ASR model '{model}' is missing.",
    zh: "ASR 模型「{model}」缺失。",
    severity: "degraded",
  },
  BACKEND_PLATFORM_UNSUPPORTED: {
    en: "Backend '{backend}' is not supported on this platform.",
    zh: "後端「{backend}」在此平台上不受支援。",
    severity: "degraded",
  },
};

test("renderCode: renders English template", () => {
  const result = renderCode("FFMPEG_MISSING", {}, SAMPLE_TABLE, "en");
  assert.ok(result.includes("FFmpeg"), `Expected FFmpeg in: ${result}`);
});

test("renderCode: renders Chinese template", () => {
  const result = renderCode("FFMPEG_MISSING", {}, SAMPLE_TABLE, "zh");
  assert.ok(result.includes("FFmpeg"), `Expected FFmpeg in: ${result}`);
});

test("renderCode: substitutes params", () => {
  const result = renderCode("MODEL_MISSING", { model: "whisper-large" }, SAMPLE_TABLE, "en");
  assert.ok(result.includes("whisper-large"), `Expected model name in: ${result}`);
});

test("renderCode: zh with params", () => {
  const result = renderCode("MODEL_MISSING", { model: "my-model" }, SAMPLE_TABLE, "zh");
  assert.ok(result.includes("my-model"), `Expected model name in: ${result}`);
});

test("renderCode: backend substitution works", () => {
  const result = renderCode("BACKEND_PLATFORM_UNSUPPORTED", { backend: "crispasr" }, SAMPLE_TABLE, "en");
  assert.ok(result.includes("crispasr"), `Expected backend in: ${result}`);
});

test("renderCode: unknown code returns code itself", () => {
  const result = renderCode("TOTALLY_UNKNOWN_CODE", {}, SAMPLE_TABLE, "en");
  assert.equal(result, "TOTALLY_UNKNOWN_CODE");
});

test("renderCode: null codesTable returns code itself", () => {
  const result = renderCode("FFMPEG_MISSING", {}, null, "en");
  assert.equal(result, "FFMPEG_MISSING");
});

test("renderCode: missing param leaves placeholder", () => {
  const result = renderCode("MODEL_MISSING", {}, SAMPLE_TABLE, "en");
  // Should NOT throw; placeholder left as-is
  assert.ok(typeof result === "string");
  assert.ok(result.includes("{model}"), `Expected placeholder in: ${result}`);
});

// ---------------------------------------------------------------------------
// partitionBackendEntries — splits shown vs. unsupported backends
// ---------------------------------------------------------------------------

test("partitionBackendEntries: ready entry goes to shown", () => {
  const entries = { openvino_cpu: { state: "ready" } };
  const { shown, unsupported } = partitionBackendEntries(entries);
  assert.equal(shown.length, 1);
  assert.equal(shown[0].key, "openvino_cpu");
  assert.equal(unsupported.length, 0);
});

test("partitionBackendEntries: setup_required goes to shown", () => {
  const entries = { crispasr: { state: "setup_required" } };
  const { shown, unsupported } = partitionBackendEntries(entries);
  assert.equal(shown.length, 1);
  assert.equal(unsupported.length, 0);
});

test("partitionBackendEntries: machine_unavailable goes to shown (disabled)", () => {
  const entries = { cuda: { state: "machine_unavailable" } };
  const { shown, unsupported } = partitionBackendEntries(entries);
  assert.equal(shown.length, 1);
  assert.equal(shown[0].disabled, true);
  assert.equal(unsupported.length, 0);
});

test("partitionBackendEntries: platform_unsupported goes to unsupported list", () => {
  const entries = { crispasr: { state: "platform_unsupported" } };
  const { shown, unsupported } = partitionBackendEntries(entries);
  assert.equal(shown.length, 0);
  assert.equal(unsupported.length, 1);
  assert.equal(unsupported[0].key, "crispasr");
});

test("partitionBackendEntries: mixed entries split correctly", () => {
  const entries = {
    openvino_cpu: { state: "ready" },
    crispasr: { state: "platform_unsupported" },
    cuda: { state: "machine_unavailable" },
    chatllm_vulkan: { state: "platform_unsupported" },
  };
  const { shown, unsupported } = partitionBackendEntries(entries);
  assert.equal(shown.length, 2);
  assert.equal(unsupported.length, 2);
  const shownKeys = shown.map(e => e.key);
  assert.ok(shownKeys.includes("openvino_cpu"));
  assert.ok(shownKeys.includes("cuda"));
  const unsupKeys = unsupported.map(e => e.key);
  assert.ok(unsupKeys.includes("crispasr"));
  assert.ok(unsupKeys.includes("chatllm_vulkan"));
});

test("partitionBackendEntries: null or empty input returns empty lists", () => {
  const { shown, unsupported } = partitionBackendEntries(null);
  assert.equal(shown.length, 0);
  assert.equal(unsupported.length, 0);
  const r2 = partitionBackendEntries({});
  assert.equal(r2.shown.length, 0);
  assert.equal(r2.unsupported.length, 0);
});

test("partitionBackendEntries: each shown entry has key, state, disabled", () => {
  const entries = { openvino_cpu: { state: "ready", reason: null } };
  const { shown } = partitionBackendEntries(entries);
  assert.ok("key" in shown[0]);
  assert.ok("state" in shown[0]);
  assert.ok("disabled" in shown[0]);
  assert.equal(shown[0].disabled, false);
});
