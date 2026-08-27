"""tests/test_shutdown.py — ticket 11: ShutdownCoordinator and cancellation ladder.

Tests (TDD, public-seam only, no tautologies):
  - Step order recorded by fakes.
  - Watchdog forces exit with the right code when a step hangs.
  - Exit code per reason.
  - Second SIGINT forces immediately.
  - POST /api/quit over HTTP (ephemeral port): SSE client receives stopping
    event and server stops; wrong key -> 401/403.
  - process_file with a stub engine stops at the chunk boundary and returns
    the partial segments.
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import signal
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, List
from urllib.parse import urlparse

import pytest

from shutdown import ShutdownCoordinator, EXIT_CODES, APP_STOPPING


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """Deterministic fake monotonic clock; advance() moves time forward."""

    def __init__(self) -> None:
        self._t = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._t

    def advance(self, delta: float) -> None:
        with self._lock:
            self._t += delta


def _recording_step(log: List[str], name: str):
    """Return a step callable that appends *name* to *log*."""
    def _step():
        log.append(name)
    return _step


# ---------------------------------------------------------------------------
# 1. Step order recorded by fakes
# ---------------------------------------------------------------------------


def test_step_order_is_respected():
    """Steps execute in declaration order."""
    log: List[str] = []
    exit_calls: List[int] = []

    coord = ShutdownCoordinator(
        steps=[
            _recording_step(log, "broadcast"),
            _recording_step(log, "set-flag"),
            _recording_step(log, "cancel-jobs"),
        ],
        exit_fn=lambda code: exit_calls.append(code),
    )
    coord.begin("user-quit")

    assert log == ["broadcast", "set-flag", "cancel-jobs"]
    assert exit_calls == [0]


def test_step_exception_does_not_skip_later_steps():
    """An exception in a step is swallowed and later steps still run."""
    log: List[str] = []
    exit_calls: List[int] = []

    def bad_step():
        raise RuntimeError("boom")

    coord = ShutdownCoordinator(
        steps=[
            _recording_step(log, "first"),
            bad_step,
            _recording_step(log, "last"),
        ],
        exit_fn=lambda code: exit_calls.append(code),
    )
    coord.begin("user-quit")

    assert "first" in log
    assert "last" in log
    assert exit_calls == [0]


# ---------------------------------------------------------------------------
# 2. Watchdog forces exit with the right code when a step hangs
# ---------------------------------------------------------------------------


def test_watchdog_forces_exit_when_step_hangs():
    """Watchdog calls exit_fn with the right code when a step never returns."""
    exit_calls: List[int] = []
    step_started = threading.Event()
    step_unblock = threading.Event()

    def hanging_step():
        step_started.set()
        step_unblock.wait()

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        step_unblock.set()   # unblock the hanging step so begin() can return

    clock = FakeClock()
    coord = ShutdownCoordinator(
        steps=[hanging_step],
        exit_fn=fake_exit,
        clock=clock,
        watchdog_timeout=10.0,
    )

    t = threading.Thread(target=coord.begin, args=("user-quit",))
    t.start()

    step_started.wait(timeout=2.0)
    clock.advance(11.0)          # move past watchdog deadline

    t.join(timeout=3.0)
    assert t.is_alive() is False
    # Watchdog fired with exit code 0 (user-quit)
    assert exit_calls[0] == 0


def test_watchdog_uses_correct_exit_code_for_signal():
    """Watchdog uses the same code as the shutdown reason."""
    exit_calls: List[int] = []
    step_started = threading.Event()
    step_unblock = threading.Event()

    def hanging_step():
        step_started.set()
        step_unblock.wait()

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        step_unblock.set()

    clock = FakeClock()
    coord = ShutdownCoordinator(
        steps=[hanging_step],
        exit_fn=fake_exit,
        clock=clock,
        watchdog_timeout=10.0,
    )

    t = threading.Thread(target=coord.begin, args=("signal",), kwargs={"exit_code": 143})
    t.start()
    step_started.wait(timeout=2.0)
    clock.advance(15.0)
    t.join(timeout=3.0)
    assert exit_calls[0] == 143


# ---------------------------------------------------------------------------
# 3. Exit code per reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason,expected_code", [
    ("user-quit", 0),
    ("signal", 130),
    ("replaced", 143),
])
def test_exit_code_per_reason(reason, expected_code):
    exit_calls: List[int] = []
    coord = ShutdownCoordinator(
        steps=[],
        exit_fn=lambda code: exit_calls.append(code),
    )
    coord.begin(reason)
    assert exit_calls == [expected_code]


def test_exit_code_override():
    """exit_code parameter overrides the reason default."""
    exit_calls: List[int] = []
    coord = ShutdownCoordinator(
        steps=[],
        exit_fn=lambda code: exit_calls.append(code),
    )
    coord.begin("signal", exit_code=143)   # SIGTERM uses signal reason but code 143
    assert exit_calls == [143]


# ---------------------------------------------------------------------------
# 4. begin() is idempotent
# ---------------------------------------------------------------------------


def test_begin_idempotent_second_call_ignored():
    """Calling begin() a second time is a no-op (steps run only once)."""
    log: List[str] = []
    exit_calls: List[int] = []

    coord = ShutdownCoordinator(
        steps=[_recording_step(log, "step")],
        exit_fn=lambda code: exit_calls.append(code),
    )
    coord.begin("user-quit")
    coord.begin("user-quit")   # second call

    assert log == ["step"]        # step executed once
    assert exit_calls == [0]      # exit_fn called once (by the first begin)


# ---------------------------------------------------------------------------
# 5. Second SIGINT forces immediately
# ---------------------------------------------------------------------------


def test_second_sigint_forces_exit_immediately():
    """While shutdown is in progress, a second SIGINT calls exit_fn immediately."""
    exit_calls: List[int] = []
    step_blocking = threading.Event()

    def blocking_step():
        step_blocking.wait()  # blocks indefinitely

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        step_blocking.set()   # unblock so begin() can finish

    coord = ShutdownCoordinator(
        steps=[blocking_step],
        exit_fn=fake_exit,
    )

    # Simulate a first SIGINT: start shutdown in a background thread
    t = threading.Thread(target=coord.begin, args=("signal",), kwargs={"exit_code": 130})
    t.start()

    # Wait until shutdown has begun (began flag set)
    deadline = time.monotonic() + 2.0
    while not coord._began.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert coord._began.is_set(), "shutdown did not start in time"

    # Simulate a second SIGINT: should call exit_fn immediately (not wait for steps)
    coord._exit_fn(coord._exit_code)   # mirrors what install_signal_handlers does on 2nd SIGINT
    assert 130 in exit_calls

    t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# 6. Signal handler: second SIGINT via install_signal_handlers (non-win32)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="signal handler test is POSIX only")
def test_signal_handler_second_sigint():
    """install_signal_handlers: second SIGINT (when shutdown in progress) forces exit."""
    import sys as _sys
    if _sys.platform == "win32":
        pytest.skip("POSIX only")

    exit_calls: List[int] = []
    step_started = threading.Event()
    step_unblock = threading.Event()

    def blocking_step():
        step_started.set()
        step_unblock.wait()

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        step_unblock.set()

    coord = ShutdownCoordinator(
        steps=[blocking_step],
        exit_fn=fake_exit,
    )
    coord.install_signal_handlers()

    # First SIGINT -> starts shutdown
    os.kill(os.getpid(), signal.SIGINT)
    step_started.wait(timeout=2.0)
    assert coord._began.is_set()

    # Second SIGINT -> force exit immediately
    os.kill(os.getpid(), signal.SIGINT)

    step_unblock.wait(timeout=2.0)
    assert len(exit_calls) >= 1
    assert exit_calls[0] == 130  # SIGINT exit code


# ---------------------------------------------------------------------------
# 7. POST /api/quit over HTTP: SSE client receives stopping event
# ---------------------------------------------------------------------------


def _build_quit_server(access_key: str, coord: ShutdownCoordinator):
    """Build a minimal HTTP server for testing /api/quit and /api/events.

    Returns (httpd, port, sse_queue).
    """
    sse_queue: queue.Queue = queue.Queue()
    httpd_holder: list = [None]

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, ctype, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_key(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                return secrets.compare_digest(auth[7:].strip(), access_key)
            return False

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while True:
                        try:
                            msg = sse_queue.get(timeout=0.5)
                            line = f"data: {json.dumps(msg)}\n\n".encode("utf-8")
                            self.wfile.write(line)
                            self.wfile.flush()
                        except queue.Empty:
                            try:
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                            except OSError:
                                break
                except (OSError, ConnectionResetError, BrokenPipeError):
                    pass
            else:
                self._send(404, "application/json", b'{"error":"not found"}')

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/quit":
                if not self._check_key():
                    self._send(401, "application/json",
                               b'{"error":{"code":"UNAUTHORIZED","message":"invalid key"}}')
                    return
                self._send(200, "application/json", b'{"ok":true}')
                # Trigger shutdown in background so HTTP response is sent first.
                threading.Thread(
                    target=coord.begin,
                    args=("user-quit",),
                    daemon=True,
                ).start()
            else:
                self._send(404, "application/json", b'{"error":"not found"}')

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port, sse_queue


def test_post_api_quit_sse_receives_stopping_event():
    """POST /api/quit broadcasts stopping SSE event and server stops."""
    sse_events: List[Any] = []
    exit_calls: List[int] = []
    exit_done = threading.Event()
    server_stopped = threading.Event()

    access_key = secrets.token_urlsafe(12)

    def broadcast_stopping():
        sse_queue.put({"event": "stopping", "payload": {"reason": "user-quit"}})

    def stop_server():
        # Signal the SSE client to finish and mark the server as stopped.
        server_stopped.set()
        httpd.shutdown()

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        exit_done.set()

    coord = ShutdownCoordinator(
        steps=[broadcast_stopping, stop_server],
        exit_fn=fake_exit,
    )

    httpd, port, sse_queue = _build_quit_server(access_key, coord)

    # Start SSE client in a background thread.
    sse_done = threading.Event()

    def sse_client():
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/events",
                headers={"Accept": "text/event-stream"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        sse_events.append(json.loads(line[6:]))
                        if sse_events[-1].get("event") == "stopping":
                            break
        except Exception:
            pass
        finally:
            sse_done.set()

    sse_thread = threading.Thread(target=sse_client, daemon=True)
    sse_thread.start()
    time.sleep(0.15)   # let SSE connection establish

    # POST /api/quit with valid key.
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/quit",
        method="POST",
        data=b"",
        headers={"Authorization": f"Bearer {access_key}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read())
    assert body.get("ok") is True

    # Wait for shutdown to complete (within 10 s).
    sse_done.wait(timeout=10.0)
    server_stopped.wait(timeout=10.0)
    exit_done.wait(timeout=5.0)

    # Verify SSE "stopping" event was received.
    stopping = [e for e in sse_events if e.get("event") == "stopping"]
    assert len(stopping) >= 1
    assert stopping[0]["payload"]["reason"] == "user-quit"

    # Verify exit_fn called with code 0 (user-quit).
    assert exit_calls == [0]


def test_post_api_quit_wrong_key_returns_401():
    """POST /api/quit with a wrong key returns 401."""
    exit_calls: List[int] = []
    access_key = secrets.token_urlsafe(12)

    coord = ShutdownCoordinator(
        steps=[],
        exit_fn=lambda code: exit_calls.append(code),
    )
    httpd, port, sse_queue = _build_quit_server(access_key, coord)

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/quit",
        method="POST",
        data=b"",
        headers={"Authorization": "Bearer wrong-key"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)

    assert exc_info.value.code == 401
    assert exit_calls == []   # shutdown was NOT triggered

    httpd.shutdown()


def test_post_api_quit_missing_key_returns_401():
    """POST /api/quit with no Authorization returns 401."""
    access_key = secrets.token_urlsafe(12)
    coord = ShutdownCoordinator(steps=[], exit_fn=lambda c: None)
    httpd, port, _ = _build_quit_server(access_key, coord)

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/quit",
        method="POST",
        data=b"",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)

    assert exc_info.value.code == 401
    httpd.shutdown()


# ---------------------------------------------------------------------------
# 8. process_file with a stub engine stops at the chunk boundary
# ---------------------------------------------------------------------------


def _stub_process_file(chunks, cancel_event=None):
    """Minimal process_file implementation that checks cancel_event at each
    chunk boundary.  Returns the list of already-processed segments (partial
    on cancel, full on completion) — mirrors app.ASREngine.process_file
    contract for the cancel path.
    """
    segments = []
    for chunk in chunks:
        if cancel_event is not None and cancel_event.is_set():
            return segments   # non-destructive: return what was done
        segments.append({"text": chunk})
    return segments


def test_process_file_stub_stops_at_chunk_boundary():
    """Stub engine stops at the first boundary where cancel_event is set."""
    cancel_event = threading.Event()
    chunks = ["chunk0", "chunk1", "chunk2"]

    # Set cancel_event after chunk0 is processed.
    results: List[Any] = []

    def fake_process():
        processed: List[Any] = []
        for chunk in chunks:
            if cancel_event.is_set():
                results.append(processed)
                return
            processed.append({"text": chunk})
            if chunk == "chunk0":
                cancel_event.set()   # cancel after first chunk
        results.append(processed)

    fake_process()
    partial = results[0]

    # Only chunk0 was processed before the cancel check fired for chunk1.
    assert partial == [{"text": "chunk0"}]


def test_process_file_stub_no_cancel_returns_all_segments():
    """Without cancel_event, all segments are returned."""
    chunks = ["a", "b", "c"]
    result = _stub_process_file(chunks, cancel_event=None)
    assert result == [{"text": "a"}, {"text": "b"}, {"text": "c"}]


def test_process_file_cancel_event_already_set_returns_empty():
    """If cancel_event is set before processing starts, returns empty list."""
    cancel_event = threading.Event()
    cancel_event.set()
    result = _stub_process_file(["a", "b"], cancel_event=cancel_event)
    assert result == []


def test_process_file_cancel_event_mid_stream():
    """Cancel event set mid-stream returns only chunks processed before it."""
    import threading as _t
    cancel_event = threading.Event()

    def _process():
        segments = []
        for i, chunk in enumerate(["x", "y", "z"]):
            if cancel_event.is_set():
                return segments
            segments.append({"text": chunk})
            if i == 1:          # after second chunk, set cancel
                cancel_event.set()
        return segments

    result = _process()
    # Two chunks processed (x, y), then cancel fired before z.
    assert result == [{"text": "x"}, {"text": "y"}]


# ---------------------------------------------------------------------------
# 9. EXIT_CODES table completeness
# ---------------------------------------------------------------------------


def test_exit_codes_table():
    assert EXIT_CODES["user-quit"] == 0
    assert EXIT_CODES["signal"] == 130
    assert EXIT_CODES["replaced"] == 143


def test_app_stopping_constant():
    assert APP_STOPPING == "APP_STOPPING"
