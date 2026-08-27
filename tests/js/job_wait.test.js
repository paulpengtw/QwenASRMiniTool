"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");

// job_wait.js is not yet created; these tests drive its creation.
const JobWait = require("../../webview/js/job_wait.js");
const { decide, extractProgress } = JobWait;

// ---------------------------------------------------------------------------
// decide()
// ---------------------------------------------------------------------------

test("decide returns continue for queued state", () => {
  const d = decide({ job_id: "j1", state: "queued", segments: [], saved_paths: [] });
  assert.equal(d.action, "continue");
});

test("decide returns continue for running state", () => {
  const d = decide({ job_id: "j1", state: "running", segments: [], saved_paths: [] });
  assert.equal(d.action, "continue");
});

test("decide returns continue for capturing state", () => {
  const d = decide({ job_id: "j1", state: "capturing", segments: [], saved_paths: [] });
  assert.equal(d.action, "continue");
});

test("decide returns continue for null input", () => {
  const d = decide(null);
  assert.equal(d.action, "continue");
});

test("decide returns continue for job with no state", () => {
  const d = decide({ job_id: "j1" });
  assert.equal(d.action, "continue");
});

test("decide returns resolve for completed state", () => {
  const job = {
    job_id: "j2",
    state: "completed",
    segments: [{ start: 0, end: 1, text: "hello" }],
    saved_paths: ["/out/sub.srt"],
  };
  const d = decide(job);
  assert.equal(d.action, "resolve");
  assert.equal(d.result.job_id, "j2");
  assert.equal(d.result.state, "completed");
  assert.equal(d.result.segments.length, 1);
  assert.equal(d.result.srtPath, "/out/sub.srt");
});

test("decide uses last saved_path as srtPath", () => {
  const job = {
    job_id: "j2",
    state: "completed",
    segments: [],
    saved_paths: ["/out/a.srt", "/out/b.srt"],
  };
  const d = decide(job);
  assert.equal(d.result.srtPath, "/out/b.srt");
});

test("decide sets srtPath null when no saved_paths", () => {
  const job = {
    job_id: "j2",
    state: "completed",
    segments: [],
    saved_paths: [],
  };
  const d = decide(job);
  assert.equal(d.result.srtPath, null);
});

test("decide returns resolve for cancelled state with partial segments", () => {
  const job = {
    job_id: "j3",
    state: "cancelled",
    segments: [{ start: 0, end: 1, text: "partial" }],
    saved_paths: [],
  };
  const d = decide(job);
  assert.equal(d.action, "resolve");
  assert.equal(d.result.state, "cancelled");
  assert.equal(d.result.segments.length, 1);
  assert.equal(d.result.segments[0].text, "partial");
  assert.equal(d.result.srtPath, null);
});

test("decide returns reject for failed state", () => {
  const job = {
    job_id: "j4",
    state: "failed",
    segments: [],
    saved_paths: [],
    error: "Engine exploded",
  };
  const d = decide(job);
  assert.equal(d.action, "reject");
  assert.ok(d.error instanceof Error);
  assert.equal(d.error.message, "Engine exploded");
});

test("decide preserves the message from a structured failed-job error", () => {
  const d = decide({
    job_id: "j4",
    state: "failed",
    segments: [],
    saved_paths: [],
    error: {
      code: "VIDEO_NEEDS_FFMPEG",
      params: { filename: "clip.mp4" },
      message: "Install ffmpeg to transcribe this video.",
    },
  });
  assert.equal(d.action, "reject");
  assert.equal(d.error.message, "Install ffmpeg to transcribe this video.");
});

test("decide reject uses generic message when error field is null", () => {
  const job = {
    job_id: "j4",
    state: "failed",
    segments: [],
    saved_paths: [],
    error: null,
  };
  const d = decide(job);
  assert.equal(d.action, "reject");
  assert.ok(d.error instanceof Error);
  assert.ok(d.error.message.length > 0);
});

// ---------------------------------------------------------------------------
// extractProgress()
// ---------------------------------------------------------------------------

test("extractProgress returns null for null input", () => {
  assert.equal(extractProgress(null), null);
});

test("extractProgress returns null when progress is missing", () => {
  assert.equal(extractProgress({ job_id: "j1" }), null);
});

test("extractProgress returns null when done is null", () => {
  const job = { progress: { done: null, total: 100, message: "working" } };
  assert.equal(extractProgress(job), null);
});

test("extractProgress returns null when total is zero", () => {
  const job = { progress: { done: 0, total: 0, message: "" } };
  assert.equal(extractProgress(job), null);
});

test("extractProgress computes pct correctly", () => {
  const job = { progress: { done: 50, total: 100, message: "working" } };
  const p = extractProgress(job);
  assert.equal(p.pct, 50);
  assert.equal(p.status, "working");
});

test("extractProgress rounds pct", () => {
  const job = { progress: { done: 1, total: 3, message: "" } };
  const p = extractProgress(job);
  assert.equal(p.pct, 33);
});

test("extractProgress returns empty string status when message is null", () => {
  const job = { progress: { done: 10, total: 100, message: null } };
  const p = extractProgress(job);
  assert.equal(p.status, "");
});
