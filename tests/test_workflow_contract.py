"""tests/test_workflow_contract.py — Workflow compatibility contract (ticket 08).

Tests (strict TDD — each test documents the expected behaviour before it exists):

1. api_server: POST /v1/audio/transcriptions with a video file when ffmpeg absent
   → HTTP 409 with JSON {error: {code: "VIDEO_NEEDS_FFMPEG", params, remedy}}.
2. api_server: POST /v1/audio/transcriptions with an audio (.wav) file when ffmpeg absent
   → 200 OK (audio does not need ffmpeg; stub engine transcribes it).
3. api_server: POST /v1/audio/transcriptions with a WebM file when ffmpeg absent
   → HTTP 409 with JSON {error: {code: "RECORDING_NEEDS_FFMPEG", params, remedy}}.
4. webview_backend: toggle_tunnel(True) on Linux without cloudflared
   → {ok: False, error: {code: "CLOUDFLARED_MISSING"}} and download_cloudflared NOT called.
5. cf_tunnel.CloudflareTunnel.start with a fake subprocess that never prints a URL
   → fails within the injected timeout, terminate() is called.
6. webview_backend.get_endpoint (or toggle_endpoint result) carries lan_urls (list) and
   exposure_notice {code: "ENDPOINT_LAN_EXPOSED"}.
"""
from __future__ import annotations

import io
import json
import socket
import sys
import tempfile
import threading
import time
import types
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]


def _multipart_body(filename: str, data: bytes, boundary: bytes = b"boundary123") -> bytes:
    """Build a minimal multipart/form-data body for a single file field."""
    lines = [
        b"--" + boundary,
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(),
        b"Content-Type: application/octet-stream",
        b"",
        data,
        b"--" + boundary + b"--",
        b"",
    ]
    return b"\r\n".join(lines)


def _post_transcribe(port: int, token: str, filename: str, data: bytes,
                     response_format: str | None = None):
    """POST a file to /v1/audio/transcriptions on localhost:<port>.

    Returns (status_code, parsed_body).  For error responses the body is always
    JSON; for 200 responses it may be plain text (SRT/text) or JSON depending on
    response_format.  Returns (status, raw_bytes_string) for 200 plain text.
    """
    boundary = b"boundary123"
    file_data = data
    if response_format:
        # Append a response_format field to the multipart body
        fmt_part = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="response_format"\r\n\r\n'
            + response_format.encode() + b"\r\n"
        )
        body = fmt_part + _multipart_body(filename, file_data, boundary)
    else:
        body = _multipart_body(filename, file_data, boundary)

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
            "Content-Length": str(len(body)),
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _StubEngine:
    """Minimal stub engine that 'transcribes' by writing a fixed SRT file."""
    ready = True
    use_aligner = False
    _fa_bin = None
    diar_engine = None

    def process_file(self, path, *, language=None, diarize=False, n_speakers=None,
                     original_path=None, out_format="srt", progress_cb=None, **kw):
        out = Path(path).with_suffix(".srt")
        out.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n\n", encoding="utf-8")
        return str(out)


# ---------------------------------------------------------------------------
# Test group 1-3: api_server FFmpeg-absent behaviour
# ---------------------------------------------------------------------------

class TestApiServerFfmpegAbsent:
    """api_server.TranscribeServer coded refusal when FFmpeg is absent."""

    @pytest.fixture(autouse=True)
    def server(self):
        """Start a TranscribeServer on a free port with a stub engine."""
        sys.path.insert(0, str(ROOT))
        from api_server import TranscribeServer
        engine = _StubEngine()
        port = _find_free_port()
        srv = TranscribeServer(get_engine=lambda: engine, port=port, host="127.0.0.1")
        srv.start()
        yield srv
        srv.stop()

    def test_video_file_returns_409_VIDEO_NEEDS_FFMPEG(self, server):
        """Video file (.mp4) without ffmpeg → 409 coded error VIDEO_NEEDS_FFMPEG."""
        # Monkeypatch platform_seams.find_executable to return None so
        # ffmpeg_utils.find_ffmpeg() returns None.
        import platform_seams
        with patch.object(platform_seams, "find_executable", return_value=None):
            status, body = _post_transcribe(
                server._port, server.token, "clip.mp4", b"fake-mp4-data"
            )
        assert status == 409, f"Expected 409, got {status}; body={body}"
        error = body.get("error", {})
        assert error.get("code") == "VIDEO_NEEDS_FFMPEG", f"Wrong code: {error}"
        assert "remedy" in error, "Missing remedy field"

    def test_audio_file_still_works_without_ffmpeg(self, server):
        """Audio file (.wav) does not need ffmpeg; stub engine returns 200."""
        import platform_seams
        with patch.object(platform_seams, "find_executable", return_value=None):
            status, body = _post_transcribe(
                server._port, server.token, "recording.wav",
                b"RIFF\x00\x00\x00\x00WAVEfmt ",
            )
        # 200 = success; body may be SRT text or JSON depending on response_format
        assert status == 200, f"Expected 200, got {status}; body={body}"

    def test_webm_file_returns_409_RECORDING_NEEDS_FFMPEG(self, server):
        """WebM/Opus recording without ffmpeg → 409 RECORDING_NEEDS_FFMPEG."""
        import platform_seams
        with patch.object(platform_seams, "find_executable", return_value=None):
            status, body = _post_transcribe(
                server._port, server.token, "capture.webm", b"fake-webm-data"
            )
        assert status == 409, f"Expected 409, got {status}; body={body}"
        error = body.get("error", {})
        assert error.get("code") == "RECORDING_NEEDS_FFMPEG", f"Wrong code: {error}"
        assert "remedy" in error, "Missing remedy field"


# ---------------------------------------------------------------------------
# Test group 4: toggle_tunnel on Linux without cloudflared
# ---------------------------------------------------------------------------

class TestToggleTunnelLinuxNoCloudfared:
    """toggle_tunnel returns coded failure on Linux when cloudflared is absent."""

    def _make_backend(self):
        """Create a WebBackend with stubs to avoid heavy imports."""
        sys.path.insert(0, str(ROOT))
        from webview_backend import WebBackend
        backend = WebBackend.__new__(WebBackend)
        backend._server = MagicMock()
        backend._server.running = True
        backend._server._port = 11435
        backend._server.token = "testtoken"
        backend._tunnel = None
        backend._on_event = None
        backend._lock = __import__("threading").Lock()
        return backend

    def test_coded_failure_and_no_download_called(self):
        """On Linux with cloudflared missing: ok=False, code=CLOUDFLARED_MISSING, no download."""
        import cf_tunnel
        backend = self._make_backend()

        download_mock = MagicMock()

        with patch.object(cf_tunnel, "find_cloudflared", return_value=None), \
             patch.object(cf_tunnel, "download_cloudflared", download_mock), \
             patch.object(sys, "platform", "linux"):
            result = backend.toggle_tunnel(True)

        assert result.get("ok") is False, f"Expected ok=False, got {result}"
        error = result.get("error", {})
        assert error.get("code") == "CLOUDFLARED_MISSING", f"Wrong code: {error}"
        assert "remedy" in error, "Missing remedy in error"
        download_mock.assert_not_called()

    def test_windows_keeps_download_path(self):
        """On Windows the code goes through to CloudflareTunnel.start (download path preserved)."""
        import cf_tunnel
        backend = self._make_backend()

        # On windows: find_cloudflared returns None → CloudflareTunnel.start would
        # call download_cloudflared. We just verify toggle_tunnel doesn't return
        # CLOUDFLARED_MISSING on win32.
        with patch.object(cf_tunnel, "find_cloudflared", return_value=None), \
             patch.object(sys, "platform", "win32"):
            # Patch start so it does not actually spawn
            with patch.object(cf_tunnel.CloudflareTunnel, "start", return_value=None):
                result = backend.toggle_tunnel(True)

        # Should NOT have a CLOUDFLARED_MISSING error (the download path is taken)
        error = result.get("error") or {}
        assert error.get("code") != "CLOUDFLARED_MISSING", (
            f"Windows path should not return CLOUDFLARED_MISSING; got {result}"
        )


# ---------------------------------------------------------------------------
# Test group 5: CloudflareTunnel.start timeout
# ---------------------------------------------------------------------------

class TestCloudfareTunnelStartTimeout:
    """CloudflareTunnel.start with a fake subprocess that never prints a URL."""

    def test_timeout_terminates_process(self):
        """Fake proc never yields a URL → fails within injected timeout, terminate() called."""
        sys.path.insert(0, str(ROOT))
        from cf_tunnel import CloudflareTunnel

        # Build a fake Popen whose stdout yields lines slowly but never a URL.
        class _FakeStdout:
            def __iter__(self):
                # Yield benign lines forever until the process is terminated.
                for _ in range(1000):
                    yield "INFO Starting tunnel\n"
                    time.sleep(0.05)

        fake_proc = MagicMock()
        fake_proc.stdout = _FakeStdout()
        fake_proc.pid = 99999
        terminate_called = threading.Event()

        def _fake_terminate():
            terminate_called.set()

        fake_proc.terminate = _fake_terminate

        tunnel = CloudflareTunnel()

        # Inject the fake proc by patching platform_seams.spawn and find_cloudflared
        import cf_tunnel
        with patch.object(cf_tunnel, "find_cloudflared", return_value=Path("/usr/bin/cloudflared")), \
             patch("cf_tunnel._spawn", return_value=fake_proc):
            url = tunnel.start(port=11435, timeout=0.3)  # 300 ms injected timeout

        assert url is None, f"Expected None URL on timeout, got {url!r}"
        assert terminate_called.wait(timeout=2.0), "terminate() was not called within 2 s"
        assert tunnel.status.startswith("failed") or "failed" in tunnel.status.lower(), (
            f"Expected failed status, got {tunnel.status!r}"
        )

    def test_timeout_sets_failed_status_with_captured_output(self):
        """Failed status includes captured output."""
        sys.path.insert(0, str(ROOT))
        from cf_tunnel import CloudflareTunnel
        import cf_tunnel

        class _FakeStdout:
            def __iter__(self):
                yield "INFO cloudflared starting\n"
                yield "WARN connection timeout\n"
                time.sleep(0.5)

        fake_proc = MagicMock()
        fake_proc.stdout = _FakeStdout()
        fake_proc.pid = 99999
        fake_proc.terminate = MagicMock()

        tunnel = CloudflareTunnel()
        with patch.object(cf_tunnel, "find_cloudflared", return_value=Path("/usr/bin/cloudflared")), \
             patch("cf_tunnel._spawn", return_value=fake_proc):
            url = tunnel.start(port=11435, timeout=0.2)

        assert url is None
        # Status should mention failure
        assert "fail" in tunnel.status.lower() or tunnel.status == "failed", (
            f"Status should indicate failure, got {tunnel.status!r}"
        )


# ---------------------------------------------------------------------------
# Test group 6: Endpoint payload carries lan_urls and exposure_notice
# ---------------------------------------------------------------------------

class TestEndpointLanExposure:
    """get_endpoint response includes lan_urls and exposure_notice."""

    def _make_backend_with_server(self):
        """Create a WebBackend whose _server is running."""
        sys.path.insert(0, str(ROOT))
        from webview_backend import WebBackend
        from api_server import TranscribeServer

        backend = WebBackend.__new__(WebBackend)
        engine = _StubEngine()
        port = _find_free_port()
        srv = TranscribeServer(get_engine=lambda: engine, port=port, host="127.0.0.1")
        srv.start()
        backend._server = srv
        backend._tunnel = None
        backend._on_event = None
        backend._lock = __import__("threading").Lock()
        return backend, srv

    def test_get_endpoint_includes_lan_urls(self):
        """get_endpoint() returns a non-empty lan_urls list when server is running."""
        backend, srv = self._make_backend_with_server()
        try:
            info = backend.get_endpoint()
            assert "lan_urls" in info, f"Missing lan_urls in {info}"
            assert isinstance(info["lan_urls"], list), "lan_urls should be a list"
        finally:
            srv.stop()

    def test_get_endpoint_includes_exposure_notice(self):
        """get_endpoint() returns exposure_notice with code ENDPOINT_LAN_EXPOSED."""
        backend, srv = self._make_backend_with_server()
        try:
            info = backend.get_endpoint()
            assert "exposure_notice" in info, f"Missing exposure_notice in {info}"
            notice = info["exposure_notice"]
            assert notice.get("code") == "ENDPOINT_LAN_EXPOSED", (
                f"Wrong code: {notice}"
            )
        finally:
            srv.stop()

    def test_get_endpoint_exposure_notice_has_params(self):
        """exposure_notice.params is present (may be empty or contain urls/port)."""
        backend, srv = self._make_backend_with_server()
        try:
            info = backend.get_endpoint()
            notice = info.get("exposure_notice", {})
            assert "params" in notice, f"Missing params in exposure_notice: {notice}"
        finally:
            srv.stop()


# ---------------------------------------------------------------------------
# Test group 7: Capability codes contain the new codes
# ---------------------------------------------------------------------------

class TestNewCapabilityCodes:
    """The capability_codes registry contains the ticket-mandated codes."""

    def test_VIDEO_NEEDS_FFMPEG_present(self):
        from capability_codes import CODES
        assert "VIDEO_NEEDS_FFMPEG" in CODES, "Missing VIDEO_NEEDS_FFMPEG code"

    def test_RECORDING_NEEDS_FFMPEG_present(self):
        from capability_codes import CODES
        assert "RECORDING_NEEDS_FFMPEG" in CODES, "Missing RECORDING_NEEDS_FFMPEG code"

    def test_ENDPOINT_LAN_EXPOSED_present(self):
        from capability_codes import CODES
        assert "ENDPOINT_LAN_EXPOSED" in CODES, "Missing ENDPOINT_LAN_EXPOSED code"

    def test_CLOUDFLARED_MISSING_has_remedy(self):
        """CLOUDFLARED_MISSING entry should include install instructions."""
        from capability_codes import CODES, render
        entry = CODES.get("CLOUDFLARED_MISSING", {})
        en_text = entry.get("en", "")
        # Should contain some installation hint
        assert any(kw in en_text.lower() for kw in ("install", "apt", "package", "path")), (
            f"CLOUDFLARED_MISSING.en should mention installation: {en_text}"
        )

    def test_all_new_codes_have_en_zh_severity(self):
        from capability_codes import CODES
        for code in ("VIDEO_NEEDS_FFMPEG", "RECORDING_NEEDS_FFMPEG", "ENDPOINT_LAN_EXPOSED"):
            entry = CODES[code]
            assert "en" in entry
            assert "zh" in entry
            assert "severity" in entry


# ---------------------------------------------------------------------------
# 7. _job_registry wired to backend (ticket 08 gap)
# ---------------------------------------------------------------------------

class TestJobRegistryWiring:
    """Verify that WebViewServer wires its registry to backend._job_registry.

    Gap: _job_registry was never assigned to the backend instance; consequently
    on_sse_client_disconnected() always obtained None from getattr and never
    called capture_client_closed().
    """

    def test_backend_has_job_registry_after_init(self):
        """WebViewServer.__init__ must set backend._job_registry = self.registry."""
        sys.path.insert(0, str(ROOT))
        from webview_server import WebViewServer

        server = WebViewServer(host="127.0.0.1", port=0)
        assert hasattr(server.backend, "_job_registry"), (
            "backend._job_registry not set after WebViewServer.__init__"
        )
        assert server.backend._job_registry is server.registry, (
            "backend._job_registry is not the same object as server.registry"
        )

    def test_sse_disconnect_calls_capture_client_closed(self):
        """on_sse_client_disconnected() must call registry.capture_client_closed(job_id)."""
        sys.path.insert(0, str(ROOT))
        from webview_server import WebViewServer

        server = WebViewServer(host="127.0.0.1", port=0)

        # Submit a recording job (kind="recording" starts in "capturing" state).
        job = server.registry.submit(kind="recording", spec={"channel": "mono"})
        job_id = job.job_id

        # Point the backend at the active job.
        server.backend._recording_job_id = job_id

        # Simulate SSE client disconnect.
        server.backend.on_sse_client_disconnected()

        # The job should now be completed with the expected note.
        job_dict = server.registry._jobs[job_id].to_dict()
        assert job_dict["state"] == "completed", (
            f"Expected job state 'completed' after disconnect, got {job_dict['state']!r}"
        )
        assert any("capture_client_closed" in n or "ended early" in n
                   for n in job_dict.get("notes", [])), (
            f"Expected note about capture client closure, got {job_dict.get('notes')}"
        )
