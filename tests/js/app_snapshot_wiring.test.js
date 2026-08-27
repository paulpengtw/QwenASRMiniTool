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
