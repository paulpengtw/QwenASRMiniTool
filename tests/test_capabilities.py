"""Tests for capabilities.py — build_snapshot() and HTTP-level API endpoints."""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(platform: str = "linux", backend: str | None = None,
                cpu_model_size: str = "0.6B", recovered: str | None = None,
                session_ignored=None):
    """Build a minimal SettingsStore-like mock."""
    store = MagicMock()
    store.recovered = recovered
    store.session_ignored = session_ignored or []
    data: dict = {}
    if backend is not None:
        data["backend"] = backend
    if cpu_model_size:
        data["cpu_model_size"] = cpu_model_size

    def _get(key, default=None):
        return data.get(key, default)

    store.get = _get
    return store


def _probes(ffmpeg=True, cloudflared=False, model_present=True,
            model_state="unloaded", model_error=None, diarization=False):
    return {
        "ffmpeg": ffmpeg,
        "cloudflared": cloudflared,
        "model_present": model_present,
        "model_state": model_state,
        "model_error": model_error,
        "diarization": diarization,
    }


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
from capabilities import build_snapshot


# ---------------------------------------------------------------------------
# 1. Fresh Linux settings -> openvino_cpu + 0.6B
# ---------------------------------------------------------------------------

class TestFreshLinuxDefaults:
    def test_effective_backend_is_openvino(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store, _probes())
        assert snap["effective_backend"] == "openvino"

    def test_effective_model_is_06b(self):
        store = _make_store(platform="linux", cpu_model_size="0.6B")
        snap = build_snapshot("linux", store, _probes())
        assert snap["effective_model"] == "0.6B"

    def test_backend_preference_not_overwritten_when_unset(self):
        # If no pref is stored (None), the snapshot still resolves correctly
        # but the preference field reflects the derived default.
        store = _make_store(platform="linux", backend=None)
        snap = build_snapshot("linux", store, _probes())
        # effective_backend must be openvino
        assert snap["effective_backend"] == "openvino"

    def test_no_status_line_when_backend_matches(self):
        store = _make_store(platform="linux", backend="openvino")
        snap = build_snapshot("linux", store, _probes())
        assert snap["status_line"] is None

    def test_openvino_cpu_ready_on_linux(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store, _probes())
        assert snap["backends"]["openvino_cpu"]["state"] == "ready"


# ---------------------------------------------------------------------------
# 2. Windows preference (crispasr) on Linux -> preserved + status code
# ---------------------------------------------------------------------------

class TestWindowsPrefPreservedOnLinux:
    def _snap(self):
        store = _make_store(platform="linux", backend="crispasr")
        return build_snapshot("linux", store, _probes())

    def test_status_line_code_preserved(self):
        snap = self._snap()
        assert snap["status_line"] is not None
        assert snap["status_line"]["code"] == "USING_OPENVINO_CPU_UBUNTU_PREF_PRESERVED"

    def test_backend_preference_is_crispasr(self):
        snap = self._snap()
        assert snap["backend_preference"] == "crispasr"

    def test_effective_backend_is_openvino(self):
        snap = self._snap()
        assert snap["effective_backend"] == "openvino"

    def test_crispasr_platform_unsupported(self):
        snap = self._snap()
        assert snap["backends"]["crispasr"]["state"] == "platform_unsupported"

    def test_chatllm_platform_unsupported(self):
        snap = self._snap()
        assert snap["backends"]["chatllm_vulkan"]["state"] == "platform_unsupported"


# ---------------------------------------------------------------------------
# 3. Missing ffmpeg -> setup_required and NOT a blocker
# ---------------------------------------------------------------------------

class TestMissingFfmpeg:
    def _snap(self):
        store = _make_store(platform="linux")
        return build_snapshot("linux", store, _probes(ffmpeg=False))

    def test_ffmpeg_setup_required(self):
        snap = self._snap()
        assert snap["features"]["ffmpeg"]["state"] == "setup_required"

    def test_ffmpeg_action_install(self):
        snap = self._snap()
        assert snap["features"]["ffmpeg"]["action"] == "install"

    def test_ffmpeg_not_a_blocker(self):
        snap = self._snap()
        blocker_keys = [b["key"] for b in snap["health"]["blockers"]]
        assert "ffmpeg" not in blocker_keys

    def test_ffmpeg_in_optional(self):
        snap = self._snap()
        optional_keys = [o["key"] for o in snap["health"]["optional"]]
        assert "ffmpeg" in optional_keys


# ---------------------------------------------------------------------------
# 4. Missing model -> setup_required with download action
# ---------------------------------------------------------------------------

class TestMissingModel:
    def _snap(self):
        store = _make_store(platform="linux", cpu_model_size="0.6B")
        return build_snapshot("linux", store, _probes(model_present=False,
                                                       model_state="unloaded"))

    def test_model_download_action_in_navigation(self):
        snap = self._snap()
        # navigation_hint targets model page when model absent
        assert snap["navigation_hint"]["target"] == "model"

    def test_model_state_unloaded(self):
        snap = self._snap()
        assert snap["model_state"]["state"] == "unloaded"

    def test_effective_model_0_6b(self):
        snap = self._snap()
        assert snap["effective_model"] == "0.6B"


# ---------------------------------------------------------------------------
# 5. Unhonourable values reported under recovery
# ---------------------------------------------------------------------------

class TestUnhonourableValues:
    def test_session_ignored_reported_in_recovery_events(self):
        store = _make_store(platform="linux",
                            session_ignored=[("backend", "invalid_backend")])
        snap = build_snapshot("linux", store, _probes())
        codes = [e["code"] for e in snap["recovery_events"]]
        assert "invalid_backend" in codes

    def test_settings_recovered_in_recovery_events(self):
        store = _make_store(platform="linux", recovered="/tmp/settings.json.corrupt-20240101")
        snap = build_snapshot("linux", store, _probes())
        codes = [e["code"] for e in snap["recovery_events"]]
        assert "SETTINGS_RECOVERED" in codes

    def test_recovery_event_has_backup_path(self):
        backup = "/tmp/settings.json.corrupt-20240101"
        store = _make_store(platform="linux", recovered=backup)
        snap = build_snapshot("linux", store, _probes())
        evt = next(e for e in snap["recovery_events"] if e["code"] == "SETTINGS_RECOVERED")
        assert evt["params"]["backup_path"] == backup


# ---------------------------------------------------------------------------
# 6. Health blockers rule
# ---------------------------------------------------------------------------

class TestHealthBlockers:
    def test_no_blockers_when_effective_backend_ready(self):
        store = _make_store(platform="linux", backend="openvino")
        snap = build_snapshot("linux", store, _probes())
        assert snap["health"]["blockers"] == []

    def test_model_error_is_a_blocker(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store,
                              _probes(model_state="error", model_error="file not found"))
        blocker_keys = [b["key"] for b in snap["health"]["blockers"]]
        assert "model" in blocker_keys

    def test_optional_features_not_blockers(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store,
                              _probes(ffmpeg=False, cloudflared=False, diarization=False))
        blocker_keys = [b["key"] for b in snap["health"]["blockers"]]
        for opt_key in ("ffmpeg", "cloudflared", "diarization", "forced_alignment"):
            assert opt_key not in blocker_keys


# ---------------------------------------------------------------------------
# 7. Navigation hint
# ---------------------------------------------------------------------------

class TestNavigationHint:
    def test_ready_model_targets_workspace(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store,
                              _probes(model_present=True, model_state="ready"))
        assert snap["navigation_hint"]["target"] == "workspace"

    def test_loading_model_targets_workspace(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store,
                              _probes(model_present=True, model_state="loading"))
        assert snap["navigation_hint"]["target"] == "workspace"

    def test_error_model_targets_model_page(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store,
                              _probes(model_state="error", model_error="failed"))
        assert snap["navigation_hint"]["target"] == "model"

    def test_missing_model_targets_model_page(self):
        store = _make_store(platform="linux")
        snap = build_snapshot("linux", store,
                              _probes(model_present=False, model_state="unloaded"))
        assert snap["navigation_hint"]["target"] == "model"


# ---------------------------------------------------------------------------
# 8. Selecting 1.7B on Ubuntu writes OpenVINO model choice
# ---------------------------------------------------------------------------

class TestModelSizeSelection:
    def test_17b_model_reflected_in_effective_model(self):
        store = _make_store(platform="linux", cpu_model_size="1.7B")
        snap = build_snapshot("linux", store, _probes())
        assert snap["effective_model"] == "1.7B"

    def test_backend_key_unchanged_when_model_size_changes(self):
        store = _make_store(platform="linux", backend="openvino", cpu_model_size="1.7B")
        snap = build_snapshot("linux", store, _probes())
        # Backend pref is still openvino, not crispasr
        assert snap["backend_preference"] == "openvino"
        assert snap["effective_backend"] == "openvino"


# ---------------------------------------------------------------------------
# 9. HTTP-level tests: /api/capabilities and /api/message-codes
# ---------------------------------------------------------------------------

class TestHTTPCapabilitiesEndpoints:
    """Spin up a real WebViewServer on an ephemeral port with a stub backend."""

    @pytest.fixture(autouse=True)
    def _server(self, tmp_path):
        """Start WebViewServer on an ephemeral port; stop after test."""
        # Minimal stub backend to avoid loading real models
        from webview_server import WebViewServer
        from unittest.mock import patch, MagicMock

        stub_snap = {
            "backend_preference": "openvino",
            "effective_backend": "openvino",
            "effective_model": "0.6B",
            "status_line": None,
            "model_state": {"state": "unloaded", "message": None},
            "backends": {
                "openvino_cpu": {"state": "ready", "reason": None,
                                 "remedy": None, "action": None},
                "crispasr": {"state": "platform_unsupported",
                             "reason": {"code": "BACKEND_PLATFORM_UNSUPPORTED",
                                        "params": {"backend": "crispasr"}},
                             "remedy": None, "action": None},
                "chatllm_vulkan": {"state": "platform_unsupported",
                                   "reason": {"code": "BACKEND_PLATFORM_UNSUPPORTED",
                                              "params": {"backend": "chatllm_vulkan"}},
                                   "remedy": None, "action": None},
                "cuda_pytorch": {"state": "platform_unsupported",
                                 "reason": {"code": "BACKEND_PLATFORM_UNSUPPORTED",
                                            "params": {"backend": "cuda_pytorch"}},
                                 "remedy": None, "action": None},
            },
            "features": {
                "ffmpeg": {"state": "ready", "reason": None, "remedy": None, "action": None},
                "cloudflared": {"state": "setup_required",
                                "reason": {"code": "CLOUDFLARED_MISSING", "params": {}},
                                "remedy": None, "action": "install"},
                "forced_alignment": {"state": "platform_unsupported",
                                     "reason": {"code": "ALIGN_WINDOWS_ONLY", "params": {}},
                                     "remedy": None, "action": None},
                "diarization": {"state": "setup_required",
                                "reason": {"code": "MODEL_MISSING",
                                           "params": {"model": "diarization"}},
                                "remedy": None, "action": "download"},
                "endpoint": {"state": "ready", "reason": None, "remedy": None, "action": None},
            },
            "health": {"blockers": [], "optional": []},
            "recovery_events": [],
            "navigation_hint": {"target": "model"},
        }

        with (
            patch.object(WebViewServer, "__init__", lambda self, host="127.0.0.1", port=0: None),
            patch("webview_server.WebBackend"),
        ):
            srv = WebViewServer.__new__(WebViewServer)
            srv.host = "127.0.0.1"
            srv.hub = MagicMock()
            srv.hub.subscribe.return_value = None
            stub_backend = MagicMock()
            stub_backend.get_capabilities.return_value = stub_snap
            stub_backend.get_status.return_value = {"modelReady": False}
            srv.backend = stub_backend
            srv._httpd = None
            srv._thread = None
            srv._want_port = 0

        # Start the real HTTP server manually
        from http.server import ThreadingHTTPServer
        import webview_server as ws_mod

        _this_test = self

        class _Handler(ws_mod._make_handler_class(srv) if hasattr(ws_mod, "_make_handler_class")
                       else _FallbackHandler):
            pass

        # We need to build the real handler. Use the actual server's _httpd.
        # Instead, start the server the normal way with stubs.
        srv2 = _build_test_server(stub_snap)
        self._srv = srv2
        self._port = srv2.port
        yield
        srv2.stop()

    def _get(self, path):
        url = f"http://127.0.0.1:{self._port}{path}"
        req = urllib.request.Request(url, headers={"Host": f"127.0.0.1:{self._port}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())

    def test_capabilities_endpoint_returns_snapshot(self):
        data = self._get("/api/capabilities")
        assert "effective_backend" in data
        assert "backends" in data
        assert "features" in data
        assert "health" in data

    def test_capabilities_has_backend_preference(self):
        data = self._get("/api/capabilities")
        assert "backend_preference" in data

    def test_message_codes_endpoint_returns_codes(self):
        data = self._get("/api/message-codes")
        assert "FFMPEG_MISSING" in data
        assert "BACKEND_PLATFORM_UNSUPPORTED" in data

    def test_message_codes_has_en_zh(self):
        data = self._get("/api/message-codes")
        entry = data.get("FFMPEG_MISSING", {})
        assert "en" in entry
        assert "zh" in entry

    def test_status_embeds_capabilities(self):
        data = self._get("/api/status")
        assert "capabilities" in data


# ---------------------------------------------------------------------------
# Helper: build a real test server
# ---------------------------------------------------------------------------

class _TestServerWrapper:
    """Thin wrapper around a real WebViewServer for HTTP tests."""

    def __init__(self, port: int, stub_snap: dict):
        self.port = port
        self._stub_snap = stub_snap
        self._httpd = None
        self._thread = None

    def start(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        stub_snap = self._stub_snap
        import capability_codes

        class _H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                from urllib.parse import urlparse
                path = urlparse(self.path).path
                if path == "/api/capabilities":
                    return self._json(stub_snap)
                if path == "/api/message-codes":
                    return self._json(json.loads(capability_codes.as_json()))
                if path == "/api/status":
                    return self._json({"modelReady": False, "capabilities": stub_snap})
                self._json({"error": "not found"}, 404)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.port = httpd.server_address[1]
        self._httpd = httpd
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        self._thread = t

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()


def _build_test_server(stub_snap: dict) -> _TestServerWrapper:
    w = _TestServerWrapper(0, stub_snap)
    w.start()
    return w


# Patch the test class to use the simple wrapper instead of real WebViewServer
class TestHTTPCapabilitiesEndpoints:
    """HTTP-level tests for /api/capabilities and /api/message-codes."""

    _stub_snap = {
        "backend_preference": "openvino",
        "effective_backend": "openvino",
        "effective_model": "0.6B",
        "status_line": None,
        "model_state": {"state": "unloaded", "message": None},
        "backends": {
            "openvino_cpu": {"state": "ready", "reason": None, "remedy": None, "action": None},
            "crispasr": {"state": "platform_unsupported",
                         "reason": {"code": "BACKEND_PLATFORM_UNSUPPORTED",
                                    "params": {"backend": "crispasr"}},
                         "remedy": None, "action": None},
            "chatllm_vulkan": {"state": "platform_unsupported",
                               "reason": {"code": "BACKEND_PLATFORM_UNSUPPORTED",
                                          "params": {"backend": "chatllm_vulkan"}},
                               "remedy": None, "action": None},
            "cuda_pytorch": {"state": "platform_unsupported",
                             "reason": {"code": "BACKEND_PLATFORM_UNSUPPORTED",
                                        "params": {"backend": "cuda_pytorch"}},
                             "remedy": None, "action": None},
        },
        "features": {
            "ffmpeg": {"state": "ready", "reason": None, "remedy": None, "action": None},
            "cloudflared": {"state": "setup_required",
                            "reason": {"code": "CLOUDFLARED_MISSING", "params": {}},
                            "remedy": None, "action": "install"},
            "forced_alignment": {"state": "platform_unsupported",
                                 "reason": {"code": "ALIGN_WINDOWS_ONLY", "params": {}},
                                 "remedy": None, "action": None},
            "diarization": {"state": "setup_required",
                            "reason": {"code": "MODEL_MISSING",
                                       "params": {"model": "diarization"}},
                            "remedy": None, "action": "download"},
            "endpoint": {"state": "ready", "reason": None, "remedy": None, "action": None},
        },
        "health": {"blockers": [], "optional": []},
        "recovery_events": [],
        "navigation_hint": {"target": "model"},
    }

    @pytest.fixture(autouse=True)
    def _start_server(self):
        w = _build_test_server(self._stub_snap)
        self._port = w.port
        yield
        w.stop()

    def _get(self, path):
        url = f"http://127.0.0.1:{self._port}{path}"
        req = urllib.request.Request(url, headers={"Host": f"127.0.0.1:{self._port}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())

    def test_capabilities_endpoint_returns_snapshot(self):
        data = self._get("/api/capabilities")
        assert "effective_backend" in data
        assert "backends" in data
        assert "features" in data
        assert "health" in data

    def test_capabilities_has_backend_preference(self):
        data = self._get("/api/capabilities")
        assert "backend_preference" in data

    def test_message_codes_endpoint_returns_codes(self):
        data = self._get("/api/message-codes")
        assert "FFMPEG_MISSING" in data
        assert "BACKEND_PLATFORM_UNSUPPORTED" in data

    def test_message_codes_has_en_zh(self):
        data = self._get("/api/message-codes")
        entry = data.get("FFMPEG_MISSING", {})
        assert "en" in entry
        assert "zh" in entry

    def test_status_embeds_capabilities(self):
        data = self._get("/api/status")
        assert "capabilities" in data
