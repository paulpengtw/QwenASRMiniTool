"""Tests for downloader.py ticket-06 features:

- .part-then-rename file staging
- Range resume from existing .part
- Transient mid-stream retry (IncompleteRead / ConnectionResetError)
- Offline fast-fail (ConnectionRefusedError → OfflineError, no retry)
- cancel_event stops promptly, keeps .part, raises DownloadCancelled
- _ssl_ctx().verify_mode == ssl.CERT_REQUIRED on Linux
- quick_check / quick_check_1p7b ignore .part sidecar files
- ensure_vad is called by the 1.7B download path
"""
from __future__ import annotations

import http.server
import socket
import ssl
import sys
import threading
import time
from pathlib import Path

import pytest

import downloader


# ── Local HTTP test server ────────────────────────────────────────────────────

class _TestServer:
    """A minimal HTTP server that serves a fixed blob, with Range support.

    Args:
        blob: bytes to serve.
        truncate_first_at: if > 0, the FIRST request is truncated after this
            many bytes of *response body* (not counting headers), and the
            connection is closed.  Subsequent requests are served in full.
    """

    def __init__(self, blob: bytes, *, truncate_first_at: int = 0):
        self.blob = blob
        self.truncate_first_at = truncate_first_at
        self.request_count = 0
        self.range_headers: list[str | None] = []
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    @property
    def url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address
        return f"http://127.0.0.1:{port}/blob"

    # ------------------------------------------------------------------
    def __enter__(self) -> "_TestServer":
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # suppress per-request noise
                pass

            def do_GET(self):
                outer.request_count += 1
                req_no = outer.request_count
                range_header = self.headers.get("Range")
                outer.range_headers.append(range_header)

                blob = outer.blob
                start = 0

                if range_header and range_header.startswith("bytes="):
                    start_str = range_header[6:].split("-")[0]
                    start = int(start_str)
                    if start >= len(blob):
                        self.send_response(416)
                        self.end_headers()
                        return
                    body = blob[start:]
                    self.send_response(206)
                    self.send_header(
                        "Content-Range",
                        f"bytes {start}-{len(blob) - 1}/{len(blob)}",
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                else:
                    body = blob
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()

                truncate = outer.truncate_first_at
                if truncate > 0 and req_no == 1:
                    # Send partial data then force-close the connection.
                    self.wfile.write(body[:truncate])
                    try:
                        self.wfile.flush()
                    except Exception:
                        pass
                    # SO_LINGER l_onoff=1 l_linger=0 → RST on close
                    try:
                        import struct
                        self.request.setsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_LINGER,
                            struct.pack("ii", 1, 0),
                        )
                    except Exception:
                        pass
                    self.request.close()
                else:
                    try:
                        self.wfile.write(body)
                    except Exception:
                        pass

        self._server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *args):
        if self._server is not None:
            self._server.shutdown()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _part(dest: Path) -> Path:
    """Return the .part sidecar path for dest."""
    return dest.parent / (dest.name + ".part")


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFullDownload:
    """Full download: file lands at final name; no .part left behind."""

    def test_file_at_final_name(self, tmp_path):
        blob = b"hello world " * 500
        dest = tmp_path / "model.bin"

        with _TestServer(blob) as srv:
            downloader._download_file(srv.url, dest)

        assert dest.read_bytes() == blob, "file content mismatch"
        assert not _part(dest).exists(), ".part file should be gone after success"


class TestRangeResume:
    """Resume from an existing .part sends Range header; appends correctly."""

    def test_sends_range_header(self, tmp_path):
        blob = b"abcdefghij" * 600  # 6000 bytes
        first_chunk = blob[:2000]
        dest = tmp_path / "file.bin"

        # Pre-write .part with first chunk
        _part(dest).write_bytes(first_chunk)

        with _TestServer(blob) as srv:
            downloader._download_file(srv.url, dest)

        assert srv.range_headers[0] == f"bytes={len(first_chunk)}-", (
            "Range header not sent for existing .part"
        )
        assert dest.read_bytes() == blob, "resumed content mismatch"
        assert not _part(dest).exists(), ".part should be renamed away on success"


class TestTransientRetry:
    """Mid-stream failure triggers retry; .part keeps accumulated bytes."""

    def test_retry_completes_after_truncation(self, tmp_path, monkeypatch):
        # Monkeypatch _sleep so retries are instant.
        monkeypatch.setattr(downloader, "_sleep", lambda _: None)

        blob = b"X" * (128 * 1024)   # 128 KB
        truncate_at = 32 * 1024       # server closes after 32 KB on first req

        dest = tmp_path / "model.bin"

        with _TestServer(blob, truncate_first_at=truncate_at) as srv:
            downloader._download_file(srv.url, dest)

        assert dest.read_bytes() == blob, "content mismatch after retry"
        assert not _part(dest).exists(), ".part should be gone after success"
        assert srv.request_count >= 2, "expected at least one retry"


class TestOfflineFastFail:
    """connect-phase refusal → OfflineError immediately, no retries."""

    def test_raises_offline_error(self, tmp_path):
        # Bind to a port then release it so nothing listens there.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        # Port is now closed.

        url = f"http://127.0.0.1:{port}/blob"
        dest = tmp_path / "file.bin"

        sleep_calls: list[float] = []
        monkeypatch_obj = None  # we don't monkeypatch here; just measure time

        t0 = time.monotonic()
        with pytest.raises(downloader.OfflineError):
            downloader._download_file(url, dest)
        elapsed = time.monotonic() - t0

        assert elapsed < 2.0, f"OfflineError should fail fast, took {elapsed:.2f}s"

    def test_no_retries_on_refused(self, tmp_path, monkeypatch):
        """OfflineError must not trigger any backoff sleeps."""
        sleep_calls: list[float] = []
        monkeypatch.setattr(downloader, "_sleep", lambda s: sleep_calls.append(s))

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        url = f"http://127.0.0.1:{port}/blob"
        dest = tmp_path / "file.bin"

        with pytest.raises(downloader.OfflineError):
            downloader._download_file(url, dest)

        assert sleep_calls == [], "_sleep must not be called for offline errors"


class TestCancelEvent:
    """cancel_event set mid-stream: .part survives, DownloadCancelled raised."""

    def test_cancel_keeps_part(self, tmp_path):
        blob = b"Y" * (256 * 1024)  # 256 KB — more than a single 64KB chunk
        cancel_event = threading.Event()
        dest = tmp_path / "data.bin"

        progress_calls = [0]

        def _progress(done, total):
            progress_calls[0] += 1
            if progress_calls[0] >= 1:
                cancel_event.set()

        with _TestServer(blob) as srv:
            with pytest.raises(downloader.DownloadCancelled):
                downloader._download_file(
                    srv.url, dest, progress_cb=_progress, cancel_event=cancel_event
                )

        assert not dest.exists(), "final file must not exist after cancel"
        assert _part(dest).exists(), ".part must survive a cancel"
        # The .part must contain some bytes (at least one chunk was written)
        assert _part(dest).stat().st_size > 0


class TestSSLCtxLinux:
    """On non-win32, _ssl_ctx() must use CERT_REQUIRED (no CERT_NONE fallback)."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows has own SSL rungs")
    def test_verify_mode_is_cert_required(self):
        ctx = downloader._ssl_ctx()
        assert ctx.verify_mode == ssl.CERT_REQUIRED, (
            f"Expected CERT_REQUIRED on Linux, got {ctx.verify_mode!r}"
        )


class TestQuickCheckIgnoresPart:
    """quick_check and quick_check_1p7b ignore .part sidecar files."""

    def test_quick_check_ignores_part(self, tmp_path):
        ov_dir = tmp_path / "qwen3_asr_int8"
        ov_dir.mkdir(parents=True)

        # Place a .part file for one of the required .bin files.
        (ov_dir / "audio_encoder_model.bin.part").write_bytes(b"partial data")

        # quick_check must return False — only the final name counts.
        assert downloader.quick_check(tmp_path) is False

    def test_quick_check_1p7b_ignores_part(self, tmp_path):
        kv_dir = tmp_path / "qwen3_asr_1p7b_kv_int8"
        kv_dir.mkdir(parents=True)

        # Place a .part sidecar.
        (kv_dir / "audio_encoder_model.bin.part").write_bytes(b"partial")

        assert downloader.quick_check_1p7b(tmp_path) is False

    def test_quick_check_1p7b_requires_vad(self, tmp_path):
        """quick_check_1p7b returns False when VAD is absent (ticket-06 invariant)."""
        kv_dir = tmp_path / "qwen3_asr_1p7b_kv_int8"
        kv_dir.mkdir(parents=True)
        # No VAD file created → should be False even with kv dir present.
        assert downloader.quick_check_1p7b(tmp_path) is False


class TestEnsureVadCalledBy1p7b:
    """ensure_vad is called by the 1.7B download path."""

    def test_ensure_vad_invoked(self, tmp_path, monkeypatch):
        called: list[bool] = []

        monkeypatch.setattr(
            downloader, "ensure_vad", lambda *a, **kw: called.append(True)
        )
        # Also stub _download_file so no network is needed.
        monkeypatch.setattr(
            downloader, "_download_file", lambda *a, **kw: None
        )

        downloader.download_1p7b(tmp_path)

        assert called, "ensure_vad was not called by download_1p7b"
