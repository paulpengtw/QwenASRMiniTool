/* ============================================================
   job_wait.js — pure state machine for waiting on a job to reach a
   terminal state.  Fed with job snapshot objects (from GET /api/jobs/<id>
   or derived from SSE "job" events); returns a decision object that tells
   the caller whether to continue waiting, resolve, or reject.

   UMD: works as a Node.js module (node --test) and as a browser global
   (window.JobWait).
   ============================================================ */
(function () {
  "use strict";

  var TERMINAL_RESOLVE = { completed: true, cancelled: true };
  var TERMINAL_REJECT  = { failed: true };

  /**
   * decide(job) — given a job snapshot dict, return a decision.
   *
   * Returns one of:
   *   { action: "continue" }
   *   { action: "resolve", result: { job_id, segments, srtPath, state } }
   *   { action: "reject",  error: Error }
   */
  function decide(job) {
    if (!job || !job.state) return { action: "continue" };

    var state = job.state;

    if (TERMINAL_REJECT[state]) {
      var msg = (job.error && String(job.error).length > 0)
        ? String(job.error)
        : "Transcription failed";
      return { action: "reject", error: new Error(msg) };
    }

    if (TERMINAL_RESOLVE[state]) {
      var paths = Array.isArray(job.saved_paths) ? job.saved_paths : [];
      var srtPath = paths.length > 0 ? paths[paths.length - 1] : null;
      return {
        action: "resolve",
        result: {
          job_id:   job.job_id,
          segments: Array.isArray(job.segments) ? job.segments : [],
          srtPath:  srtPath,
          state:    state,
        },
      };
    }

    return { action: "continue" };
  }

  /**
   * extractProgress(job) — extract progress info from a job snapshot.
   *
   * Returns { pct: number, status: string } or null if no useful progress.
   */
  function extractProgress(job) {
    if (!job || !job.progress) return null;
    var done  = job.progress.done;
    var total = job.progress.total;
    var msg   = job.progress.message;
    if (done == null || total == null || total === 0) return null;
    return {
      pct:    Math.round((done / total) * 100),
      status: msg != null ? String(msg) : "",
    };
  }

  var JobWait = { decide: decide, extractProgress: extractProgress };

  if (typeof module !== "undefined") module.exports = JobWait;
  else window.JobWait = JobWait;
})();
