"""tests/test_api_server_stop.py — TDD tests for g3: APP_STOPPING refusal gate
and caller-disconnect cancellation in TranscribeServer.

Decision docs 11 (endpoint requests are connection-bound registry entries
occupying the single inference slot; auto-cancelled at the next chunk boundary
on caller disconnect; on shutdown new requests are refused and in-flight ones
cancelled and answered with a 503-style JSON error before the listener closes)
and 02/10 (stopping order).
"""
from __future__ import annotations

import io
import json
import socket
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import urllib.error


# ---------------------------------------------------------------------------
# Helpers: minimal multipart body builder
# ---------------------------------------------------------------------------

BOUNDARY = b"testboundary1234"


def _make_multipart(filename: str, data: bytes) -> bytes:
    """Build a minimal multipart/form-data body with one 'file' field."""
    return (
        b"--" + BOUNDARY + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="' + filename.encode() + b'"\r\n'
        b"Content-Type: audio/wav\r\n"
        b"\r\n"
        + data
        + b"\r\n"
        b"--" + BOUNDARY + b"--\r\n"
    )


# ---------------------------------------------------------------------------
# Stub engine
# ---------------------------------------------------------------------------

class StubEngine:
    """Minimal engine stub used by api_server tests.

    process_file() calls progress_cb(i, total, msg) once per fake chunk and
    honours cancel_event at each chunk boundary.  It records whether the event
    was observed so tests can assert on it.
    """

    ready = True
    cancel_observed: bool = False

    def __init__(
        self,
        n_chunks: int = 5,
        chunk_delay: float = 0.05,
    ) -> None:
        self.n_chunks = n_chunks
        self.chunk_delay = chunk_delay
        self._calls: List[Dict[str, Any]] = []

    def process_file(
        self,
        audio_path,
        *,
        progress_cb=None,
        language=None,
        diarize=False,
        n_speakers=None,
        original_path=None,
        out_format=None,
        cancel_event=None,
    ) -> "Path | None":
        self._calls.append({"audio_path": audio_path})
        for i in range(self.n_chunks):
            if cancel_event is not None and cancel_event.is_set():
                self.cancel_observed = True
                return None  # partial: no output file
            if progress_cb:
                progress_cb(i, self.n_chunks, f"chunk {i+1}/{self.n_chunks}")
            time.sleep(self.chunk_delay)
        # Return a fake SRT file path (doesn't need to exist for most tests)
        return audio_path  # sentinel


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(engine, stopping=None, registry=None):
    """Start a TranscribeServer on a free port; return (server, url_base)."""
    from api_server import TranscribeServer

    port = _free_port()
    srv = TranscribeServer(
        get_engine=lambda: engine,
        port=port,
        host="127.0.0.1",  # loopback-only for tests
        token="testtoken",
        registry=registry,
    )
    if stopping is not None:
        srv.stopping = stopping
    srv.start()
    return srv, f"http://127.0.0.1:{port}"


def _post_transcribe(url_base: str, audio_data: bytes = b"\x00" * 44) -> urllib.request.Request:
    body = _make_multipart("test.wav", audio_data)
    req = urllib.request.Request(
        url_base + "/v1/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={BOUNDARY.decode()}",
            "Authorization": "Bearer testtoken",
        },
    )
    return req


# ===========================================================================
# Tests
# ===========================================================================


class TestAppStoppingRefusal:
    """New /v1/audio/transcriptions requests during shutdown get 503 APP_STOPPING."""

    def test_new_request_during_stopping_returns_503(self):
        stopping = threading.Event()
        stopping.set()  # already stopping before the request arrives
        engine = StubEngine()
        srv, base = _start_server(engine, stopping=stopping)
        try:
            req = _post_transcribe(base)
            try:
                urllib.request.urlopen(req)
                assert False, "expected HTTPError 503"
            except urllib.error.HTTPError as exc:
                assert exc.code == 503, f"expected 503, got {exc.code}"
                body = json.loads(exc.read())
                assert body["error"]["code"] == "APP_STOPPING", body
        finally:
            srv.stop()

    def test_normal_request_when_not_stopping_is_not_refused(self):
        """Sanity: when stopping is NOT set, request proceeds (may fail for other reasons)."""
        stopping = threading.Event()
        engine = StubEngine()
        srv, base = _start_server(engine, stopping=stopping)
        try:
            req = _post_transcribe(base)
            try:
                resp = urllib.request.urlopen(req)
                # Some response arrived (could be 200 or model-not-ready, doesn't matter)
                assert resp.status in (200,)
            except urllib.error.HTTPError as exc:
                # 503 with APP_STOPPING must NOT appear
                if exc.code == 503:
                    body = json.loads(exc.read())
                    assert body.get("error", {}).get("code") != "APP_STOPPING", (
                        "should not be refused when not stopping"
                    )
        finally:
            srv.stop()


class TestCallerDisconnectCancellation:
    """Engine observes cancel_event within a few chunks when caller disconnects."""

    def test_disconnect_sets_cancel_event(self):
        """Closing the client connection mid-request triggers cancel_event in the engine."""
        engine = StubEngine(n_chunks=10, chunk_delay=0.1)
        srv, base = _start_server(engine)
        try:
            # Open a raw TCP connection, send the HTTP request, then close early
            port = srv._port
            body = _make_multipart("test.wav", b"\x00" * 44)
            http_req = (
                f"POST /v1/audio/transcriptions HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Authorization: Bearer testtoken\r\n"
                f"Content-Type: multipart/form-data; boundary={BOUNDARY.decode()}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + body

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", port))
            sock.sendall(http_req)
            # Give the server a moment to start processing (1st chunk boundary)
            time.sleep(0.15)
            # Abruptly close the connection (caller disconnect)
            sock.close()

            # Wait for the engine to observe the cancel event
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if engine.cancel_observed:
                    break
                time.sleep(0.05)

            assert engine.cancel_observed, (
                "engine did not observe cancel_event within 2 s of caller disconnect"
            )
        finally:
            srv.stop()


class TestRegistryEndpointEntry:
    """Endpoint requests are registered as 'endpoint' kind in the job registry."""

    def test_request_registered_as_endpoint_kind(self):
        """When a registry is attached, new requests create an 'endpoint' job."""
        from job_registry import JobRegistry

        registry = JobRegistry()
        engine = StubEngine(n_chunks=2, chunk_delay=0.0)
        srv, base = _start_server(engine, registry=registry)
        try:
            req = _post_transcribe(base)
            try:
                urllib.request.urlopen(req)
            except urllib.error.HTTPError:
                pass  # SRT parsing may fail, we only care about registry entry

            # Wait briefly for the job to be submitted
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                snap = registry.snapshot()
                if snap["jobs"]:
                    break
                time.sleep(0.05)

            snap = registry.snapshot()
            assert snap["jobs"], "expected at least one job in registry"
            assert snap["jobs"][0]["kind"] == "endpoint", (
                f"expected kind='endpoint', got {snap['jobs'][0]['kind']!r}"
            )
        finally:
            srv.stop()


class TestDisconnectRegistryEntry:
    """On caller disconnect, registry entry ends cancelled with metadata only (no segments)."""

    def test_disconnect_entry_is_cancelled_no_segments(self):
        from job_registry import JobRegistry

        registry = JobRegistry()
        engine = StubEngine(n_chunks=10, chunk_delay=0.1)
        srv, base = _start_server(engine, registry=registry)
        try:
            port = srv._port
            body = _make_multipart("test.wav", b"\x00" * 44)
            http_req = (
                f"POST /v1/audio/transcriptions HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Authorization: Bearer testtoken\r\n"
                f"Content-Type: multipart/form-data; boundary={BOUNDARY.decode()}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + body

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", port))
            sock.sendall(http_req)
            # Give server time to start and create the registry entry
            time.sleep(0.15)
            sock.close()  # abrupt disconnect

            # Wait for the registry entry to reach cancelled state
            deadline = time.monotonic() + 2.0
            job_dict = None
            while time.monotonic() < deadline:
                snap = registry.snapshot()
                if snap["jobs"] and snap["jobs"][0]["state"] == "cancelled":
                    job_dict = snap["jobs"][0]
                    break
                time.sleep(0.05)

            assert job_dict is not None, "registry entry never reached 'cancelled' state"
            assert job_dict["segments"] == [], (
                f"partial segments should be discarded; got {job_dict['segments']}"
            )
            assert job_dict["kind"] == "endpoint"
        finally:
            srv.stop()


class TestShutdownInFlightCancelled:
    """Setting stopping mid-request causes the in-flight request to receive a 503 error."""

    def test_inflight_request_gets_error_on_shutdown(self):
        """Setting stopping.set() while a request is processing cancels it with a 503."""
        stopping = threading.Event()
        engine = StubEngine(n_chunks=10, chunk_delay=0.1)
        srv, base = _start_server(engine, stopping=stopping)

        results: Dict[str, Any] = {}

        def _do_request():
            req = _post_transcribe(base)
            try:
                urllib.request.urlopen(req)
                results["status"] = 200
            except urllib.error.HTTPError as exc:
                results["status"] = exc.code
                try:
                    results["body"] = json.loads(exc.read())
                except Exception:
                    results["body"] = {}

        t = threading.Thread(target=_do_request, daemon=True)
        t.start()

        # Let the request start processing
        time.sleep(0.15)
        # Set stopping — mimics the coordinator step
        stopping.set()
        srv.cancel_inflight()  # coordinator calls this

        t.join(timeout=3.0)
        assert not t.is_alive(), "request thread did not complete"
        assert results.get("status") in (503, 499), (
            f"expected 503 or 499 from in-flight shutdown, got {results}"
        )
        body = results.get("body", {})
        assert body.get("error", {}).get("code") == "APP_STOPPING", body
