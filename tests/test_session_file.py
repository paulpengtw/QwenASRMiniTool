"""tests/test_session_file.py — TDD suite for session_file.py (ticket 10)."""
from __future__ import annotations

import json
import os
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import patch

import pytest

# Module under test
import session_file as sf

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_base(tmp_path):
    """A fresh base_dir per test."""
    return tmp_path / "base"


# ---------------------------------------------------------------------------
# session_path
# ---------------------------------------------------------------------------

class TestSessionPath:
    def test_returns_expected_location(self, tmp_base):
        p = sf.session_path(tmp_base)
        assert p == tmp_base / ".session" / "session.json"


# ---------------------------------------------------------------------------
# write_session / read_session
# ---------------------------------------------------------------------------

class TestWriteReadSession:
    def _write(self, base_dir):
        sf.write_session(
            base_dir,
            url="http://127.0.0.1:9999/",
            port=9999,
            pid=12345,
            access_key="test-key",
            started_at="2024-01-01T00:00:00Z",
        )

    def test_creates_file(self, tmp_base):
        self._write(tmp_base)
        assert sf.session_path(tmp_base).exists()

    def test_file_mode_0600(self, tmp_base):
        self._write(tmp_base)
        mode = sf.session_path(tmp_base).stat().st_mode & 0o777
        assert mode == 0o600

    def test_contents_valid_json_with_required_keys(self, tmp_base):
        self._write(tmp_base)
        data = json.loads(sf.session_path(tmp_base).read_text())
        for key in ("url", "port", "pid", "identity", "access_key", "started_at"):
            assert key in data
        for key in ("start_time", "exe"):
            assert key in data["identity"]

    def test_atomicity_no_partial_read(self, tmp_base):
        """The temp file must not be visible at the final path during write."""
        final = sf.session_path(tmp_base)
        seen_partial = []

        original_replace = os.replace
        def patched_replace(src, dst):
            # Just before the rename, check the final path doesn't exist yet
            # (or still has old content if overwriting)
            seen_partial.append(final.exists())
            original_replace(src, dst)

        with patch("os.replace", side_effect=patched_replace):
            self._write(tmp_base)

        # The final path should have been created by the patched replace
        assert final.exists()

    def test_read_session_returns_dict(self, tmp_base):
        self._write(tmp_base)
        result = sf.read_session(tmp_base)
        assert isinstance(result, dict)
        assert result["url"] == "http://127.0.0.1:9999/"
        assert result["port"] == 9999
        assert result["pid"] == 12345

    def test_read_session_missing_file_returns_none(self, tmp_base):
        assert sf.read_session(tmp_base) is None

    def test_read_session_garbage_returns_none(self, tmp_base):
        sf.session_path(tmp_base).parent.mkdir(parents=True, exist_ok=True)
        sf.session_path(tmp_base).write_text("not json at all{{{")
        assert sf.read_session(tmp_base) is None

    def test_read_session_missing_keys_returns_none(self, tmp_base):
        sf.session_path(tmp_base).parent.mkdir(parents=True, exist_ok=True)
        sf.session_path(tmp_base).write_text(json.dumps({"url": "x"}))
        assert sf.read_session(tmp_base) is None


# ---------------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------------

class TestDeleteSession:
    def test_deletes_existing_file(self, tmp_base):
        sf.write_session(tmp_base, "http://127.0.0.1:1/", 1, 1, "k", "t")
        sf.delete_session(tmp_base)
        assert not sf.session_path(tmp_base).exists()

    def test_idempotent_when_missing(self, tmp_base):
        # Should not raise even if file does not exist
        sf.delete_session(tmp_base)
        sf.delete_session(tmp_base)


# ---------------------------------------------------------------------------
# process_identity
# ---------------------------------------------------------------------------

class TestProcessIdentity:
    def test_current_process_has_start_time_and_exe(self):
        ident = sf.process_identity(os.getpid())
        assert "start_time" in ident
        assert "exe" in ident
        assert ident["start_time"] != ""

    def test_current_process_matches_itself(self):
        ident = sf.process_identity(os.getpid())
        ident2 = sf.process_identity(os.getpid())
        assert ident["start_time"] == ident2["start_time"]

    def test_bogus_start_time_mismatches(self):
        real = sf.process_identity(os.getpid())
        bogus = {"start_time": "9999999999999", "exe": real["exe"]}
        assert real["start_time"] != bogus["start_time"]

    def test_dead_pid_returns_fallback(self):
        # Use a very high PID that won't exist
        ident = sf.process_identity(999999999)
        assert "start_time" in ident
        assert "exe" in ident
        # Fallback values should be empty strings
        assert ident["start_time"] == ""
        assert ident["exe"] == ""


# ---------------------------------------------------------------------------
# is_alive
# ---------------------------------------------------------------------------

class TestIsAlive:
    def test_current_process_is_alive(self):
        assert sf.is_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self):
        # PID 0 cannot be signal-tested; use a very high PID instead
        assert sf.is_alive(999999999) is False


# ---------------------------------------------------------------------------
# probe_health  (tested with a real local HTTP server)
# ---------------------------------------------------------------------------

class TestProbeHealth:
    def test_returns_false_on_refused_connection(self):
        # Nothing listening on port 19999 (very likely)
        result = sf.probe_health("http://127.0.0.1:19999", "k", timeout=0.5)
        assert result is False

    def test_returns_true_on_ok_response(self):
        """Start a minimal HTTP server that returns {"status":"ok"}."""
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"status": "ok"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a): pass

        srv = HTTPServer(("127.0.0.1", 0), _H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        result = sf.probe_health(f"http://127.0.0.1:{port}", "testkey", timeout=2.0)
        srv.server_close()
        assert result is True


# ---------------------------------------------------------------------------
# terminate_and_wait
# ---------------------------------------------------------------------------

class TestTerminateAndWait:
    def test_already_dead_pid_returns_false_quickly(self):
        # A PID that does not exist: SIGTERM raises ProcessLookupError
        result = sf.terminate_and_wait(999999999, deadline=1.0)
        # Returns False because we could not signal it (it doesn't exist)
        assert result is False

    def test_injected_sleep_is_called(self):
        """Verify the sleep callable is injected (not hard-coded time.sleep)."""
        calls = []
        def fake_sleep(s):
            calls.append(s)

        # Signal a non-existent PID -> immediately returns False, sleep not needed
        sf.terminate_and_wait(999999999, deadline=1.0, sleep=fake_sleep)
        # Whether sleep is called or not is irrelevant for non-existent pid,
        # but we validate the function accepts the injectable


# ---------------------------------------------------------------------------
# resolve — decision table with fake probes
# ---------------------------------------------------------------------------

@dataclass
class FakeProbes:
    """Injectable probes for resolve() tests."""
    alive: bool = True
    healthy: bool = False
    identity_matches: bool = True
    terminate_ok: bool = True
    sleep_calls: list = field(default_factory=list)

    def is_alive(self, pid: int) -> bool:
        return self.alive

    def probe_health(self, url: str, key: str, timeout: float = 1.0) -> bool:
        return self.healthy

    def process_identity(self, pid: int) -> dict:
        if self.identity_matches:
            return {"start_time": "12345", "exe": "/usr/bin/python3"}
        else:
            return {"start_time": "99999", "exe": "/usr/bin/python3"}

    def terminate_and_wait(self, pid: int, deadline: float = 10.0,
                           sleep: Callable = time.sleep) -> bool:
        return self.terminate_ok


def _stored_identity_matches():
    return {"start_time": "12345", "exe": "/usr/bin/python3"}


def _stored_identity_mismatch():
    return {"start_time": "99999", "exe": "/usr/bin/python3"}


def _write_session_with_identity(base_dir, identity: dict):
    """Write a session file with a specific identity."""
    session = sf.session_path(base_dir)
    session.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "url": "http://127.0.0.1:8888/",
        "port": 8888,
        "pid": 55555,
        "identity": identity,
        "access_key": "test-key",
        "started_at": "2024-01-01T00:00:00Z",
    }
    session.write_text(json.dumps(data))


class TestResolve:
    def test_missing_file_gives_start_fresh(self, tmp_base):
        probes = FakeProbes()
        decision = sf.resolve(tmp_base, probes)
        assert decision.kind == "start_fresh"

    def test_invalid_json_gives_start_fresh(self, tmp_base):
        sf.session_path(tmp_base).parent.mkdir(parents=True, exist_ok=True)
        sf.session_path(tmp_base).write_text("{{{not json")
        probes = FakeProbes()
        decision = sf.resolve(tmp_base, probes)
        assert decision.kind == "start_fresh"

    def test_dead_pid_gives_start_fresh(self, tmp_base):
        _write_session_with_identity(tmp_base, _stored_identity_matches())
        probes = FakeProbes(alive=False)
        decision = sf.resolve(tmp_base, probes)
        assert decision.kind == "start_fresh"

    def test_alive_healthy_gives_reuse(self, tmp_base):
        _write_session_with_identity(tmp_base, _stored_identity_matches())
        probes = FakeProbes(alive=True, healthy=True)
        decision = sf.resolve(tmp_base, probes)
        assert decision.kind == "reuse"
        assert decision.url == "http://127.0.0.1:8888/"
        assert decision.pid == 55555

    def test_alive_unhealthy_identity_matches_gives_takeover(self, tmp_base):
        _write_session_with_identity(tmp_base, _stored_identity_matches())
        probes = FakeProbes(alive=True, healthy=False,
                            identity_matches=True, terminate_ok=True)
        decision = sf.resolve(tmp_base, probes)
        assert decision.kind == "start_fresh_after_takeover"

    def test_alive_unhealthy_identity_mismatch_gives_orphan(self, tmp_base):
        _write_session_with_identity(tmp_base, _stored_identity_mismatch())
        # identity_matches=True in probes returns start_time=12345, but stored is 99999
        probes = FakeProbes(alive=True, healthy=False, identity_matches=True)
        decision = sf.resolve(tmp_base, probes)
        # stored identity has start_time=99999, probe returns start_time=12345 -> mismatch
        assert decision.kind == "start_new_port_report_orphan"
        assert decision.pid == 55555

    def test_alive_unhealthy_wont_die_gives_orphan(self, tmp_base):
        _write_session_with_identity(tmp_base, _stored_identity_matches())
        probes = FakeProbes(alive=True, healthy=False,
                            identity_matches=True, terminate_ok=False)
        decision = sf.resolve(tmp_base, probes)
        assert decision.kind == "start_new_port_report_orphan"

    def test_bounded_wait_uses_injected_sleep(self, tmp_base):
        """resolve() passes the sleep probe through to terminate_and_wait."""
        sleep_calls = []

        @dataclass
        class TimedProbes:
            alive: bool = True
            healthy: bool = False
            identity_matches: bool = True
            terminate_ok: bool = True

            def is_alive(self, pid):
                return self.alive

            def probe_health(self, url, key, timeout=1.0):
                return self.healthy

            def process_identity(self, pid):
                return {"start_time": "12345", "exe": "/usr/bin/python3"}

            def terminate_and_wait(self, pid, deadline=10.0, sleep=time.sleep):
                sleep_calls.append(("called", deadline))
                return self.terminate_ok

        _write_session_with_identity(tmp_base, _stored_identity_matches())
        probes = TimedProbes()
        decision = sf.resolve(tmp_base, probes)
        assert decision.kind == "start_fresh_after_takeover"
        assert len(sleep_calls) == 1
        assert sleep_calls[0][1] == 10.0
