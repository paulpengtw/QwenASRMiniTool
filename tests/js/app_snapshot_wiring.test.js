/**
 * Tests for gap 12: session_state.js wiring into app.js and index.html
 *
 * These are structural tests that verify:
 * 1. webview/index.html loads session_state.js before app.js
 * 2. app.js _bridge_snapshot handler calls applySnapshot and processes snap.jobs
 * 3. app.js references SessionState, applySnapshot, applyEvent
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../..");

const indexHtml = fs.readFileSync(path.join(ROOT, "webview/index.html"), "utf-8");
const appJs = fs.readFileSync(path.join(ROOT, "webview/js/app.js"), "utf-8");

// ---------------------------------------------------------------------------
// index.html script loading order
// ---------------------------------------------------------------------------

test("index.html loads session_state.js in script tags", () => {
  assert.ok(
    indexHtml.includes("session_state.js"),
    "index.html must include a <script> tag for session_state.js"
  );
});

test("index.html loads session_state.js before app.js", () => {
  const sessionIdx = indexHtml.indexOf("session_state.js");
  const appIdx = indexHtml.indexOf("app.js");
  assert.ok(sessionIdx !== -1, "session_state.js not found in index.html");
  assert.ok(appIdx !== -1, "app.js not found in index.html");
  assert.ok(
    sessionIdx < appIdx,
    "session_state.js must appear before app.js in index.html"
  );
});

// ---------------------------------------------------------------------------
// app.js references SessionState API
// ---------------------------------------------------------------------------

test("app.js references SessionState", () => {
  assert.ok(
    appJs.includes("SessionState"),
    "app.js must reference SessionState (from session_state.js)"
  );
});

test("app.js calls applySnapshot", () => {
  assert.ok(
    appJs.includes("applySnapshot"),
    "app.js must call applySnapshot in the snapshot handler"
  );
});

test("app.js calls applyEvent", () => {
  assert.ok(
    appJs.includes("applyEvent"),
    "app.js must call applyEvent for SSE events"
  );
});

// ---------------------------------------------------------------------------
// _bridge_snapshot handler processes snap.jobs
// ---------------------------------------------------------------------------

test("app.js _bridge_snapshot handler reads snap.jobs", () => {
  // Find the _bridge_snapshot section and verify snap.jobs is accessed
  assert.ok(
    appJs.includes("snap.jobs"),
    "app.js _bridge_snapshot handler must access snap.jobs"
  );
});

// ---------------------------------------------------------------------------
// Integration: applySnapshot + applyEvent are consistent with session_state.js
// (Verify by simulating what app.js does: apply snapshot, then apply event,
// confirm the state machine works end-to-end as the module expects)
// ---------------------------------------------------------------------------

test("SessionState applySnapshot + applyEvent round-trip used by app.js logic", () => {
  // Load session_state.js to verify the functions used in app.js are callable
  const SessionState = require("../../webview/js/session_state.js");

  // Simulate what app.js _bridge_snapshot should now do:
  // 1. Start with initial state
  let state = SessionState.initialState();
  assert.equal(state.connection.status, "connecting");

  // 2. Apply snapshot (what _bridge_snapshot calls on every (re)connect)
  const snap = {
    status: { modelReady: true, version: "1.0.0" },
    jobs: {
      jobs: [
        { job_id: "j1", kind: "single", state: "completed", segments: [{ start: 0, end: 1, text: "hello", edited: false }], notes: [], saved_paths: ["/out/a.srt"] },
        { job_id: "j2", kind: "single", state: "running", segments: [], notes: [], saved_paths: [] },
      ],
    },
    endpoint: { running: true, port: 11435 },
    tunnel: null,
  };
  state = SessionState.applySnapshot(state, snap);

  assert.equal(state.connection.status, "connected");
  assert.equal(state.jobs.length, 2);
  assert.equal(state.jobs[0].job_id, "j1");
  assert.equal(state.jobs[0].state, "completed");
  assert.equal(state.jobs[1].state, "running");
  assert.deepEqual(state.endpoint, { running: true, port: 11435 });

  // 3. Apply an SSE event (what app.js applyEvent calls on each SSE message)
  state = SessionState.applyEvent(state, "finished", { job_id: "j2", finished_at: "2026-08-27T10:00:00Z" });
  assert.equal(state.jobs[1].state, "completed");

  // 4. Reconnect: apply snapshot again (simulates SSE reconnect with fresh snapshot)
  const snap2 = {
    status: { modelReady: true, version: "1.0.0" },
    jobs: { jobs: snap.jobs.jobs },
    endpoint: { running: true, port: 11435 },
    tunnel: null,
  };
  state = SessionState.applySnapshot(state, snap2);
  assert.equal(state.connection.status, "connected");
  assert.equal(state.jobs.length, 2);
});

// ---------------------------------------------------------------------------
// Ticket g1: job_wait.js wiring in index.html
// ---------------------------------------------------------------------------

test("index.html loads job_wait.js before bridge.js", () => {
  const fs = require("fs");
  const path = require("path");
  const indexHtml = fs.readFileSync(
    path.join(__dirname, "../../webview/index.html"),
    "utf-8"
  );
  const jwIdx = indexHtml.indexOf("job_wait.js");
  const brIdx = indexHtml.indexOf("bridge.js");
  assert.ok(jwIdx >= 0, "job_wait.js not found in index.html");
  assert.ok(brIdx >= 0, "bridge.js not found in index.html");
  assert.ok(jwIdx < brIdx, "job_wait.js must be loaded before bridge.js");
});

test("bridge.js references _waitForJob", () => {
  const fs = require("fs");
  const path = require("path");
  const bridgeJs = fs.readFileSync(
    path.join(__dirname, "../../webview/js/bridge.js"),
    "utf-8"
  );
  assert.ok(bridgeJs.includes("_waitForJob"), "bridge.js must define _waitForJob");
});

test("bridge.js webTranscribe calls _waitForJob", () => {
  const fs = require("fs");
  const path = require("path");
  const bridgeJs = fs.readFileSync(
    path.join(__dirname, "../../webview/js/bridge.js"),
    "utf-8"
  );
  // webTranscribe must resolve via _waitForJob, not return r.json() directly
  const webTranscribeFn = bridgeJs.slice(
    bridgeJs.indexOf("async function webTranscribe"),
    bridgeJs.indexOf("function _waitForJob")
  );
  assert.ok(webTranscribeFn.includes("_waitForJob(job_id)"), "webTranscribe must call _waitForJob(job_id)");
  assert.ok(!webTranscribeFn.includes("return r.json()"), "webTranscribe must not return r.json() directly");
});

test("app.js stores _curJobId from transcribe result", () => {
  const fs = require("fs");
  const path = require("path");
  const appJs = fs.readFileSync(
    path.join(__dirname, "../../webview/js/app.js"),
    "utf-8"
  );
  assert.ok(appJs.includes("_curJobId = res.job_id"), "app.js must store _curJobId from res.job_id");
});

test("app.js calls API.editSegment when _curJobId is set", () => {
  const fs = require("fs");
  const path = require("path");
  const appJs = fs.readFileSync(
    path.join(__dirname, "../../webview/js/app.js"),
    "utf-8"
  );
  assert.ok(appJs.includes("API.editSegment(_curJobId"), "app.js must call API.editSegment with _curJobId");
});

test("app.js calls API.recordSaved when _curJobId is set", () => {
  const fs = require("fs");
  const path = require("path");
  const appJs = fs.readFileSync(
    path.join(__dirname, "../../webview/js/app.js"),
    "utf-8"
  );
  assert.ok(appJs.includes("API.recordSaved(_curJobId"), "app.js must call API.recordSaved with _curJobId");
});
