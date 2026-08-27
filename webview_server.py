"""webview_server.py — 桌面 WebView 的本機 HTTP 伺服器（純標準庫）

把 webview/ 靜態前端與 /api/* 業務端點以同一個 stdlib HTTP 伺服器提供，
並以 SSE（/api/events）把進度/狀態主動推給前端。設計取向與 Eel /
flaskwebgui 相同（本機 server + 瀏覽器渲染），但零第三方相依，方便
PyInstaller 打包（與既有 api_server.py 一致的做法）。

安全：只綁 127.0.0.1（loopback），外部連不到、且不觸發防火牆提示，
故桌面用途免金鑰。LAN 對外的 OpenAI 相容端點仍由 api_server.py 負責。

路由：
  GET  /                      → webview/index.html
  GET  /css/* /js/* …         → webview/ 靜態檔
  GET  /health                → {"status","model_ready"}
  GET  /api/status            → 後端狀態
  GET  /api/settings          → 設定；POST 改設定（json patch）
  GET  /api/devices           → 裝置 + 診斷
  GET  /api/endpoint          → LAN 端點狀態；POST {action:start|stop|regen,port?}
  POST /api/backend           → {index} 切換推理核心
  POST /api/transcribe        → multipart 上傳轉錄，回 {segments,srtPath}
  GET  /api/events            → SSE：data: {"event","payload"} 進度/狀態推送
"""
from __future__ import annotations

import json
import queue
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from webview_backend import WebBackend
from job_registry import JobRegistry


def resolve_web_dir() -> Path:
    """前端資產目錄：原始碼用專案 webview/；PyInstaller 凍結時用 _MEIPASS。

    凍結時刻意放在 `webview_assets/`，避免與 pywebview 套件本身的
    `webview/` 目錄在 _internal/ 撞名混在一起（兩者皆名為 webview）。
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for name in ("webview_assets", "webview"):     # 優先乾淨的 webview_assets
            d = base / name
            if (d / "index.html").is_file():
                return d
        return base / "webview_assets"
    return Path(__file__).resolve().parent / "webview"


WEB_DIR = resolve_web_dir()

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class _EventHub:
    """SSE 廣播：每個連線一個 Queue，publish() 推給全部訂閱者。"""

    def __init__(self):
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: str, payload: dict):
        msg = {"event": event, "payload": payload}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except Exception:
                pass


class WebViewServer:
    """本機前端伺服器。持有 WebBackend + EventHub。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.hub = _EventHub()
        self.backend = WebBackend(on_event=self.hub.publish)
        self.registry = JobRegistry()
        # Wire the registry to the backend so on_sse_client_disconnected() can
        # call capture_client_closed() when a recording SSE client drops.
        # (Gap fix: _job_registry was never assigned, so reg was always None.)
        self.backend._job_registry = self.registry
        # Publish registry events as SSE "job" events
        self.registry.subscribe(
            lambda ev, payload: self.hub.publish("job", {"event": ev, "payload": payload})
        )
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._want_port = port
        self.port = port
        # Shutdown coordinator (ticket 11): set by the launcher on non-win32.
        # When set, POST /api/quit is enabled and requires the access key.
        self.shutdown_coordinator = None
        # Access key for POST /api/quit (same as the session access key).
        # Set by the launcher; None means the endpoint is not enabled.
        self.quit_access_key: str | None = None
        # Flag: False -> refuse new work with 503 APP_STOPPING (ticket 11).
        self._accepting_work: bool = True

    def start(self):
        if self._httpd:
            return
        server = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):    # 靜音預設存取日誌
                pass

            # ── 回應輔助 ──────────────────────────────────────
            def _json(self, obj, code=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _err(self, code, msg):
                self._json({"error": {"message": msg}}, code)

            def _read_json_body(self) -> dict:
                n = int(self.headers.get("Content-Length", 0))
                if not n:
                    return {}
                try:
                    return json.loads(self.rfile.read(n).decode("utf-8"))
                except Exception:
                    return {}

            # ── DNS rebinding / CSRF 防護 ─────────────────────
            #   惡意網站可能用 DNS rebinding 把網域指向 127.0.0.1，或跨站
            #   POST 到本機 /api（端點有副作用）。要求 Host/Origin 必須是
            #   本機回環位址 —— Edge --app 載入的就是 127.0.0.1:port，會通過。
            def _check_host(self) -> bool:
                allowed = {f"127.0.0.1:{server.port}", f"localhost:{server.port}"}
                if self.headers.get("Host", "") not in allowed:
                    self._err(403, "bad host")
                    return False
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{a}" for a in allowed}:
                    self._err(403, "bad origin")
                    return False
                return True

            # ── GET ───────────────────────────────────────────
            def do_GET(self):
                path = urlparse(self.path).path
                if (path.startswith("/api/") or path == "/health") and not self._check_host():
                    return
                if path == "/health":
                    b = server.backend
                    return self._json({"status": "ok",
                                       "model_ready": bool(getattr(b.engine, "ready", False))})
                if path == "/api/status":
                    return self._json(server.backend.get_status())
                if path == "/api/settings":
                    return self._json(server.backend.get_settings())
                if path == "/api/devices":
                    return self._json(server.backend.list_devices())
                if path == "/api/model-options":
                    return self._json(server.backend.get_model_options())
                if path == "/api/languages":
                    return self._json(server.backend.get_languages())
                if path == "/api/endpoint":
                    return self._json(server.backend.get_endpoint())
                if path == "/api/health-check":
                    return self._json(server.backend.health_check())
                if path == "/api/tunnel":
                    return self._json(server.backend.get_tunnel())
                if path == "/api/qr":
                    return self._qr(urlparse(self.path).query)
                if path == "/api/batch":
                    return self._json(server.backend.get_batch())
                if path == "/api/capabilities":
                    return self._json(server.backend.get_capabilities())
                if path == "/api/message-codes":
                    import capability_codes, json as _json
                    return self._json(_json.loads(capability_codes.as_json()))
                if path == "/api/snapshot":
                    b = server.backend
                    try:
                        endpoint = b.get_endpoint()
                    except Exception:
                        endpoint = None
                    try:
                        tunnel = b.get_tunnel()
                    except Exception:
                        tunnel = None
                    return self._json({
                        "status": b.get_status(),
                        "jobs": server.registry.snapshot(),
                        "endpoint": endpoint,
                        "tunnel": tunnel,
                    })
                if path == "/api/jobs":
                    return self._json(server.registry.snapshot())
                if path == "/api/events":
                    return self._sse()
                if path.startswith("/api/"):
                    return self._err(404, "unknown api")
                return self._static(path)

            # ── POST ──────────────────────────────────────────
            def do_POST(self):
                path = urlparse(self.path).path
                if not self._check_host():        # 所有 POST 皆為 /api，一律驗證
                    return
                try:
                    if path == "/api/settings":
                        return self._json(server.backend.set_settings(self._read_json_body()))
                    if path == "/api/backend":
                        return self._json(server.backend.set_backend(
                            self._read_json_body().get("index")))
                    if path == "/api/model":
                        body = self._read_json_body()
                        return self._json(server.backend.set_model(
                            body.get("core"), body.get("model")))
                    if path == "/api/load":           # 首次選定模型 → 就地下載並載入
                        return self._json(server.backend.request_load())
                    if path == "/api/endpoint":
                        body = self._read_json_body()
                        act = body.get("action")
                        if act == "start":
                            return self._json(server.backend.toggle_endpoint(True, body.get("port")))
                        if act == "stop":
                            return self._json(server.backend.toggle_endpoint(False))
                        if act == "regen":
                            return self._json(server.backend.regen_key())
                        return self._err(400, "unknown action")
                    if path == "/api/tunnel":
                        act = self._read_json_body().get("action")
                        return self._json(server.backend.toggle_tunnel(act == "start"))
                    if path == "/api/transcribe":
                        return self._transcribe_job()
                    if path == "/api/cancel":
                        return self._json({"ok": server.backend.cancel()})
                    if path == "/api/quit":
                        # Requires access key (ticket 11).
                        import secrets as _sec
                        key = server.quit_access_key
                        if not key:
                            return self._err(403, "quit endpoint not configured")
                        auth = self.headers.get("Authorization", "")
                        got = auth[7:].strip() if auth.startswith("Bearer ") else ""
                        if not got or not _sec.compare_digest(got, key):
                            return self._err(401, "invalid access key")
                        # Respond 200 then trigger shutdown.
                        self._json({"ok": True})
                        coord = server.shutdown_coordinator
                        if coord is not None:
                            threading.Thread(
                                target=coord.begin,
                                args=("user-quit",),
                                daemon=True,
                            ).start()
                        return
                    if path == "/api/open-output":
                        return self._json({"ok": server.backend.open_output_dir()})
                    if path == "/api/check-update":
                        return self._json(server.backend.open_releases())
                    # /api/jobs/<id>/cancel
                    # /api/jobs/<id>/segments/<idx>
                    # /api/jobs/<id>/saved
                    if path.startswith("/api/jobs/"):
                        parts = path.split("/")
                        # parts: ['', 'api', 'jobs', '<id>', ...]
                        if len(parts) >= 5:
                            job_id = parts[3]
                            sub = parts[4]
                            if sub == "cancel":
                                try:
                                    server.registry.cancel(job_id)
                                    return self._json({"ok": True})
                                except KeyError:
                                    return self._err(404, "job not found")
                            if sub == "segments" and len(parts) >= 6:
                                try:
                                    idx = int(parts[5])
                                except (ValueError, IndexError):
                                    return self._err(400, "invalid segment index")
                                body = self._read_json_body()
                                text = body.get("text")
                                if text is None:
                                    return self._err(400, "missing text")
                                try:
                                    server.registry.edit_segment(job_id, idx, str(text))
                                    return self._json({"ok": True})
                                except (KeyError, IndexError) as exc:
                                    return self._err(404, str(exc))
                            if sub == "saved":
                                body = self._read_json_body()
                                path_val = body.get("path")
                                if not path_val:
                                    return self._err(400, "missing path")
                                try:
                                    server.registry.record_saved_path(job_id, str(path_val))
                                    return self._json({"ok": True})
                                except KeyError:
                                    return self._err(404, "job not found")
                    return self._err(404, "unknown api")
                except Exception as e:
                    return self._err(500, str(e))

            # ── QR 圖（segno → PNG）───────────────────────────
            def _qr(self, query):
                from urllib.parse import parse_qs
                data = (parse_qs(query).get("d", [""])[0] or "").strip()
                png = server.backend.make_qr(data) if data else None
                if not png:
                    return self._err(404, "qr unavailable")
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(png)

            # ── 靜態檔 ────────────────────────────────────────
            def _static(self, path):
                if path in ("", "/"):
                    path = "/index.html"
                target = (WEB_DIR / path.lstrip("/")).resolve()
                # 防目錄穿越：必須仍在 WEB_DIR 內
                if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
                    return self._err(403, "forbidden")
                if not target.is_file():
                    return self._err(404, "not found")
                data = target.read_bytes()
                ctype = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)

            # ── SSE 進度/狀態串流 ─────────────────────────────
            def _sse(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q = server.hub.subscribe()
                # 連上時先補一次目前狀態，避免錯過載入完成事件
                try:
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    init = {"event": "status",
                            "payload": {"modelReady": bool(getattr(server.backend.engine, "ready", False))}}
                    self.wfile.write(f"data: {json.dumps(init, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    while True:
                        try:
                            msg = q.get(timeout=15)
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")     # 心跳，維持連線
                            self.wfile.flush()
                            continue
                        self.wfile.write(f"data: {json.dumps(msg, ensure_ascii=False)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    server.hub.unsubscribe(q)
                    # Ticket 08 — recording capture-client disconnect:
                    # job_registry.py is in the tree; notify the backend so
                    # it can call registry.capture_client_closed(job_id) to
                    # retain segments and complete the recording job
                    # (decision doc 02: capture ends with its client,
                    # segments retained).
                    try:
                        server.backend.on_sse_client_disconnected()
                    except Exception:
                        pass

            # ── 轉錄（multipart 上傳）─────────────────────────
            def _transcribe_job(self):
                """Create a registry job for a single-file transcription request."""
                from api_server import _parse_multipart
                ctype = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ctype or "boundary=" not in ctype:
                    return self._err(400, "需以 multipart/form-data 上傳 file")
                boundary = ctype.split("boundary=", 1)[1].strip().strip('"').encode()
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                fields, files = _parse_multipart(body, boundary)
                if "file" not in files or not files["file"][1]:
                    return self._err(400, "缺少 file 或內容為空")
                filename, data = files["file"]

                tmp_dir = Path(tempfile.mkdtemp(prefix="asr_web_"))
                ext = Path(filename).suffix or ".wav"
                in_path = tmp_dir / ("upload" + ext)
                in_path.write_bytes(data)

                opts = {
                    "path": str(in_path),
                    "name": filename,
                    "language": (fields.get("language") or "").strip() or None,
                    "diarize": (fields.get("diarize", "") or "").lower() in ("1", "true", "on", "yes"),
                    "nSpeakers": fields.get("n_speakers", ""),
                    "align": (fields.get("align", "1") or "").lower() in ("1", "true", "on", "yes"),
                    "hint": fields.get("hint", ""),
                }

                # Create a registry job and run it through the inference lane
                job = server.registry.submit(kind="single", spec=opts, lane="inference")
                job_id = job.job_id

                def _run():
                    import shutil
                    try:
                        server.registry.start(job_id)
                        result = server.backend.transcribe(
                            opts, progress_cb=lambda pct, status: (
                                server.registry.update_progress(job_id, pct, 100, status),
                                server.hub.publish("progress", {"job_id": job_id, "pct": pct, "status": status}),
                            ))
                        segs = result.get("segments", [])
                        if segs:
                            server.registry.append_segments(job_id, segs)
                        srt_path = result.get("srtPath")
                        if srt_path:
                            server.registry.record_saved_path(job_id, srt_path)
                        server.registry.finish(job_id, result=result)
                    except Exception as exc:
                        try:
                            server.registry.fail(job_id, str(exc))
                        except Exception:
                            pass
                    finally:
                        try:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                        except Exception:
                            pass

                t = threading.Thread(target=_run, daemon=True)
                t.start()
                return self._json({"job_id": job_id, "ok": True})

        self._httpd = ThreadingHTTPServer((self.host, self._want_port), _Handler)
        self.port = self._httpd.server_address[1]      # 取得實際綁定的埠（port=0 時）
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


if __name__ == "__main__":
    # 獨立啟動（除錯用）：起 server，印出網址。只有「選擇的模型已下載」才自動
    # 載入（與 app_webview 一致：首次/未下載 → 等使用者於模型頁按下載，避免硬抓）。
    srv = WebViewServer(port=8765)
    srv.start()
    if srv.backend.selected_model_present():
        srv.backend.start_load()
    print(f"WebView server: {srv.url}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.stop()
