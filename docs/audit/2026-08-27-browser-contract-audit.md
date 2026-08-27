# Browser-UI contract audit — 2026-08-27

Scope: the Ubuntu source-support browser path described by
`.scratch/ubuntu-implementation/README.md`, the resolved source-support
decisions, and `CONTEXT.md`.  The audit covers the `window.QwenAPI` bridge,
the loopback `WebViewServer`, the session-lifetime registry, the Ubuntu
launcher/shutdown path, and the browser assets.  Findings are concrete
producer/consumer mismatches only.

The audit used static source inspection plus executable contract tests.  The
pre-audit suites were 447 Python tests and 132 JavaScript tests.  The new
headless smoke test uses a port-0 server and a generated mono 16 kHz WAV; all
network operations have one-second request timeouts and the whole scenario has
a ten-second deadline.

## Findings summary

| ID | Severity | File:line evidence | Gap | Status |
|---|---|---|---|---|
| H-01 | high | `webview_server.py:214-237`, `webview_server.py:299-304` | Once the Ubuntu launcher had a session key, browser API GET/POST and SSE routes did not enforce it. | Fixed; `tests/test_webview_server_jobs.py::test_configured_webview_access_key_protects_api_routes` is green. |
| H-02 | high | `ubuntu_launcher.py:185-255`, `session_file.py:274-338` | Fresh/reused browser URLs and the fresh server did not share the persisted session key, and the real launcher did not install the coordinated Linux lifecycle. | Fixed; launcher tests cover keyed URLs, server fields, and lifecycle handoff. |
| H-03 | high | `shutdown.py:73-190`, `app_webview.py:469-486`, `webview_backend.py:1465-1479` | Shutdown had no running LAN endpoint/registry seam, so the endpoint listener could close without `stopping.set()` and `cancel_inflight()` first. | Fixed; endpoint fake records `stopping.set`, `cancel_inflight`, then listener close. |
| M-01 | medium | `webview_backend.py:1041-1049`, `webview_backend.py:1531-1541`, `webview/js/app.js:925-929`, `webview/js/app.js:1035-1037` | Coded model/tunnel refusals supplied only `error.code/params`, while consumers read top-level `message`/`status`. | Fixed; bridge renders coded values through `/api/message-codes` and supplies the fields consumed by the UI. |
| M-02 | medium | `webview_server.py:511-534`, `api_server.py:288-292`, `api_server.py:420-435` | Coded job failures were either stringified in the webview registry or left running on the endpoint exception/refusal paths; the browser therefore lost `{code, params, message}`. | Fixed; coded errors are normalized and endpoint jobs become terminal failed jobs. |
| M-03 | medium | `webview_server.py:147-148`, `webview/js/bridge.js:53-63`, `webview/js/app.js:1503-1513` | Registry updates were sent as an outer `job` envelope, but the app reducer listened for the inner event names; registry progress also used `done/total/message` while the legacy UI read `pct/status`. | Fixed; bridge preserves `job` for polling, unwraps inner events, and adds the UI progress aliases. |
| M-04 | medium | `webview/js/bridge.js:45-50`, `webview/js/bridge.js:79-84`, `webview/js/bridge.js:119-121`, `webview/js/app.js:1503-1518` | The app subscribed to canonical `connected`, `reconnecting`, and `stopped`, but the bridge originally emitted only private bridge event names. | Fixed; canonical lifecycle events are emitted with the shutdown/crash reason. |
| L-01 | low | `webview/js/app.js:166`, `webview/js/app.js:1451-1463`; `webview/js/i18n.js:1-128` | Six `T()` keys had no zh-TW/zh-CN/en table entry: `result.cancelled`, `stopped.crash`, `stopped.instructions`, `stopped.replaced`, `stopped.signal`, `stopped.userQuit`. | Fixed; all six entries were added and `tests/js/i18n_contract.test.js` now scans every literal app call. |
| L-02 | low | `webview/js/app.js:1503-1508`; `job_registry.py` subscriber events | `endpoint` and `note_added` were reducer listener names without a live publisher; `item_segments_appended` is published by the registry but deliberately omitted from the app listener list. | Fixed; endpoint is snapshot-only, recording closure publishes `note_added`, and live batch item lifecycle events retain their reducer listeners and payloads. |

All findings are fixed below; the low findings are included in the final
contract pass.

## 1. `window.QwenAPI` resolved-shape audit

The bridge is defined at `webview/js/bridge.js:186-258` and installs
`window.QwenAPI` at line 381.  The following table checks every public method
against its producer, route, and actual app consumer.  “No app read” means the
method remains a public compatibility seam but no current `app.js` call reads
its result.

| Method | Producer / route | App call sites and resolved shape |
|---|---|---|
| `getStatus()` | `GET /api/status`; object from `WebBackend.get_status()` with `modelReady`, `loading`, `error`, backend/version/capability fields. | `app.js:82,935,1423,1534`; reads `modelReady` and `selectedReady`, both produced. |
| `pickFile()` | Browser fallback returns `null`; no fetch. | `app.js:122`; null deliberately selects the HTML file-input fallback. |
| `loadHintTxt()` | Browser fallback returns `null`; no fetch. | No current `app.js` call; desktop-only picker capability is intentionally absent in a browser. |
| `transcribe(opts)` | Multipart `POST /api/transcribe` returns `{job_id, ok}`; `GET /api/jobs/<id>` resolves to `{job_id, segments, srtPath, state}`. | Single `app.js:156-167`, batch `691-700`, recording `1303-1305`; all read only fields supplied by `bridge.js:260-287,365-375`. The PR #32 single-file shape fix covers all three flows. |
| `cancel()` | `POST /api/cancel` with `{}`; bridge returns `true` even if the best-effort request fails. | No current app read; route exists and the method is a compatibility seam. |
| `openOutputDir()` | `POST /api/open-output` with `{}`; bridge returns `true` after best-effort request. | `app.js:566,663`; no response fields read. |
| `checkUpdate()` | `POST /api/check-update` with `{}`; returns server result or `{ok:true}` fallback. | `app.js:1158-1162`; no response fields read. |
| `listDevices()` | `GET /api/devices`; `{devices, diag}`. | `app.js:787-802`; reads `devices`, `kind`, `name`, `note`, and `diag.level/text`, all produced. |
| `setBackend(id)` | `POST /api/backend` with `{index:id}`; backend returns `{ok, backend, restartRequired, message}`. | No current app call/read; route and params match. |
| `getModelOptions()` | `GET /api/model-options`; `{cores:[{label,models}], current, activeArch}`. | `app.js:773-784`; reads `current`, `cores`, model `label/backend/arch/note`, and `activeArch`, all produced. |
| `getCapabilities()` | `GET /api/capabilities`; capability snapshot with `backends`, features, health, and recovery fields. | `app.js:772,730-734,862-869`; reads `backends[*].state`, which `capabilities.build_snapshot()` supplies. |
| `getMessageCodes()` | `GET /api/message-codes`; JSON object keyed by capability code. | `i18n.js:150-179`; passes the table to `CapabilityView.renderCode()`. |
| `setModel(core, model)` | `POST /api/model` with `{core,model}`; success has `message/restartRequired`, coded refusal has `error:{code,params}`. | `app.js:925-929` reads `res.message` and `restartRequired`. The bridge now fills `message` for coded success responses/refusals at `bridge.js:213-218`. |
| `startLoad()` | `POST /api/load` with `{}`; `{ok,loading,alreadyLoaded,wasBusy}`. | `app.js:958-959`; only awaits/reports exceptions, so no missing-field read. |
| `getLanguages()` | `GET /api/languages`; `{languages:[{label,value}]}`. | `app.js:979-990` and status refresh; reads `languages`, `label`, `value`. |
| `getHealthCheck()` | `GET /api/health-check`; `{cores,shared,summary,activeBackend}`. | `app.js:740-763`; reads those exact fields. |
| `getSettings()` | `GET /api/settings`; `{scale,format,vocab,mirror,ffmpeg,theme,uiLang,vad,chunkSecs}`. | `app.js:592,1090-1104,1373,1395,1411`; all reads are present. |
| `setSettings(patch)` | `POST /api/settings` with the patch object; returns the same settings shape. | `app.js:1111-1153`; fire-and-forget, no producer/consumer mismatch. |
| `getEndpoint()` | `GET /api/endpoint`; `{running,host,port,key,url,lan_urls,exposure_notice}`. | `app.js:999-1008`; reads `running`, `port`, `url`, `key`; QR uses `url`. |
| `toggleEndpoint(on_, port)` | `POST /api/endpoint` with `{action:"start"|"stop",port}`; returns endpoint shape. | `app.js:1057-1064`; ignores the immediate result and calls `renderEndpoint()`, so no missing field is read. |
| `regenKey()` | `POST /api/endpoint` with `{action:"regen"}`; endpoint shape including new `key/url`. | `app.js:1072-1076`; reads `key`, `url`, `running`. |
| `getTunnel()` | `GET /api/tunnel`; `{running,url,status}`. | `app.js:1018-1038`; reads those exact fields. |
| `toggleTunnel(on_)` | `POST /api/tunnel` with `{action:"start"|"stop"}`; success has tunnel fields, coded refusal has `error:{code,params}`. | `app.js:1046`; `applyTunnelState()` reads `status/running/url/error`. Bridge now supplies rendered `status` at `bridge.js:234-239`. |
| `qrSrc(data)` | Pure URL builder for `/api/qr?d=...` plus `k` when present; not a fetch. | `app.js:1012,1028`; assigned to image `src`, matching the server route. |
| `getBatch()` | `GET /api/batch`; `{summary:{done,total},items}`. | No current app call; route exists. |
| `addBatchFiles()` | Alias to `getBatch()`; no additional route. | No current app call; deliberate browser compatibility helper. |
| `runBatch()` | Returns `true`; no fetch. Current batch UI runs its files through `transcribe()` one at a time. | No current app call; deliberate compatibility stub, not a route mismatch. |
| `getSnapshot()` | `GET /api/snapshot`; `{status,jobs,endpoint,tunnel}`. | No direct app call; bridge’s `_fetchSnapshot()` uses the same route at `bridge.js:123-127`, then app consumes `_bridge_snapshot` at `app.js:1470-1497`. |
| `cancelJob(jobId)` | `POST /api/jobs/<id>/cancel` with `{}`. | No current app call; route and params match the registry contract. |
| `editSegment(jobId,idx,text)` | `POST /api/jobs/<id>/segments/<idx>` with `{text}`; `{ok:true}`. | `app.js:361`; response is intentionally ignored after optimistic local edit. |
| `recordSaved(jobId,path)` | `POST /api/jobs/<id>/saved` with `{path}`; `{ok:true}`. | `app.js:605`; response is intentionally ignored after recording the saved path. |

The important transcribe result is therefore a resolved job result, not the
initial submission response.  The single-file, batch, and recording callers
all consume the same four fields and no producer-only field was found.

## 2. Route, method, parameter, and key audit

`WebViewServer` dispatches the routes at `webview_server.py:232-296` and
`299-406`.  The bridge’s normal JSON helpers attach both
`Authorization: Bearer <k>` and the `k` query parameter (`bridge.js:141-146`);
`EventSource` uses the query parameter (`bridge.js:44`).  The server accepts
Bearer, `X-Access-Key`, or query `k` for configured browser API routes
(`webview_server.py:214-228`).  `/health` stays public so readiness and
reconnect probes can work; `/` and static assets stay public so the browser
can load the key-bearing page.

| Server route | Bridge caller / access | Parameters and result check |
|---|---|---|
| `GET /` and static `/css/*`, `/js/*`, assets | Browser navigation; no bridge fetch | `index.html` and assets exist; no API key is needed to load the page. |
| `GET /health` | `bridge.js:90-104` reconnect probe, with key query/header; launcher readiness probe | Returns `{status:"ok",model_ready}`; public by design. |
| `GET /api/status` | `getStatus()` | No params; key attached; status shape checked above. |
| `GET /api/settings` | `getSettings()` | No params; key attached. |
| `GET /api/devices` | `listDevices()` | No params; key attached. |
| `GET /api/model-options` | `getModelOptions()` | No params; key attached. |
| `GET /api/languages` | `getLanguages()` | No params; key attached. |
| `GET /api/endpoint` | `getEndpoint()` | No params; key attached. |
| `GET /api/health-check` | `getHealthCheck()` | No params; key attached. |
| `GET /api/tunnel` | `getTunnel()` | No params; key attached. |
| `GET /api/qr?d=<encoded>` | `qrSrc(data)` creates an image URL | `d` is preserved and `k` is appended; returns PNG or JSON error. |
| `GET /api/batch` | `getBatch()` compatibility seam | No params; key attached. |
| `GET /api/capabilities` | `getCapabilities()` | No params; key attached. |
| `GET /api/message-codes` | `getMessageCodes()` / `i18n.js` | No params; key attached; returns the code table. |
| `GET /api/snapshot` | bridge `_fetchSnapshot()` | No params; key attached; returns status, registry snapshot, endpoint, tunnel. |
| `GET /api/jobs` | Registry compatibility route | No params; key attached; returns `{jobs}` snapshot. |
| `GET /api/jobs/<id>` | `_waitForJob()` via `apiGet()` | Job ID is path-encoded by the existing ID factory; key attached; returns full job snapshot. |
| `GET /api/events` | `EventSource` at `bridge.js:44` | Key is in `?k=`; returns SSE JSON envelopes. |
| `POST /api/settings` | `setSettings(patch)` | JSON patch; key header/query; returns settings shape. |
| `POST /api/backend` | `setBackend(id)` | `{index:id}`; key attached. |
| `POST /api/model` | `setModel(core,model)` | `{core,model}`; key attached; coded error is rendered by bridge. |
| `POST /api/load` | `startLoad()` | `{}`; key attached. |
| `POST /api/endpoint` | `toggleEndpoint()` / `regenKey()` | `{action:"start",port}`, `{action:"stop"}`, or `{action:"regen"}`; key attached. |
| `POST /api/tunnel` | `toggleTunnel()` | `{action:"start"|"stop"}`; key attached. |
| `POST /api/transcribe` | `transcribe()` | Multipart `file`, optional `language`, `align`, `diarize`, `n_speakers`, `hint`; key header/query; returns `{job_id,ok}`. |
| `POST /api/cancel` | `cancel()` | `{}`; key attached. |
| `POST /api/quit` | No `QwenAPI` method; launcher/explicit shutdown client | `{}` and `Authorization: Bearer <session key>`; server replies `{ok:true}` then begins shutdown. |
| `POST /api/open-output` | `openOutputDir()` | `{}`; key attached. |
| `POST /api/check-update` | `checkUpdate()` | `{}`; key attached. |
| `POST /api/jobs/<id>/cancel` | `cancelJob()` | `{}`; key attached. |
| `POST /api/jobs/<id>/segments/<idx>` | `editSegment()` | `{text}`; key attached. |
| `POST /api/jobs/<id>/saved` | `recordSaved()` | `{path}`; key attached. |

Every bridge fetch has a matching route.  `pickFile()`, `loadHintTxt()`, and
`runBatch()` deliberately do not fetch; `qrSrc()` only builds a route URL.
`/api/quit` is intentionally not a general `QwenAPI` method because it is the
launcher/explicit lifecycle control.

## 3. SSE event audit

### Server-published events

| Producer | Event(s) | Bridge/app handling |
|---|---|---|
| `webview_backend._emit()` at `webview_backend.py:240-245` | `status`, `progress`, `tunnel` (call sites at lines 269-287, 350-355, 645, 1550-1570) | Bridge forwards them. `app.js:182-197` consumes `progress`, `app.js:1049` consumes `tunnel`, and `app.js:1420-1435` consumes `status`; session state also subscribes to `status`, `tunnel`, and `progress`. |
| SSE connection bootstrap at `webview_server.py:453-455` | `status` | Bridge forwards; app status handler and snapshot path consume it. |
| Shutdown at `app_webview.py:430` | `stopping` with `reason` | Bridge forwards and calls `_handleStopped`; app shows the stopped overlay at `app.js:1521-1523` and applies the canonical state event. |
| Webview direct transcription at `webview_server.py:522` | `progress` with `{job_id,pct,status}` | Bridge forwards unchanged; app’s legacy progress consumer reads the exact fields. |
| Registry subscription at `webview_server.py:147-148` | Outer `job` envelope containing every registry event | Bridge emits `job` for `_waitForJob()` and unwraps `{event,payload}` to the inner event at `bridge.js:53-63`. App’s reducer receives the inner names listed below. |
| `JobRegistry._notify()` | `submitted`, `started`, `finished`, `failed`, `cancelled`, `progress`, `segments_appended`, `segment_edited`, `path_saved`, `note_added`, `item_started`, `item_finished`, `item_failed`, `item_segments_appended` | All are serializable registry payloads. The bridge unwraps all of them. App applies every corresponding reducer event in `app.js:1503-1513` except `item_segments_appended`, which is deliberately snapshot-backed. |

Registry progress is `{job_id,done,total,message}` at
`job_registry.py:343-345`, while the pre-existing progress bar reads
`{pct,status}` at `app.js:182`.  `bridge.js:28-39` now carries both shapes for
registry progress; direct backend progress already arrives in the legacy
shape.

### Frontend listeners

The app’s reducer listener list is `app.js:1503-1508`:

`reconnecting`, `connected`, `stopping`, `stopped`, `status`, `tunnel`,
`submitted`, `started`, `finished`, `failed`, `cancelled`,
`progress`, `segments_appended`, `segment_edited`, `path_saved`, `note_added`,
`item_started`, `item_finished`, and `item_failed`.

`connected` and `reconnecting` are bridge-generated at `bridge.js:45-50` and
`79-84`, not server-published.  `stopped` is bridge-generated at
`bridge.js:119-121` after a server `stopping` event or failed reconnect path;
the private `_bridge_stopped` event remains the overlay hook at
`app.js:1517-1519`.  Thus all three connection lifecycle events now reach the
reducer.

`endpoint` is intentionally not an SSE listener: endpoint actions explicitly
call `renderEndpoint()`, and the canonical endpoint state arrives in the next
`/api/snapshot`.  `JobRegistry.capture_client_closed()` now publishes
`note_added` with the same note string stored in the registry, so the existing
reducer listener receives recording notes live.  The registry’s
`item_started`, `item_finished`, and `item_failed` events remain live and
`item_finished` carries its result.  `item_segments_appended` remains
snapshot-backed because the current browser batch UI does not consume item
segment events.

## 4. HTML assets, globals, and i18n

The eight scripts in `webview/index.html:325-332` are, in order:

1. `js/job_wait.js`
2. `js/bridge.js`
3. `js/i18n.js`
4. `js/capability_view.js`
5. `js/segments.js`
6. `js/session_state.js`
7. `js/alignment_view.js`
8. `js/app.js`

All eight files exist.  This order defines `JobWait`, `QwenAPI`, `I18N`,
`CapabilityView`, `SegmentOps`, `SessionState`, and `AlignmentView` before
`app.js` runs.  `app.js`’s remaining `window.*` names (`AudioContext`,
`webkitAudioContext`, `matchMedia`, `MediaRecorder`, `showSaveFilePicker`,
`getSelection`, and `addEventListener`) are browser-provided globals, not
Ubuntu-only modules.  No ordering/global finding was confirmed.

Static `T("...")` keys used by `app.js` are:

```
model.goto             model.load              model.loading
model.nModels          model.needRestart
record.permDeniedShort record.permGranted       record.permPrompt
result.cancelled
status.loading         status.needModel          status.ready
stopped.crash          stopped.instructions      stopped.replaced
stopped.signal         stopped.userQuit
sub.edit               sub.mergeNext
```

Every static key has three locale entries in `webview/js/i18n.js`; the new
`tests/js/i18n_contract.test.js` source check keeps this table complete when a
new literal `T()` call is added.

## 5. Headless smoke and Windows import guard

`tests/test_headless_smoke.py:87-158` starts `WebViewServer` on an ephemeral
port with a stub backend, verifies `/`, `/api/status`, `/api/capabilities`,
`/api/snapshot`, `/api/message-codes`, and `/api/jobs`, submits a generated
16 kHz WAV to `/api/transcribe`, polls `/api/jobs/<id>` to a terminal state,
and posts keyed `/api/quit`.  API requests use the session key and all
operations are bounded by ten seconds.  The test is green.

`tests/test_platform_seams_import.py:38-64` starts a subprocess, installs the
same tkinter/GUI stubs as `tests/conftest.py`, patches `sys.platform` to
`"win32"`, and imports `webview_backend`, `app_webview`, `platform_seams`,
`settings_store`, `shutdown`, `session_file`, and `ubuntu_launcher`.  All seven
imports succeed; no Linux-only import is required.  The Windows `main()` path
in `app_webview.py` is unchanged.

## Fix verification: red → green evidence

The regression tests were written before each production slice.  The initial
red observations and the final green commands were:

| Finding | Red evidence | Green evidence |
|---|---|---|
| H-01 | `test_configured_webview_access_key_protects_api_routes` initially received HTTP 200 without a key. | `pytest tests/test_webview_server_jobs.py` → 19 passed. |
| H-02 | Fresh-launch test initially opened the unkeyed URL and had no coordinated lifecycle call; reuse had no key in its `Decision`. | `pytest tests/test_ubuntu_launcher.py tests/test_session_file.py` → all passed (launcher slice: 21 passed). |
| H-03 | Coordinator fake initially failed at construction with `TypeError: ShutdownCoordinator.__init__() got an unexpected keyword argument 'endpoint_server'`; Linux wiring initially raised a missing `endpoint_server` capture. | `pytest tests/test_shutdown.py tests/test_app_webview_linux.py` → 25 passed; fake order is `stopping.set`, `cancel_inflight`, `listener.close`. |
| M-01 | Bridge tests initially observed `setModel` `message === undefined` and tunnel `status === ""` for coded `{error:{code,params}}` results. | `node --test tests/js/bridge_contract.test.js` → 7 passed. |
| M-02 | Structured job error initially became `"[object Object]"`; coded endpoint refusal initially returned no human message and left the registry job `running`; a coded engine exception also left its registry job `running`. | `node --test tests/js/job_wait.test.js` and `pytest tests/test_workflow_contract.py tests/test_webview_server_jobs.py` → green; coded registry errors retain `{code,params,message}` and plain-string failures remain supported. |
| M-03 | Bridge envelope test initially saw no `finished`/normalized progress payload at the app event names. | The same `bridge_contract.test.js` run → 7 passed, including envelope and progress assertions. |
| M-04 | Canonical lifecycle test initially counted `connected === 0`; the stopped test initially received `null`. | `node --test tests/js/bridge_contract.test.js` → 7 passed, including `connected`, `reconnecting`, and `stopped(reason)`. |
| L-01 | The new source-contract test initially failed with exactly the six audited missing keys. | `node --test tests/js/i18n_contract.test.js` → 1 passed; the full JavaScript suite also passed. |
| L-02 | New reducer/listener tests initially failed because `endpoint` was subscribed and applied; registry/SSE tests initially received no `note_added` event and item completion omitted its result. | `node --test tests/js/session_state.test.js tests/js/app_snapshot_wiring.test.js` → 46 passed; focused registry/server tests → 94 passed, including live note and batch-item SSE forwarding. |

## Deferred / not findings

- No browser-contract findings remain deferred.
- No transcribe result-shape mismatch was found: single-file, batch, and
  recording all consume the bridge’s `{job_id,segments,srtPath,state}` result.
- No missing bridge route, wrong route verb, wrong JSON/multipart parameter, or
  missing key propagation was found after the access-key fix.
- All static scripts/globals, the requested smoke flow, and the patched-win32
  import guard passed; there is no corresponding finding to fix.
