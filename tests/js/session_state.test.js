const test = require("node:test");
const assert = require("node:assert/strict");
const SessionState = require("../../webview/js/session_state.js");

const { initialState, applySnapshot, applyEvent, reconnectBackoff } = SessionState;

// ---------------------------------------------------------------------------
// initialState
// ---------------------------------------------------------------------------

test("initialState returns connecting status", () => {
  const s = initialState();
  assert.equal(s.connection.status, "connecting");
  assert.equal(s.connection.reason, null);
  assert.equal(s.jobs.length, 0);
  assert.equal(s.status, null);
});

// ---------------------------------------------------------------------------
// applySnapshot
// ---------------------------------------------------------------------------

test("applySnapshot transitions connection to connected", () => {
  const s0 = initialState();
  const snap = { status: { model_ready: true }, jobs: { jobs: [] }, endpoint: null, tunnel: null };
  const s1 = applySnapshot(s0, snap);
  assert.equal(s1.connection.status, "connected");
});

test("applySnapshot populates jobs from snapshot.jobs.jobs", () => {
  const s0 = initialState();
  const snap = {
    status: { model_ready: true },
    jobs: {
      jobs: [
        { job_id: "j1", kind: "single", state: "completed", segments: [], notes: [], saved_paths: [] },
      ],
    },
    endpoint: null,
    tunnel: null,
  };
  const s1 = applySnapshot(s0, snap);
  assert.equal(s1.jobs.length, 1);
  assert.equal(s1.jobs[0].job_id, "j1");
  assert.equal(s1.jobs[0].state, "completed");
});

test("applySnapshot preserves previous state for missing fields", () => {
  const s0 = Object.assign(initialState(), {
    endpoint: { running: true },
    tunnel: { url: "https://t.example" },
  });
  const snap = { status: { model_ready: false }, jobs: { jobs: [] } };
  const s1 = applySnapshot(s0, snap);
  // endpoint and tunnel not in snap -> preserved from s0
  assert.deepEqual(s1.endpoint, { running: true });
  assert.deepEqual(s1.tunnel, { url: "https://t.example" });
});

test("applySnapshot overwrites endpoint when present", () => {
  const s0 = Object.assign(initialState(), { endpoint: { running: false } });
  const snap = {
    status: {},
    jobs: { jobs: [] },
    endpoint: { running: true, port: 11435 },
    tunnel: null,
  };
  const s1 = applySnapshot(s0, snap);
  assert.deepEqual(s1.endpoint, { running: true, port: 11435 });
});

test("applySnapshot with null is a no-op", () => {
  const s0 = initialState();
  const s1 = applySnapshot(s0, null);
  assert.equal(s1, s0);
});

// ---------------------------------------------------------------------------
// applyEvent — connection lifecycle
// ---------------------------------------------------------------------------

test("applyEvent reconnecting sets reconnecting status", () => {
  const s0 = applySnapshot(initialState(), { status: {}, jobs: { jobs: [] } });
  const s1 = applyEvent(s0, "reconnecting", { reason: "timeout" });
  assert.equal(s1.connection.status, "reconnecting");
  assert.equal(s1.connection.reason, "timeout");
});

test("applyEvent stopping sets stopped status with reason", () => {
  const s0 = applySnapshot(initialState(), { status: {}, jobs: { jobs: [] } });
  const s1 = applyEvent(s0, "stopping", { reason: "user-quit" });
  assert.equal(s1.connection.status, "stopped");
  assert.equal(s1.connection.reason, "user-quit");
});

test("applyEvent stopping with no payload uses default reason", () => {
  const s0 = applySnapshot(initialState(), { status: {}, jobs: { jobs: [] } });
  const s1 = applyEvent(s0, "stopping", null);
  assert.equal(s1.connection.status, "stopped");
  assert.equal(s1.connection.reason, "stopping");
});

test("applyEvent stopped sets stopped status", () => {
  const s0 = applySnapshot(initialState(), { status: {}, jobs: { jobs: [] } });
  const s1 = applyEvent(s0, "stopped", { reason: "signal" });
  assert.equal(s1.connection.status, "stopped");
  assert.equal(s1.connection.reason, "signal");
});

test("applyEvent connected clears reason", () => {
  const s0 = applyEvent(initialState(), "reconnecting", { reason: "timeout" });
  const s1 = applyEvent(s0, "connected", {});
  assert.equal(s1.connection.status, "connected");
  assert.equal(s1.connection.reason, null);
});

// ---------------------------------------------------------------------------
// applyEvent — status / tunnel
// ---------------------------------------------------------------------------

test("applyEvent status merges into existing status", () => {
  const s0 = applySnapshot(initialState(), { status: { model_ready: false, version: "1.0" }, jobs: { jobs: [] } });
  const s1 = applyEvent(s0, "status", { model_ready: true });
  assert.equal(s1.status.model_ready, true);
  assert.equal(s1.status.version, "1.0"); // preserved
});

test("applyEvent tunnel updates tunnel", () => {
  const s0 = applySnapshot(initialState(), { status: {}, jobs: { jobs: [] } });
  const s1 = applyEvent(s0, "tunnel", { running: true, url: "https://t.example" });
  assert.deepEqual(s1.tunnel, { running: true, url: "https://t.example" });
});

// ---------------------------------------------------------------------------
// applyEvent — job submitted
// ---------------------------------------------------------------------------

test("applyEvent submitted adds a new queued job placeholder", () => {
  const s0 = applySnapshot(initialState(), { status: {}, jobs: { jobs: [] } });
  const s1 = applyEvent(s0, "submitted", { job_id: "j1", kind: "single", lane: "inference" });
  assert.equal(s1.jobs.length, 1);
  assert.equal(s1.jobs[0].job_id, "j1");
  assert.equal(s1.jobs[0].state, "queued");
  assert.equal(s1.jobs[0].kind, "single");
});

test("applyEvent submitted does not duplicate existing job", () => {
  const snap = { status: {}, jobs: { jobs: [{ job_id: "j1", kind: "single", state: "queued", segments: [], notes: [], saved_paths: [] }] } };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "submitted", { job_id: "j1", kind: "single" });
  assert.equal(s1.jobs.length, 1);
});

// ---------------------------------------------------------------------------
// applyEvent — job transitions
// ---------------------------------------------------------------------------

test("applyEvent started transitions job to running", () => {
  const snap = { status: {}, jobs: { jobs: [{ job_id: "j1", kind: "single", state: "queued", segments: [], notes: [], saved_paths: [] }] } };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "started", { job_id: "j1" });
  assert.equal(s1.jobs[0].state, "running");
});

test("applyEvent finished transitions job to completed", () => {
  const snap = { status: {}, jobs: { jobs: [{ job_id: "j1", kind: "single", state: "running", segments: [], notes: [], saved_paths: [] }] } };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "finished", { job_id: "j1" });
  assert.equal(s1.jobs[0].state, "completed");
});

test("applyEvent failed transitions job to failed with error", () => {
  const snap = { status: {}, jobs: { jobs: [{ job_id: "j1", kind: "single", state: "running", segments: [], notes: [], saved_paths: [] }] } };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "failed", { job_id: "j1", error: "file not found" });
  assert.equal(s1.jobs[0].state, "failed");
  assert.equal(s1.jobs[0].error, "file not found");
});

test("applyEvent cancelled transitions job to cancelled", () => {
  const snap = { status: {}, jobs: { jobs: [{ job_id: "j1", kind: "single", state: "running", segments: [], notes: [], saved_paths: [] }] } };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "cancelled", { job_id: "j1" });
  assert.equal(s1.jobs[0].state, "cancelled");
});

test("applyEvent progress updates job progress fields", () => {
  const snap = {
    status: {},
    jobs: {
      jobs: [{
        job_id: "j1", kind: "single", state: "running",
        progress: { done: 0, total: 10, message: null },
        segments: [], notes: [], saved_paths: [],
      }],
    },
  };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "progress", { job_id: "j1", done: 3, total: 10, message: "transcribing" });
  assert.equal(s1.jobs[0].progress.done, 3);
  assert.equal(s1.jobs[0].progress.total, 10);
  assert.equal(s1.jobs[0].progress.message, "transcribing");
});

// ---------------------------------------------------------------------------
// applyEvent — segment edits and saves
// ---------------------------------------------------------------------------

test("applyEvent segment_edited updates text and sets edited flag", () => {
  const snap = {
    status: {},
    jobs: {
      jobs: [{
        job_id: "j1", kind: "single", state: "completed",
        segments: [
          { start: 0, end: 1, text: "hello", edited: false },
          { start: 1, end: 2, text: "world", edited: false },
        ],
        notes: [], saved_paths: [],
      }],
    },
  };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "segment_edited", { job_id: "j1", index: 1, text: "WORLD" });
  assert.equal(s1.jobs[0].segments[1].text, "WORLD");
  assert.equal(s1.jobs[0].segments[1].edited, true);
  // other segments unchanged
  assert.equal(s1.jobs[0].segments[0].text, "hello");
});

test("applyEvent path_saved appends to saved_paths", () => {
  const snap = {
    status: {},
    jobs: {
      jobs: [{ job_id: "j1", kind: "single", state: "completed", segments: [], notes: [], saved_paths: [] }],
    },
  };
  const s0 = applySnapshot(initialState(), snap);
  const s1 = applyEvent(s0, "path_saved", { job_id: "j1", path: "/out/sub.srt" });
  assert.deepEqual(s1.jobs[0].saved_paths, ["/out/sub.srt"]);
});

// ---------------------------------------------------------------------------
// reconnectBackoff — pure function schedule
// ---------------------------------------------------------------------------

test("reconnectBackoff attempt 0 returns 1000ms", () => {
  assert.equal(reconnectBackoff(0), 1000);
});

test("reconnectBackoff attempt 1 returns 2000ms", () => {
  assert.equal(reconnectBackoff(1), 2000);
});

test("reconnectBackoff attempt 2 returns 4000ms", () => {
  assert.equal(reconnectBackoff(2), 4000);
});

test("reconnectBackoff attempt 3 returns 8000ms", () => {
  assert.equal(reconnectBackoff(3), 8000);
});

test("reconnectBackoff attempt 4 is capped at 10000ms", () => {
  assert.equal(reconnectBackoff(4), 10000);
});

test("reconnectBackoff attempt 10 is still capped at 10000ms", () => {
  assert.equal(reconnectBackoff(10), 10000);
});

// ---------------------------------------------------------------------------
// Immutability: applyEvent does not mutate state
// ---------------------------------------------------------------------------

test("applyEvent does not mutate the original state", () => {
  const snap = {
    status: {},
    jobs: { jobs: [{ job_id: "j1", state: "queued", kind: "single", segments: [], notes: [], saved_paths: [] }] },
  };
  const s0 = applySnapshot(initialState(), snap);
  const frozen = Object.freeze(Object.assign({}, s0, { jobs: Object.freeze(s0.jobs.slice()) }));
  // Should not throw even if the state were frozen (we're not mutating it)
  const s1 = applyEvent(s0, "started", { job_id: "j1" });
  assert.equal(s0.jobs[0].state, "queued"); // original unchanged
  assert.equal(s1.jobs[0].state, "running");
});
