"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const bridgeSource = fs.readFileSync(path.join(ROOT, "webview/js/bridge.js"), "utf8");
const JobWait = require("../../webview/js/job_wait.js");

function loadBridge(fetchImpl) {
  let eventSource = null;

  const schedule = (fn, delay) => {
    const timer = setTimeout(fn, delay);
    timer.unref?.();
    return timer;
  };
  const scheduleInterval = (fn, delay) => {
    const timer = setInterval(fn, delay);
    timer.unref?.();
    return timer;
  };

  class FakeEventSource {
    constructor() {
      eventSource = this;
      this.closed = false;
    }

    close() {
      this.closed = true;
    }
  }

  class FakeFormData {
    append() {}
  }

  const context = {
    window: { addEventListener() {} },
    document: { readyState: "complete" },
    location: { search: "" },
    EventSource: FakeEventSource,
    FormData: FakeFormData,
    URLSearchParams,
    AbortController,
    Promise,
    setTimeout: schedule,
    clearTimeout,
    setInterval: scheduleInterval,
    clearInterval,
    fetch: fetchImpl,
    console,
    JobWait,
  };
  vm.createContext(context);
  vm.runInContext(bridgeSource, context, { filename: "bridge.js" });
  return {
    api: context.window.QwenAPI,
    eventSource: () => eventSource,
    context,
  };
}

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

test("bridge emits canonical connection lifecycle events for app SessionState", async () => {
  const { api, eventSource } = loadBridge(async () => ({ ok: false, status: 503 }));
  await flush();

  let connected = 0;
  let reconnecting = 0;
  api.on("connected", () => { connected += 1; });
  api.on("reconnecting", () => { reconnecting += 1; });

  eventSource().onopen();
  await api.ready;
  assert.equal(connected, 1);

  eventSource().onerror();
  assert.equal(reconnecting, 1);
});

test("bridge emits canonical stopped lifecycle events with the shutdown reason", async () => {
  const { api, eventSource } = loadBridge(async () => ({ ok: false, status: 503 }));
  await flush();

  let stopped = null;
  api.on("stopped", payload => { stopped = payload; });
  eventSource().onmessage({
    data: JSON.stringify({ event: "stopping", payload: { reason: "signal" } }),
  });

  assert.deepEqual(JSON.parse(JSON.stringify(stopped)), { reason: "signal" });
});

test("bridge unwraps registry job events for app listeners", async () => {
  const { api, eventSource } = loadBridge(async () => ({ ok: false, status: 503 }));
  await flush();

  let finishedPayload = null;
  let progressPayload = null;
  api.on("finished", payload => { finishedPayload = payload; });
  api.on("progress", payload => { progressPayload = payload; });

  eventSource().onmessage({
    data: JSON.stringify({
      event: "job",
      payload: {
        event: "finished",
        payload: { job_id: "job-2", result: { ok: true } },
      },
    }),
  });
  eventSource().onmessage({
    data: JSON.stringify({
      event: "job",
      payload: {
        event: "progress",
        payload: { job_id: "job-2", done: 25, total: 100, message: "working" },
      },
    }),
  });

  assert.deepEqual(JSON.parse(JSON.stringify(finishedPayload)), {
    job_id: "job-2", result: { ok: true },
  });
  assert.deepEqual(JSON.parse(JSON.stringify(progressPayload)), {
    job_id: "job-2", done: 25, total: 100, message: "working",
    pct: 25, status: "working",
  });
});

test("bridge renders a structured failed-job error through the message-code table", async () => {
  const fetchImpl = async url => {
    if (url === "/api/transcribe") {
      return { ok: true, json: async () => ({ job_id: "job-1" }) };
    }
    if (url === "/api/jobs/job-1") {
      return {
        ok: true,
        json: async () => ({
          job_id: "job-1",
          state: "failed",
          error: {
            code: "BACKEND_PLATFORM_UNSUPPORTED",
            params: { backend: "crispasr" },
            message: "fallback message",
          },
        }),
      };
    }
    return { ok: false, status: 404 };
  };
  const { api, context } = loadBridge(fetchImpl);
  context.window.I18N = {
    renderCode: async (code, params) =>
      `${code}:${params.backend}:rendered`,
  };

  await assert.rejects(
    api.transcribe({ file: { name: "smoke.wav" } }),
    err => {
      assert.equal(err.message, "BACKEND_PLATFORM_UNSUPPORTED:crispasr:rendered");
      return true;
    },
  );
});

test("bridge renders a coded transcription HTTP refusal through the message-code table", async () => {
  const fetchImpl = async url => {
    if (url === "/api/transcribe") {
      return {
        ok: false,
        status: 409,
        json: async () => ({
          error: {
            code: "VIDEO_NEEDS_FFMPEG",
            params: { remedy: "sudo apt install ffmpeg" },
            message: "fallback message",
          },
        }),
      };
    }
    return { ok: false, status: 404 };
  };
  const { api, context } = loadBridge(fetchImpl);
  context.window.I18N = {
    renderCode: async (code, params) => `${code}:${params.remedy}:rendered`,
  };

  await assert.rejects(
    api.transcribe({ file: { name: "clip.mp4" } }),
    err => {
      assert.equal(err.message, "VIDEO_NEEDS_FFMPEG:sudo apt install ffmpeg:rendered");
      return true;
    },
  );
});

test("bridge gives the app a rendered message for a coded model refusal", async () => {
  const fetchImpl = async url => {
    if (url === "/api/model") {
      return {
        ok: true,
        json: async () => ({
          ok: false,
          error: {
            code: "BACKEND_PLATFORM_UNSUPPORTED",
            params: { backend: "crispasr" },
          },
        }),
      };
    }
    return { ok: false, status: 404 };
  };
  const { api, context } = loadBridge(fetchImpl);
  context.window.I18N = {
    renderCode: async (code, params) => `${code}:${params.backend}:rendered`,
  };

  const result = await api.setModel("crispasr", "small");
  assert.equal(result.message, "BACKEND_PLATFORM_UNSUPPORTED:crispasr:rendered");
});

test("bridge gives the app a rendered status for a coded tunnel refusal", async () => {
  const fetchImpl = async url => {
    if (url === "/api/tunnel") {
      return {
        ok: true,
        json: async () => ({
          ok: false,
          running: false,
          status: "",
          error: { code: "CLOUDFLARED_MISSING", params: {} },
        }),
      };
    }
    return { ok: false, status: 404 };
  };
  const { api, context } = loadBridge(fetchImpl);
  context.window.I18N = {
    renderCode: async code => `${code}:rendered`,
  };

  const result = await api.toggleTunnel(true);
  assert.equal(result.status, "CLOUDFLARED_MISSING:rendered");
});
