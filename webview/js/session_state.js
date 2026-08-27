/* ============================================================
   session_state.js — pure client-side state reducer for reconnectable sessions
   UMD module (like segments.js): exports SessionState.

   Connection states: connecting | connected | reconnecting | stopped

   applySnapshot(state, snapshot) — rebuild from server snapshot
   applyEvent(state, event, payload) — apply an SSE event to state
   ============================================================ */
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Initial state factory
  // ---------------------------------------------------------------------------

  function initialState() {
    return {
      connection: { status: "connecting", reason: null },
      status: null,          // server status object from snapshot
      jobs: [],              // ordered list of job snapshots
      endpoint: null,
      tunnel: null,
    };
  }

  // ---------------------------------------------------------------------------
  // applySnapshot(state, snapshot) -> new state
  // Rebuilds client state from a full server snapshot.
  // Called on load and on every SSE reconnect.
  // ---------------------------------------------------------------------------

  function applySnapshot(state, snapshot) {
    if (!snapshot || typeof snapshot !== "object") return state;
    return Object.assign({}, state, {
      connection: { status: "connected", reason: null },
      status: snapshot.status != null ? snapshot.status : state.status,
      jobs: Array.isArray((snapshot.jobs || {}).jobs)
        ? snapshot.jobs.jobs.slice()
        : (Array.isArray(snapshot.jobs) ? snapshot.jobs.slice() : state.jobs),
      endpoint: snapshot.endpoint != null ? snapshot.endpoint : state.endpoint,
      tunnel: snapshot.tunnel != null ? snapshot.tunnel : state.tunnel,
    });
  }

  // ---------------------------------------------------------------------------
  // applyEvent(state, event, payload) -> new state
  // Applies one SSE event to the existing client state.
  // ---------------------------------------------------------------------------

  function applyEvent(state, event, payload) {
    if (!event) return state;

    // ---- connection lifecycle ----
    if (event === "reconnecting") {
      return Object.assign({}, state, {
        connection: { status: "reconnecting", reason: (payload && payload.reason) || null },
      });
    }
    if (event === "connected") {
      return Object.assign({}, state, {
        connection: { status: "connected", reason: null },
      });
    }
    if (event === "stopping") {
      return Object.assign({}, state, {
        connection: {
          status: "stopped",
          reason: (payload && payload.reason) || "stopping",
        },
      });
    }
    if (event === "stopped") {
      return Object.assign({}, state, {
        connection: {
          status: "stopped",
          reason: (payload && payload.reason) || "stopped",
        },
      });
    }

    // ---- status / tunnel ----
    if (event === "status") {
      return Object.assign({}, state, {
        status: payload != null ? Object.assign({}, state.status, payload) : state.status,
      });
    }
    if (event === "tunnel") {
      return Object.assign({}, state, { tunnel: payload });
    }
    if (event === "endpoint") {
      return Object.assign({}, state, { endpoint: payload });
    }

    // ---- job events ----
    if (!payload || payload.job_id == null) return state;

    const jobId = payload.job_id;

    if (event === "submitted") {
      // A new job was submitted; optimistically create a placeholder.
      // The real data will arrive on next snapshot fetch.
      const existing = state.jobs.find(j => j.job_id === jobId);
      if (existing) return state;
      const newJob = {
        job_id: jobId,
        kind: payload.kind || "single",
        lane: payload.lane || "inference",
        state: "queued",
        client_id: payload.client_id || null,
        queued_at: payload.queued_at || null,
        started_at: null,
        finished_at: null,
        progress: { done: null, total: null, message: null },
        segments: [],
        result: null,
        error: null,
        notes: [],
        saved_paths: [],
      };
      return Object.assign({}, state, { jobs: state.jobs.concat(newJob) });
    }

    // All other job events require finding an existing job
    const idx = state.jobs.findIndex(j => j.job_id === jobId);
    if (idx === -1) return state;

    const job = state.jobs[idx];
    let updatedJob;

    if (event === "started") {
      updatedJob = Object.assign({}, job, {
        state: "running",
        started_at: payload.started_at || job.started_at,
      });
    } else if (event === "finished") {
      updatedJob = Object.assign({}, job, {
        state: "completed",
        finished_at: payload.finished_at || job.finished_at,
        result: payload.result !== undefined ? payload.result : job.result,
      });
    } else if (event === "failed") {
      updatedJob = Object.assign({}, job, {
        state: "failed",
        error: payload.error || job.error,
        finished_at: payload.finished_at || job.finished_at,
      });
    } else if (event === "cancelled") {
      updatedJob = Object.assign({}, job, {
        state: "cancelled",
        finished_at: payload.finished_at || job.finished_at,
      });
    } else if (event === "progress") {
      updatedJob = Object.assign({}, job, {
        progress: {
          done: payload.done !== undefined ? payload.done : job.progress.done,
          total: payload.total !== undefined ? payload.total : job.progress.total,
          message: payload.message !== undefined ? payload.message : job.progress.message,
        },
      });
    } else if (event === "segments_appended") {
      // Segments are appended; actual data comes from snapshot; here we just note the count
      updatedJob = Object.assign({}, job, {
        _pendingSegmentRefresh: true,
      });
    } else if (event === "segment_edited") {
      // Apply the edit optimistically
      const segs = job.segments.map((s, i) =>
        i === payload.index
          ? Object.assign({}, s, { text: payload.text, edited: true })
          : s
      );
      updatedJob = Object.assign({}, job, { segments: segs });
    } else if (event === "path_saved") {
      updatedJob = Object.assign({}, job, {
        saved_paths: job.saved_paths.concat(payload.path),
      });
    } else if (event === "note_added") {
      updatedJob = Object.assign({}, job, {
        notes: job.notes.concat(payload.note),
      });
    } else if (event === "item_started" || event === "item_finished" || event === "item_failed") {
      // Batch item state changes — update item in job.items
      if (!Array.isArray(job.items)) return state;
      const ii = payload.item_index;
      if (ii == null || ii < 0 || ii >= job.items.length) return state;
      const items = job.items.map((item, i) => {
        if (i !== ii) return item;
        if (event === "item_started") return Object.assign({}, item, { state: "running" });
        if (event === "item_finished") return Object.assign({}, item, { state: "completed", result: payload.result });
        if (event === "item_failed") return Object.assign({}, item, { state: "failed", error: payload.error });
        return item;
      });
      updatedJob = Object.assign({}, job, { items });
    } else {
      return state;
    }

    const jobs = state.jobs.slice();
    jobs[idx] = updatedJob;
    return Object.assign({}, state, { jobs });
  }

  // ---------------------------------------------------------------------------
  // reconnectBackoff(attempt) -> milliseconds
  // Pure function: 1s, 2s, 4s, capped at 10s.
  // attempt is 0-indexed (0 = first retry).
  // ---------------------------------------------------------------------------

  function reconnectBackoff(attempt) {
    const ms = 1000 * Math.pow(2, attempt);
    return Math.min(ms, 10000);
  }

  // ---------------------------------------------------------------------------
  // UMD export
  // ---------------------------------------------------------------------------

  const SessionState = { initialState, applySnapshot, applyEvent, reconnectBackoff };
  if (typeof module !== "undefined") module.exports = SessionState;
  else window.SessionState = SessionState;
})();
