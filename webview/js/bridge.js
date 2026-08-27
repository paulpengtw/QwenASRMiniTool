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

  function connectSSE() {
    try {
      const es = new EventSource("/api/events" + (KEY ? "?k=" + encodeURIComponent(KEY) : ""));
      es.onopen = () => {
        _sseAttempt = 0;
        _sseHealthRetries = 0;
        emit("_bridge_connected", {});
        // Fetch snapshot on every SSE (re)connect
        _fetchSnapshot();
      };
      es.onmessage = e => {
        try {
          const m = JSON.parse(e.data);
          if (m && m.event) emit(m.event, m.payload);
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
      try { msg = (await r.json()).error?.message || msg; } catch {}
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
    async setModel(core, model) { return apiPost("/api/model", { core, model }); },
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
    async toggleTunnel(on_) { return apiPost("/api/tunnel", { action: on_ ? "start" : "stop" }); },

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

  // ── web 轉錄：POST /api/transcribe（進度走 SSE job events）──
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
      try { msg = (await r.json()).error?.message || msg; } catch {}
      throw new Error(msg);
    }
    return r.json();   // {job_id, ok}
  }

  window.QwenAPI = api;
})();
