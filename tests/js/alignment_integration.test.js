/**
 * alignment_integration.test.js
 *
 * node --test tests/js/alignment_integration.test.js
 *
 * Structural integration tests: verify that alignment_view.js is wired
 * into index.html and app.js, and that the required DOM elements exist.
 *
 * These are file-content tests at the seam between alignment_view.js
 * (pure logic) and the HTML/JS host that must apply it.
 */
"use strict";
const test   = require("node:test");
const assert = require("node:assert/strict");
const fs     = require("node:fs");
const path   = require("node:path");

const WEBVIEW   = path.join(__dirname, "../../webview");
const HTML_PATH = path.join(WEBVIEW, "index.html");
const APP_PATH  = path.join(WEBVIEW, "js/app.js");

const html  = fs.readFileSync(HTML_PATH, "utf-8");
const appJs = fs.readFileSync(APP_PATH, "utf-8");

// ---------------------------------------------------------------------------
// 1. alignment_view.js must be loaded in index.html
// ---------------------------------------------------------------------------

test("index.html: alignment_view.js script tag is present", () => {
  const hasTag = html.includes('src="js/alignment_view.js"') ||
                 html.includes("src='js/alignment_view.js'");
  assert.ok(hasTag,
    "index.html must have a <script src=\"js/alignment_view.js\"> tag");
});

test("index.html: alignment_view.js is loaded before app.js", () => {
  const avPos  = html.indexOf("alignment_view.js");
  const appPos = html.indexOf("js/app.js");
  assert.ok(avPos  !== -1, "alignment_view.js must appear in index.html");
  assert.ok(appPos !== -1, "js/app.js must appear in index.html");
  assert.ok(avPos < appPos,
    "alignment_view.js must be loaded before app.js so window.AlignmentView is available");
});

// ---------------------------------------------------------------------------
// 2. app.js must reference AlignmentView
// ---------------------------------------------------------------------------

test("app.js: references AlignmentView.fromStatus", () => {
  assert.ok(appJs.includes("AlignmentView.fromStatus"),
    "app.js must call AlignmentView.fromStatus to derive the UI variant from status.alignment");
});

test("app.js: calls applyAlignmentDescriptor or equivalent after refreshStatus", () => {
  // The exact function name is an implementation detail; accept any of the likely names.
  const hasApply = appJs.includes("applyAlignmentDescriptor") ||
                   appJs.includes("applyAlignment") ||
                   appJs.includes("_applyAlignment");
  assert.ok(hasApply,
    "app.js must apply the AlignmentView descriptor to the DOM (function named applyAlignment* or similar)");
});

// ---------------------------------------------------------------------------
// 3. Required DOM elements in index.html
// ---------------------------------------------------------------------------

test("index.html: #align-chip element present for proportional read-only chip", () => {
  assert.ok(html.includes('id="align-chip"'),
    "index.html must contain an element with id='align-chip' " +
    "rendered when status.alignment.method === 'proportional'");
});

test("index.html: #align-badge element present for karaoke ≈ 估算 badge", () => {
  assert.ok(html.includes('id="align-badge"'),
    "index.html must contain an element with id='align-badge' " +
    "shown in the karaoke panel when faInUnsupported is true");
});

// ---------------------------------------------------------------------------
// 4. #gpu-diag must start hidden so crispasr.exe text is not shown to all platforms
// ---------------------------------------------------------------------------

test("index.html: #gpu-diag is initially hidden", () => {
  // Find the opening tag of #gpu-diag and check it carries the hidden attribute.
  const match = html.match(/<[^>]+id="gpu-diag"[^>]*>/);
  assert.ok(match, "#gpu-diag element must exist in index.html");
  assert.ok(match[0].includes("hidden"),
    "#gpu-diag must carry the 'hidden' attribute so the Windows-only " +
    "'crispasr.exe --diagnostics' text is not shown unconditionally on all platforms; " +
    "renderModel() populates it dynamically from listDevices().diag");
});

// ---------------------------------------------------------------------------
// 5. app.js: toggle logic toggles both #sw-align wrapper and #align-chip
// ---------------------------------------------------------------------------

test("app.js: references both align-chip and sw-align for toggle logic", () => {
  const hasAlignChip   = appJs.includes("align-chip");
  const hasSwAlign     = appJs.includes("sw-align");
  assert.ok(hasAlignChip,
    "app.js must reference #align-chip to show it on proportional platforms");
  assert.ok(hasSwAlign,
    "app.js must reference #sw-align to hide/show the normal toggle");
});
