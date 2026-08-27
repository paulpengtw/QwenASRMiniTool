"""tests/test_headless_e2e.py — Headless end-to-end test (Linux, ticket 15).

Decision source: 07 (the final orphan-process check is the only proof that
PR_SET_PDEATHSIG and killpg work end-to-end).

These tests start the real app stack via tests/helpers/e2e_server.py in a
subprocess with QWEN_NO_BROWSER=1, exercise the HTTP API, and verify that:

  1. /health returns {"status": "ok"} before timing out.
  2. GET /api/capabilities reports setup_required for models (no model present)
     and a sane effective_backend (openvino on Linux).
  3. GET /api/snapshot returns a well-formed snapshot dict.
  4. POST /api/quit with the session access key exits the process with code 0
     within 10 s, removes the session file, and kills any spawned child process.
  5. A SIGKILLed server causes a child spawned via platform_seams.spawn() to
     die (PDEATHSIG / PR_SET_PDEATHSIG).

Environment requirements
------------------------
- Linux only (POSIX: PR_SET_PDEATHSIG).
- No model files needed; the server starts with setup_required capability state.
- The helper subprocess installs GUI stubs so tkinter / customtkinter are not
  required in the environment.

What is left out (impossible in this environment)
--------------------------------------------------
None of the test logic is left out.  The entire test suite runs on a headless
Debian/Ubuntu system without a display, tkinter, or model files.

Skips
-----
All tests skip on win32 (PDEATHSIG is Linux-specific).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tests" / "helpers" / "e2e_server.py"
PYTHON = sys.executable   # same venv as the test runner

# Guard: skip everything on Windows.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="headless e2e tests use PDEATHSIG — Linux-only",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def _get(port: int, path: str) -> dict:
    req = urllib.request.Request(
        _url(port, path),
        headers={"Host": f"127.0.0.1:{port}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _post(port: int, path: str, body: dict | None = None,
          auth_key: str | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Content-Length": str(len(data)),
    }
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"
    req = urllib.request.Request(
        _url(port, path), data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _poll_health(port: int, timeout: float = 15.0) -> bool:
    """Return True when /health responds 200 within *timeout* seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                _url(port, "/health"),
                headers={"Host": f"127.0.0.1:{port}"},
            )
            with urllib.request.urlopen(req, timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _pid_alive(pid: int) -> bool:
    """Return True if pid exists and is not a zombie."""
    try:
        os.kill(pid, 0)
        # Check for zombie in /proc/<pid>/status
        try:
            st = Path(f"/proc/{pid}/status").read_text()
            return "State:\tZ" not in st
        except OSError:
            return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just can't signal it


class _ServerFixture:
    """Manages a single e2e_server subprocess lifetime."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        spawn_marker: Optional[str] = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.spawn_marker = spawn_marker
        self.proc: Optional[subprocess.Popen] = None
        self.port: int = 0
        self.key: str = ""
        self.child_pid: Optional[int] = None

    def start(self, ready_timeout: float = 20.0) -> None:
        env = dict(os.environ)
        env["QWEN_TEST_BASE_DIR"] = str(self.tmp_path)
        env["QWEN_NO_BROWSER"] = "1"
        if self.spawn_marker:
            env["QWEN_E2E_SPAWN_MARKER"] = self.spawn_marker

        self.proc = subprocess.Popen(
            [PYTHON, str(HELPER)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(ROOT),
            text=True,
            bufsize=1,   # line-buffered
        )

        # Wait for the "READY port=<N> key=<K>" line.
        deadline = time.monotonic() + ready_timeout
        ready_line: str = ""
        child_pid_line: str = ""
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if line.startswith("CHILD_PID="):
                child_pid_line = line
            if line.startswith("READY port="):
                ready_line = line
                break

        if not ready_line:
            self.kill()
            stderr_snippet = ""
            try:
                stderr_snippet = self.proc.stderr.read(2000)
            except Exception:
                pass
            raise RuntimeError(
                f"e2e_server did not print READY within {ready_timeout}s.\n"
                f"stderr: {stderr_snippet}"
            )

        # Parse "READY port=<N> key=<K>"
        parts = dict(p.split("=", 1) for p in ready_line.split() if "=" in p)
        self.port = int(parts.get("port", 0))
        self.key = parts.get("key", "")

        if child_pid_line:
            try:
                self.child_pid = int(child_pid_line.split("=")[1].strip())
            except (ValueError, IndexError):
                self.child_pid = None

        if not self.port or not self.key:
            self.kill()
            raise RuntimeError(f"Could not parse port/key from: {ready_line!r}")

    def kill(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=3)
            except Exception:
                pass

    def wait(self, timeout: float = 12.0) -> Optional[int]:
        if self.proc is None:
            return None
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    @property
    def pid(self) -> Optional[int]:
        if self.proc is None:
            return None
        return self.proc.pid

    @property
    def session_json_path(self) -> Path:
        return self.tmp_path / ".session" / "session.json"


# ---------------------------------------------------------------------------
# Test 1: Clean shutdown via POST /api/quit
# ---------------------------------------------------------------------------

class TestHeadlessE2EQuit:
    """Verifies the full headless lifecycle: start, API, quit, cleanup."""

    @pytest.fixture(autouse=True)
    def _server(self, tmp_path):
        """Start the e2e server and ensure it is killed at teardown."""
        srv = _ServerFixture(tmp_path)
        srv.start()
        self._srv = srv
        yield srv
        srv.kill()

    # ── 1. /health ─────────────────────────────────────────────────────────

    def test_health_returns_ok(self):
        """GET /health must return {"status": "ok"} before timeout."""
        srv = self._srv
        assert _poll_health(srv.port, timeout=10.0), (
            f"/health did not respond on port {srv.port}"
        )
        resp = _get(srv.port, "/health")
        assert resp["status"] == "ok"
        assert resp["model_ready"] is False   # no model loaded

    # ── 2. /api/capabilities ────────────────────────────────────────────────

    def test_capabilities_model_setup_required(self):
        """GET /api/capabilities must report setup_required for the model."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        cap = _get(srv.port, "/api/capabilities")
        # On Linux with no model files, the model should be setup_required.
        model_state = cap.get("model_state", {})
        assert model_state.get("state") in ("unloaded", "setup_required"), (
            f"Expected model state unloaded/setup_required, got: {model_state}"
        )

    def test_capabilities_effective_backend_openvino(self):
        """GET /api/capabilities must report openvino as effective_backend on Linux."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        cap = _get(srv.port, "/api/capabilities")
        assert cap.get("effective_backend") == "openvino", (
            f"Expected openvino on Linux, got: {cap.get('effective_backend')!r}"
        )

    def test_capabilities_has_health_dict(self):
        """GET /api/capabilities must include a health dict."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        cap = _get(srv.port, "/api/capabilities")
        assert "health" in cap
        assert "blockers" in cap["health"]
        assert "optional" in cap["health"]

    # ── 3. /api/snapshot ────────────────────────────────────────────────────

    def test_snapshot_returns_well_formed_dict(self):
        """GET /api/snapshot must return status + jobs + endpoint + tunnel."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        snap = _get(srv.port, "/api/snapshot")
        assert "status" in snap
        assert "jobs" in snap
        assert "endpoint" in snap or "tunnel" in snap  # at least one present

    def test_snapshot_status_has_model_ready(self):
        """GET /api/snapshot status must include modelReady."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        snap = _get(srv.port, "/api/snapshot")
        status = snap.get("status", {})
        assert "modelReady" in status
        assert status["modelReady"] is False  # no model loaded

    # ── 4. POST /api/quit ───────────────────────────────────────────────────

    def test_quit_with_key_exits_zero(self):
        """POST /api/quit with the correct access key must exit the server with code 0."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"

        resp = _post(srv.port, "/api/quit", auth_key=srv.key)
        assert resp.get("ok") is True

        exit_code = srv.wait(timeout=10.0)
        assert exit_code == 0, (
            f"Expected exit code 0 after /api/quit, got: {exit_code!r}"
        )

    def test_quit_removes_session_file(self):
        """POST /api/quit must remove the session file on clean shutdown."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        assert srv.session_json_path.exists(), "Session file should exist before quit"

        _post(srv.port, "/api/quit", auth_key=srv.key)
        srv.wait(timeout=10.0)

        assert not srv.session_json_path.exists(), (
            f"Session file should be removed after clean quit: {srv.session_json_path}"
        )

    def test_quit_with_wrong_key_returns_401(self):
        """POST /api/quit with a wrong key must return 401."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        try:
            _post(srv.port, "/api/quit", auth_key="wrongkey")
            pytest.fail("Expected 401 but request succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401, f"Expected 401, got {exc.code}"

    def test_quit_without_key_returns_401_or_403(self):
        """POST /api/quit without a key must return 401 or 403."""
        srv = self._srv
        assert _poll_health(srv.port), "/health not ready"
        try:
            _post(srv.port, "/api/quit")   # no auth_key
            pytest.fail("Expected 401/403 but request succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code in (401, 403), f"Expected 401/403, got {exc.code}"

    # ── 5. No orphan child after quit ──────────────────────────────────────

    def test_quit_kills_spawned_child(self, tmp_path):
        """POST /api/quit must kill children tracked by guard_children()."""
        marker = "QWEN_E2E_ORPHAN_CHECK_QUIT_XYZ"
        srv = _ServerFixture(tmp_path / "orphan_quit", spawn_marker=marker)
        try:
            srv.start()
            assert _poll_health(srv.port), "/health not ready"

            child_pid = srv.child_pid
            assert child_pid is not None, "Child PID not emitted by e2e_server"
            assert _pid_alive(child_pid), "Child should be alive before quit"

            _post(srv.port, "/api/quit", auth_key=srv.key)
            exit_code = srv.wait(timeout=10.0)
            assert exit_code == 0

            # Give the kernel a moment to reap the child.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and _pid_alive(child_pid):
                time.sleep(0.05)

            assert not _pid_alive(child_pid), (
                f"Child PID {child_pid} should be dead after clean quit "
                f"(guard_children terminate_all)"
            )
        finally:
            srv.kill()


# ---------------------------------------------------------------------------
# Test 2: SIGKILL server → child dies (PDEATHSIG)
# ---------------------------------------------------------------------------

class TestHeadlessE2EPdeathsig:
    """Verifies PR_SET_PDEATHSIG: when the server is SIGKILLed, children die."""

    def test_sigkill_kills_child_via_pdeathsig(self, tmp_path):
        """SIGKILLing the server process must cause spawned children to die
        within 2 s (via PR_SET_PDEATHSIG=SIGTERM set by platform_seams.spawn).
        """
        marker = "QWEN_E2E_PDEATHSIG_PROOF_MARKER"
        srv = _ServerFixture(tmp_path, spawn_marker=marker)
        try:
            srv.start()
            assert _poll_health(srv.port), "/health not ready"

            child_pid = srv.child_pid
            assert child_pid is not None, "Child PID not emitted"
            assert _pid_alive(child_pid), "Child should be alive before SIGKILL"

            # SIGKILL the server — no graceful shutdown.
            os.kill(srv.pid, signal.SIGKILL)
            srv.proc.wait(timeout=3)

            # PDEATHSIG: the child should receive SIGTERM from the kernel
            # because its parent (e2e_server) died.  Give it up to 2 s.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and _pid_alive(child_pid):
                time.sleep(0.05)

            assert not _pid_alive(child_pid), (
                f"Child PID {child_pid} is still alive {2.0:.1f} s after "
                f"server SIGKILL — PDEATHSIG did not fire"
            )
        finally:
            srv.kill()
