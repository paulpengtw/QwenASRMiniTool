/**
 * alignment_view.test.js
 *
 * node --test tests/js/alignment_view.test.js
 *
 * Pure-logic tests: AlignmentView.fromStatus() returns the correct UI
 * variant descriptor from a backend alignment capability snapshot.
 */
"use strict";
const test   = require("node:test");
const assert = require("node:assert/strict");
const AlignmentView = require("../../webview/js/alignment_view.js");

// ---------------------------------------------------------------------------
// Platform-unsupported (Ubuntu / Linux): proportional
// ---------------------------------------------------------------------------

test("platform_unsupported: showChip true, showToggle false", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.equal(v.showChip,   true);
  assert.equal(v.showToggle, false);
});

test("platform_unsupported: chipLabel is non-empty", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.ok(v.chipLabel.length > 0, "chipLabel must not be empty");
  assert.ok(v.chipLabel.includes("比例估算"), "chipLabel should mention 比例估算");
});

test("platform_unsupported: chipTooltip explains Windows-only", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.ok(v.chipTooltip.length > 0, "chipTooltip must not be empty");
});

test("platform_unsupported: showBadge true (karaoke ≈ 估算 badge)", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.equal(v.showBadge, true);
});

test("platform_unsupported: chunkDisabled true with reason", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.equal(v.chunkDisabled, true);
  assert.ok(v.chunkReason.length > 0);
});

test("platform_unsupported: faInUnsupported true (collapsed group)", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.equal(v.faInUnsupported, true);
});

test("platform_unsupported: statusLine is stable non-empty string", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.ok(v.statusLine.length > 0);
  assert.ok(v.statusLine.includes("Ubuntu"));
});

test("platform_unsupported: method and state are reflected in descriptor", () => {
  const v = AlignmentView.fromStatus({
    method: "proportional",
    state:  "platform_unsupported",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.equal(v.method, "proportional");
  assert.equal(v.state,  "platform_unsupported");
});

// ---------------------------------------------------------------------------
// Windows / exact path: normal UI
// ---------------------------------------------------------------------------

test("exact/ready: showToggle true, showChip false (Windows path)", () => {
  const v = AlignmentView.fromStatus({
    method: "exact",
    state:  "ready",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.equal(v.showToggle,      true);
  assert.equal(v.showChip,        false);
  assert.equal(v.showBadge,       false);
  assert.equal(v.chunkDisabled,   false);
  assert.equal(v.faInUnsupported, false);
  assert.equal(v.statusLine,      "");
});

test("exact/ready: method and state reflected", () => {
  const v = AlignmentView.fromStatus({
    method: "exact",
    state:  "ready",
    reason: { code: "ALIGN_WINDOWS_ONLY", params: {} },
  });
  assert.equal(v.method, "exact");
  assert.equal(v.state,  "ready");
});

// ---------------------------------------------------------------------------
// Defensive: null / undefined input
// ---------------------------------------------------------------------------

test("null alignment input: defaults to proportional unsupported UI", () => {
  const v = AlignmentView.fromStatus(null);
  // Null alignment should produce the same as platform_unsupported (default state)
  assert.equal(v.showChip,   true);
  assert.equal(v.showToggle, false);
});

test("missing alignment input: does not throw", () => {
  assert.doesNotThrow(() => AlignmentView.fromStatus(undefined));
  assert.doesNotThrow(() => AlignmentView.fromStatus({}));
});
