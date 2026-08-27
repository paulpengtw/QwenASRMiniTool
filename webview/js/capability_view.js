/**
 * capability_view.js — Pure JS helpers for rendering capability snapshot.
 *
 * This module contains ONLY pure functions (no DOM, no fetch, no globals).
 * It is tested by tests/js/capability_view.test.js with node --test.
 *
 * Exports (CommonJS for node --test compatibility):
 *   controlStateForEntry(entry)         -> control state string
 *   shouldShowEntry(entry)              -> bool
 *   isEntryDisabled(entry)              -> bool
 *   mapCapabilityToI18nKey(key, entry)  -> i18n key suffix
 *   renderCode(code, params, codesTable, lang) -> string
 *   resolveDisplayLang(uiLang)          -> "en" | "zh"
 */

"use strict";

/**
 * Return the control state for a single capability entry.
 *
 * States returned:
 *   "ready"               — fully available
 *   "setup_required"      — selectable; shows download/install action
 *   "machine_unavailable" — visible but disabled with reason + remedy
 *   "platform_unsupported"— not shown in main selectors (hidden / collapsed section)
 *
 * @param {Object} entry  capability_entry from the snapshot
 * @returns {string}
 */
function controlStateForEntry(entry) {
  if (!entry || typeof entry !== "object") return "platform_unsupported";
  const s = entry.state;
  if (s === "ready") return "ready";
  if (s === "setup_required") return "setup_required";
  if (s === "machine_unavailable") return "machine_unavailable";
  // platform_unsupported and any unknown value
  return "platform_unsupported";
}

/**
 * Whether to show this entry in the main selector UI at all.
 * platform_unsupported items are hidden from main selectors.
 *
 * @param {Object} entry
 * @returns {boolean}
 */
function shouldShowEntry(entry) {
  return controlStateForEntry(entry) !== "platform_unsupported";
}

/**
 * Whether the control for this entry should be rendered as disabled.
 *
 * machine_unavailable entries are visible but disabled.
 * setup_required entries are selectable (not disabled), with a download action.
 *
 * @param {Object} entry
 * @returns {boolean}
 */
function isEntryDisabled(entry) {
  return controlStateForEntry(entry) === "machine_unavailable";
}

/**
 * Map a feature / backend key + entry to an i18n suffix for status text.
 *
 * @param {string} key     e.g. "ffmpeg", "openvino_cpu"
 * @param {Object} entry
 * @returns {string}       e.g. "ready", "setup_required", "machine_unavailable", "platform_unsupported"
 */
function mapCapabilityToI18nKey(key, entry) {
  return controlStateForEntry(entry);
}

/**
 * Resolve a uiLang setting value to the two-bucket display language used by
 * the capability codes table ("en" or "zh").
 *
 * zh-TW, zh-CN, 繁體中文, 简体中文, 簡體中文 -> "zh"
 * Everything else (including "English", "en") -> "en"
 *
 * @param {string} uiLang
 * @returns {"en"|"zh"}
 */
function resolveDisplayLang(uiLang) {
  if (!uiLang) return "en";
  const lower = String(uiLang).toLowerCase();
  if (
    lower.startsWith("zh") ||
    lower.includes("繁體") ||
    lower.includes("简体") ||
    lower.includes("簡體")
  ) {
    return "zh";
  }
  return "en";
}

/**
 * Render a capability code from the /api/message-codes table.
 *
 * Falls back to the code string itself if the code is unknown.
 * Substitutes {param} placeholders from `params`.
 *
 * @param {string} code        e.g. "FFMPEG_MISSING"
 * @param {Object} params      e.g. {}
 * @param {Object} codesTable  the JSON from /api/message-codes
 * @param {string} lang        "en" | "zh"
 * @returns {string}
 */
function renderCode(code, params, codesTable, lang) {
  const entry = codesTable && codesTable[code];
  if (!entry) return String(code);
  const template = entry[lang] || entry["en"] || String(code);
  // Replace {key} placeholders
  return template.replace(/\{(\w+)\}/g, (_, key) => {
    const val = params && params[key];
    return val !== undefined ? String(val) : `{${key}}`;
  });
}

// CommonJS export for node --test
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    controlStateForEntry,
    shouldShowEntry,
    isEntryDisabled,
    mapCapabilityToI18nKey,
    renderCode,
    resolveDisplayLang,
  };
}
