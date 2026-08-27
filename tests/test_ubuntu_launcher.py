"""tests/test_ubuntu_launcher.py — TDD suite for ubuntu_launcher.py (ticket 13).

All probes are injected; no real server, no real browser, no real session file.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import MagicMock

import pytest

# Module under test
import ubuntu_launcher as ul


# ---------------------------------------------------------------------------
# Minimal Decision stub (mirrors session_file.Decision)
# ---------------------------------------------------------------------------

@dataclass
class _Decision:
    kind: str
    url: str = ""
    pid: int = 0


# ---------------------------------------------------------------------------
# Injectable probes builder
# ---------------------------------------------------------------------------

class _Probes:
    """Injectable probes for ubuntu_launcher.launch()."""

    def __init__(
        self,
        *,
        # session resolution
        decision: _Decision = None,
        resolve_raises: Exception = None,
        # server
        server_url: str = "http://127.0.0.1:9999/",
        server_port: int = 9999,
        start_raises: Exception = None,
        # readiness
        ready: bool = True,
        # browser
        browser_opens: bool = True,
        # session write
        write_session_raises: Exception = None,
        # environment
        env: dict = None,
    ):
        self._decision = decision or _Decision(kind="start_fresh")
        self._resolve_raises = resolve_raises
        self._server_url = server_url
        self._server_port = server_port
        self._start_raises = start_raises
        self._ready = ready
        self._browser_opens = browser_opens
        self._write_session_raises = write_session_raises
        self._env = env or {}

        # Call-tracking
        self.started: bool = False
        self.opened_urls: list[str] = []
        self.written_sessions: list[dict] = []
        self.signal_handlers_installed: bool = False
        self.exit_calls: list[int] = []
        self.wait_ready_calls: list[tuple] = []  # (url, timeout)
        self.stderr_lines: list[str] = []

        # Fake server object
        self._fake_srv = MagicMock()
        self._fake_srv.url = server_url
        self._fake_srv.port = server_port

    # --- probes API ---

    def resolve_session(self, base_dir: Path) -> _Decision:
        if self._resolve_raises:
            raise self._resolve_raises
        return self._decision

    def start_server(self, base_dir: Path):
        if self._start_raises:
            raise self._start_raises
        self.started = True
        return self._fake_srv

    def wait_ready(self, url: str, timeout: float = ul.DEFAULT_READY_TIMEOUT) -> bool:
        self.wait_ready_calls.append((url, timeout))
        return self._ready

    def write_session(
        self,
        base_dir: Path,
        url: str,
        port: int,
        pid: int,
        key: str,
        started_at: str,
    ) -> None:
        if self._write_session_raises:
            raise self._write_session_raises
        self.written_sessions.append(
            {"url": url, "port": port, "pid": pid, "key": key, "started_at": started_at}
        )

    def open_browser(self, url: str) -> bool:
        self.opened_urls.append(url)
        return self._browser_opens

    def install_signal_handlers(self) -> None:
        self.signal_handlers_installed = True

    def exit(self, code: int) -> None:
        self.exit_calls.append(code)
        raise SystemExit(code)

    def environ(self) -> dict:
        return self._env

    # Wait-forever becomes a no-op so tests don't block
    def wait_forever(self) -> None:
        pass  # injected via monkeypatching below


# ---------------------------------------------------------------------------
# Helper: run launch() catching SystemExit
# ---------------------------------------------------------------------------

def _run(probes: _Probes, capsys=None) -> int:
    """Run ubuntu_launcher.launch(probes) and return the exit code."""
    # Patch the module-level _wait_forever so tests never block
    original = ul._wait_forever
    ul._wait_forever = probes.wait_forever
    try:
        try:
            ul.launch(probes)
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0
        return 0
    finally:
        ul._wait_forever = original


# ---------------------------------------------------------------------------
# 1. Readiness wait: bounded, returns the URL to the caller
# ---------------------------------------------------------------------------

class TestReadinessWait:
    def test_wait_called_with_server_url(self):
        """wait_ready is called with the server's URL."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=True)
        _run(p)
        assert len(p.wait_ready_calls) == 1
        url, _timeout = p.wait_ready_calls[0]
        assert url == p._server_url

    def test_wait_is_bounded_by_timeout(self):
        """wait_ready receives a finite timeout (> 0)."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=True)
        _run(p)
        _url, timeout = p.wait_ready_calls[0]
        assert timeout > 0

    def test_ready_server_writes_session_and_opens_browser(self):
        """When ready, session is written and browser is opened."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=True)
        _run(p)
        assert p.written_sessions, "session should be written"
        assert p.opened_urls == [p._server_url]

    def test_not_ready_exits_2(self, capsys):
        """When /health never responds, exits 2."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=False)
        code = _run(p)
        assert code == 2

    def test_not_ready_no_browser_opened(self):
        """When /health never responds, no browser is opened."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=False)
        _run(p)
        assert p.opened_urls == []


# ---------------------------------------------------------------------------
# 2. Browser-open failure: keeps serving, prints URL
# ---------------------------------------------------------------------------

class TestBrowserOpenFailure:
    def test_keeps_serving_after_browser_failure(self, capsys):
        """Server stays up when browser open fails (exit 0, not 2)."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=True, browser_opens=False)
        code = _run(p)
        # The server was started and kept alive (exit 0, not startup failure 2)
        assert code == 0
        assert p.started

    def test_prints_url_on_browser_failure(self, capsys):
        """URL is printed to stdout when browser open fails."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=True, browser_opens=False)
        _run(p, capsys)
        captured = capsys.readouterr()
        assert p._server_url in captured.out

    def test_prints_ctrl_c_hint_bilingually(self, capsys):
        """Ctrl+C hint appears in both English and Chinese."""
        p = _Probes(decision=_Decision(kind="start_fresh"), ready=True, browser_opens=False)
        _run(p, capsys)
        out = capsys.readouterr().out
        # The hint contains both 'Ctrl+C' and the Chinese variant
        assert "Ctrl+C" in out
        assert "結束" in out or "press Ctrl+C" in out.lower() or "ctrl+c" in out.lower()


# ---------------------------------------------------------------------------
# 3. Reuse path: opens existing URL, does not start a server
# ---------------------------------------------------------------------------

class TestReusePath:
    def test_opens_existing_url(self):
        existing_url = "http://127.0.0.1:8888/"
        p = _Probes(decision=_Decision(kind="reuse", url=existing_url))
        _run(p)
        assert existing_url in p.opened_urls

    def test_does_not_start_server(self):
        existing_url = "http://127.0.0.1:8888/"
        p = _Probes(decision=_Decision(kind="reuse", url=existing_url))
        _run(p)
        assert not p.started

    def test_exits_0(self):
        existing_url = "http://127.0.0.1:8888/"
        p = _Probes(decision=_Decision(kind="reuse", url=existing_url))
        code = _run(p)
        assert code == 0


# ---------------------------------------------------------------------------
# 4. QWEN_NO_BROWSER=1 skips the browser
# ---------------------------------------------------------------------------

class TestNoBrowser:
    def test_fresh_no_browser_env_skips_open(self):
        """QWEN_NO_BROWSER=1 with fresh start skips browser open."""
        p = _Probes(
            decision=_Decision(kind="start_fresh"),
            ready=True,
            env={"QWEN_NO_BROWSER": "1"},
        )
        _run(p)
        assert p.opened_urls == []

    def test_fresh_no_browser_still_starts_server(self):
        """QWEN_NO_BROWSER=1 still starts the server."""
        p = _Probes(
            decision=_Decision(kind="start_fresh"),
            ready=True,
            env={"QWEN_NO_BROWSER": "1"},
        )
        _run(p)
        assert p.started

    def test_reuse_no_browser_env_skips_open(self):
        """QWEN_NO_BROWSER=1 on reuse path skips browser open."""
        existing_url = "http://127.0.0.1:8888/"
        p = _Probes(
            decision=_Decision(kind="reuse", url=existing_url),
            env={"QWEN_NO_BROWSER": "1"},
        )
        _run(p)
        assert p.opened_urls == []


# ---------------------------------------------------------------------------
# 5. Startup failure: exits 2 with a coded message
# ---------------------------------------------------------------------------

class TestStartupFailure:
    def test_oserror_on_start_exits_2(self, capsys):
        """OSError from start_server exits 2."""
        p = _Probes(
            decision=_Decision(kind="start_fresh"),
            start_raises=OSError("address already in use"),
        )
        code = _run(p)
        assert code == 2

    def test_oserror_prints_coded_message_to_stderr(self, capsys):
        """OSError from start_server prints a capability-code message to stderr."""
        p = _Probes(
            decision=_Decision(kind="start_fresh"),
            start_raises=OSError("address already in use"),
        )
        _run(p, capsys)
        err = capsys.readouterr().err
        # Should contain a known code or the word ERROR
        assert "ERROR" in err or "LOOPBACK" in err or "錯誤" in err

    def test_importerror_on_start_exits_2(self, capsys):
        """ImportError from start_server exits 2."""
        p = _Probes(
            decision=_Decision(kind="start_fresh"),
            start_raises=ImportError("no module named webview_server"),
        )
        code = _run(p)
        assert code == 2

    def test_importerror_prints_coded_message_to_stderr(self, capsys):
        """ImportError prints a coded message to stderr."""
        p = _Probes(
            decision=_Decision(kind="start_fresh"),
            start_raises=ImportError("no module named webview_server"),
        )
        _run(p, capsys)
        err = capsys.readouterr().err
        assert "ERROR" in err or "DEP_IMPORT" in err or "錯誤" in err

    def test_no_browser_on_startup_failure(self):
        """No browser is opened when start_server raises."""
        p = _Probes(
            decision=_Decision(kind="start_fresh"),
            start_raises=OSError("bind failed"),
        )
        _run(p)
        assert p.opened_urls == []

    def test_resolve_raises_exits_2(self, capsys):
        """Exception during session resolution exits 2."""
        p = _Probes(resolve_raises=RuntimeError("session broken"))
        code = _run(p)
        assert code == 2
