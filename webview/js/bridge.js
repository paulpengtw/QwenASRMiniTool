/* ============================================================
   bridge.js — 統一前端橋接層 window.QwenAPI
   Transport: web (loopback HTTP + SSE).  Mock mode has been hard-disabled
   (ticket 12): a lost server never shows fake data.
   ============================================================ */
(function () {
  "use strict";

  // ── event bus ───────────────────────────────────────────
  const listeners = {};
  function on(ev, fn) { (listeners[ev] ||= new Set()).add(fn); return () => off(ev, fn); }
  function off(ev, fn) { listeners[ev]?.delete(fn); }
  function emit(ev, payload) { listeners[ev]?.forEach(fn => { try { fn(payload); } catch (e) { console.error(e); } }); }

  // Mock mode has been hard-disabled.  The bridge always uses the real server.
  const MODE = "web";
  const KEY = new URLSearchParams(location.search).get("k") || "";

  // ── SSE reconnect with exponential backoff (1s, 2s, 4s, max 10s) ────────
  let _sseAttempt = 0;
  let _sseHealthRetries = 0;
  const MAX_HEALTH_RETRIES = 5;

  function _backoffMs(attempt) {
    return Math.min(1000 * Math.pow(2, attempt), 10000);
  }

  function _emitServerEvent(event, payload) {
    let normalized = payload;
    // Registry progress uses done/total/message; the legacy UI progress
    // listener consumes pct/status.  Carry both views in one event.
    if (event === "progress" && payload && payload.pct == null
        && payload.done != null && payload.total) {
      normalized = Object.assign({}, payload, {
        pct: Math.round((payload.done / payload.total) * 100),
        status: payload.message == null ? "" : String(payload.message),
      });
    }
    emit(event, normalized);
  }

  function connectSSE() {
    try {
      const es = new EventSource("/api/events" + (KEY ? "?k=" + encodeURIComponent(KEY) : ""));
      es.onopen = () => {
        _sseAttempt = 0;
        _sseHealthRetries = 0;
        emit("_bridge_connected", {});
        emit("connected", {});
        // Fetch snapshot on every SSE (re)connect
        _fetchSnapshot();
      };
      es.onmessage = e => {
        try {
          const m = JSON.parse(e.data);
          if (m && m.event === "job") {
            emit("job", m.payload);
            const inner = m.payload && m.payload.payload;
            const innerEvent = m.payload && m.payload.event;
            if (innerEvent) _emitServerEvent(innerEvent, inner);
          } else if (m && m.event) {
            _emitServerEvent(m.event, m.payload);
          }
          if (m && m.event === "stopping") {
            _handleStopped(m.payload && m.payload.reason ? m.payload.reason : "stopping");
          }
        } catch { /* keepalive/comment line, ignore */ }
      };
      es.onerror = () => {
        es.close();
        _scheduleReconnect();
      };
    } catch (e) {
      console.warn("[QwenAPI] SSE failed", e);
      _scheduleReconnect();
    }
  }

  function _scheduleReconnect() {
    const delay = _backoffMs(_sseAttempt);
    _sseAttempt++;
    emit("_bridge_reconnecting", { attempt: _sseAttempt, delayMs: delay });
    emit("reconnecting", { attempt: _sseAttempt, delayMs: delay });
    setTimeout(() => _healthThenReconnect(), delay);
  }

  function _healthThenReconnect() {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2000);
    fetch("/health" + (KEY ? "?k=" + encodeURIComponent(KEY) : ""),
      { signal: ctrl.signal, headers: authHeaders() })
      .then(r => {
        clearTimeout(t);
        if (r.ok) {
          _sseHealthRetries = 0;
          connectSSE();
        } else {
          _onHealthFail();
        }
      })
      .catch(() => {
        clearTimeout(t);
        _onHealthFail();
      });
  }

  function _onHealthFail() {
    _sseHealthRetries++;
    if (_sseHealthRetries >= MAX_HEALTH_RETRIES) {
      _handleStopped("crash");
    } else {
      // Keep trying; _scheduleReconnect will loop
      const delay = _backoffMs(_sseAttempt);
      _sseAttempt++;
      setTimeout(() => _healthThenReconnect(), delay);
    }
  }

  function _handleStopped(reason) {
    emit("_bridge_stopped", { reason });
    emit("stopped", { reason });
  }

  function _fetchSnapshot() {
    fetch(withKey("/api/snapshot"), { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(snap => { if (snap) emit("_bridge_snapshot", snap); })
      .catch(() => {});
  }

  const ready = new Promise(resolve => {
    function settle() {
      // No mock fallback — always connect to the real server
      connectSSE();
      resolve(MODE);
    }
    if (document.readyState === "complete") setTimeout(settle, 0);
    else window.addEventListener("load", () => setTimeout(settle, 0), { once: true });
  });

  // ── web：fetch 輔助 ─────────────────────────────────────
  function authHeaders(extra) {
    const h = Object.assign({}, extra || {});
    if (KEY) h["Authorization"] = "Bearer " + KEY;
    return h;
  }
  function withKey(path) { return KEY ? path + (path.includes("?") ? "&" : "?") + "k=" + encodeURIComponent(KEY) : path; }
  async function _renderError(error, fallback) {
    if (error && typeof error === "object") {
      if (error.code) {
        try {
          const rendered = await window.I18N?.renderCode(error.code, error.params || {});
          if (rendered && String(rendered) !== String(error.code)) return String(rendered);
        } catch {}
        return String(error.message || fallback || error.code);
      }
      if (error.message) return String(error.message);
    }
    if (error != null && String(error).length > 0) return String(error);
    return String(fallback || "Request failed");
  }
  async function apiGet(path) {
    const r = await fetch(withKey(path), { headers: authHeaders() });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }
  async function apiPost(path, body) {
    const r = await fetch(withKey(path), {
      method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      let msg = "HTTP " + r.status;
      try {
        const payload = await r.json();
        msg = await _renderError(payload.error, msg);
      } catch {}
      throw new Error(msg);
    }
    return r.json();
  }

  // ════════════════════════════════════════════════════════
  // 公開 API — always uses the real server (mock disabled)
  // 桌面獨有能力（pickFile）回 null → UI 改用 <input> fallback
  // ════════════════════════════════════════════════════════
  const api = {
    on, off, _emit: emit,
    get mode() { return MODE; },
    ready,

    async getStatus() { return apiGet("/api/status"); },

    async pickFile() { return null; },            // 瀏覽器環境一律用 <input type=file>
    async loadHintTxt() { return null; },

    // opts: {file, language, diarize, nSpeakers, align, hint}
    // Returns {job_id, ok} — progress arrives via SSE "progress" events
    async transcribe(opts) { return webTranscribe(opts); },

    async cancel() { try { await apiPost("/api/cancel", {}); } catch {} return true; },

    async openOutputDir() { try { await apiPost("/api/open-output", {}); } catch {} return true; },
    async checkUpdate() {
      try { return await apiPost("/api/check-update", {}); } catch {}
      return { ok: true };
    },

    async listDevices() { return apiGet("/api/devices"); },
    async setBackend(id) { return apiPost("/api/backend", { index: id }); },
    async getModelOptions() { return apiGet("/api/model-options"); },
    async getCapabilities() { return apiGet("/api/capabilities"); },
    async getMessageCodes() { return apiGet("/api/message-codes"); },
    async setModel(core, model) {
      const result = await apiPost("/api/model", { core, model });
      if (result?.error && !result.message) {
        result.message = await _renderError(result.error, result.message);
      }
      return result;
    },
    // 首次選定模型 → 就地下載並載入（進度走 SSE "progress"，完成走 "status"）
    async startLoad() { return apiPost("/api/load", {}); },
    async getLanguages() { return apiGet("/api/languages"); },
    async getHealthCheck() { return apiGet("/api/health-check"); },

    async getSettings() { return apiGet("/api/settings"); },
    async setSettings(patch) { return apiPost("/api/settings", patch); },

    async getEndpoint() { return apiGet("/api/endpoint"); },
    async toggleEndpoint(on_, port) { return apiPost("/api/endpoint", { action: on_ ? "start" : "stop", port }); },
    async regenKey() { return apiPost("/api/endpoint", { action: "regen" }); },

    // 對外臨時網址（Cloudflare）
    async getTunnel() { return apiGet("/api/tunnel"); },
    async toggleTunnel(on_) {
      const result = await apiPost("/api/tunnel", { action: on_ ? "start" : "stop" });
      if (result?.error && !result.status) {
        result.status = await _renderError(result.error, result.status);
      }
      return result;
    },

    qrSrc(data) {
      if (!data) return "";
      return withKey("/api/qr?d=" + encodeURIComponent(data));
    },

    async getBatch() {
      try { return await apiGet("/api/batch"); } catch { return { summary: { done: 0, total: 0 }, items: [] }; }
    },
    async addBatchFiles() { return this.getBatch(); },
    async runBatch() { return true; },

    // Job registry API
    async getSnapshot() { return apiGet("/api/snapshot"); },
    async cancelJob(jobId) { return apiPost(`/api/jobs/${jobId}/cancel`, {}); },
    async editSegment(jobId, idx, text) { return apiPost(`/api/jobs/${jobId}/segments/${idx}`, { text }); },
    async recordSaved(jobId, path) { return apiPost(`/api/jobs/${jobId}/saved`, { path }); },
  };

  // ── web 轉錄：POST /api/transcribe → wait for job terminal state ──
  // Resolves with {job_id, segments, srtPath, state} (backward-compatible).
  // Progress is forwarded to emit("progress", {pct, status}) as before.
  // Resolution mechanism: SSE "job" events trigger an immediate poll; a 1s
  // interval poll runs in parallel as a fallback so a missed SSE event can
  // never hang the UI.  failed → reject; cancelled → resolve with partial.
  async function webTranscribe(opts) {
    if (!opts.file) throw new Error("請先選擇檔案");
    const fd = new FormData();
    fd.append("file", opts.file, opts.file.name);
    if (opts.language) fd.append("language", opts.language);
    fd.append("align", opts.align ? "1" : "0");
    fd.append("diarize", opts.diarize ? "1" : "0");
    if (opts.nSpeakers && opts.nSpeakers !== "auto") fd.append("n_speakers", String(opts.nSpeakers));
    if (opts.hint) fd.append("hint", opts.hint);
    emit("progress", { pct: 3, status: "上傳中…" });
    const r = await fetch(withKey("/api/transcribe"), { method: "POST", body: fd, headers: authHeaders() });
    if (!r.ok) {
      let msg = "HTTP " + r.status;
      try {
        const payload = await r.json();
        msg = await _renderError(payload.error, msg);
      } catch {}
      throw new Error(msg);
    }
    const { job_id } = await r.json();
    return _waitForJob(job_id);
  }

  /**
   * _waitForJob(job_id) — polls GET /api/jobs/<id> every 1s; any incoming
   * SSE "job" event for this job_id triggers an immediate extra poll.
   * Returns a Promise<{job_id, segments, srtPath, state}>.
   */
  function _waitForJob(job_id) {
    // JobWait is loaded as a sibling script; gracefully degrade if missing.
    const JW = (typeof JobWait !== "undefined") ? JobWait : null;

    return new Promise(function (resolve, reject) {
      let done = false;
      let pollTimer = null;
      let offJob = null;

      function cleanup() {
        done = true;
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        if (offJob) { offJob(); offJob = null; }
      }

      function handleJobSnapshot(job) {
        if (done) return;
        if (!job || job.job_id !== job_id) return;

        // Forward progress (same contract as old code: emit("progress", {pct, status}))
        if (JW) {
          const prog = JW.extractProgress(job);
          if (prog) emit("progress", prog);
        }

        const dec = JW ? JW.decide(job) : _fallbackDecide(job);
        if (dec.action === "resolve") {
          cleanup();
          resolve(dec.result);
        } else if (dec.action === "reject") {
          cleanup();
          _renderError(job.error, dec.error?.message)
            .then(function (message) { reject(new Error(message)); })
            .catch(function () { reject(dec.error); });
        }
      }

      function pollNow() {
        if (done) return;
        apiGet("/api/jobs/" + job_id)
          .then(function (job) { handleJobSnapshot(job); })
          .catch(function () {}); // ignore; next interval will retry
      }

      // SSE "job" events: the server publishes {event: ev, payload: payload}
      // wrapped in the outer "job" event.  Any event for our job_id triggers
      // an immediate poll to get the full snapshot.
      offJob = on("job", function (payload) {
        if (!payload) return;
        const inner = payload.payload || {};
        if (inner.job_id === job_id) pollNow();
      });

      // 1 s interval fallback poll
      pollTimer = setInterval(pollNow, 1000);

      // Initial poll immediately after submission
      pollNow();
    });
  }

  /** Minimal fallback decide() used if job_wait.js is not loaded. */
  function _fallbackDecide(job) {
    const state = job && job.state;
    if (state === "failed") {
      const error = job && job.error;
      const message = error && typeof error === "object"
        ? (error.message || error.code || "Transcription failed")
        : (error || "Transcription failed");
      return { action: "reject", error: new Error(String(message)) };
    }
    if (state === "completed" || state === "cancelled") {
      const paths = Array.isArray(job.saved_paths) ? job.saved_paths : [];
      return {
        action: "resolve",
        result: {
          job_id: job.job_id,
          segments: Array.isArray(job.segments) ? job.segments : [],
          srtPath: paths.length ? paths[paths.length - 1] : null,
          state: state,
        },
      };
    }
    return { action: "continue" };
  }

  window.QwenAPI = api;
})();
