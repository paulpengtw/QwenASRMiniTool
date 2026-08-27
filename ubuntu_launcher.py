"""ubuntu_launcher.py — Ubuntu browser-based launcher (non-win32 path).

The Windows launch path (app_webview.py / pywebview / Edge) is byte-for-byte
unchanged.  This module is the non-win32 entry point, called by run.sh on Linux.

Decision sources:
  02 — launch waits for app readiness before opening a browser; on failure keep
       serving, print URL and Ctrl+C instructions; startup failure exits non-zero.
  04 — three owners; run.sh gate; bilingual messages.
  07 — clean-VM manual scenario ending with orphan check.
  10 — reuse/takeover via the session file.
"""
from __future__ import annotations

import datetime
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Exit codes (decision 02)
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_STARTUP_FAILURE = 2
EXIT_CTRL_C = 130

# ---------------------------------------------------------------------------
# Readiness-polling defaults (injectable for tests)
# ---------------------------------------------------------------------------
DEFAULT_READY_TIMEOUT = 30.0    # seconds
DEFAULT_POLL_INTERVAL = 0.25    # seconds


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _default_base_dir() -> Path:
    return Path(__file__).resolve().parent


def _wait_ready_default(url: str, timeout: float = DEFAULT_READY_TIMEOUT) -> bool:
    """Poll /health until it responds 200 or the timeout expires."""
    import urllib.request

    health = url.rstrip("/") + "/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(DEFAULT_POLL_INTERVAL)
    return False


def _wait_forever() -> None:
    """Block until KeyboardInterrupt (Ctrl+C).  Injectable for testing."""
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


def _print_browser_failure(url: str) -> None:
    """Print bilingual message when browser open fails (decision 02)."""
    from capability_codes import render, CODES
    en = render("BROWSER_OPEN_FAILED", {"url": url}, lang="en")
    zh = render("BROWSER_OPEN_FAILED", {"url": url}, lang="zh")
    print(f"[BROWSER_OPEN_FAILED] {en}")
    print(f"[BROWSER_OPEN_FAILED] {zh}")
    print("Press Ctrl+C to quit / Ctrl+C 結束")


def _print_startup_failure_stderr(code: str, **params) -> None:
    """Print a coded bilingual error to stderr (decision 02)."""
    from capability_codes import render
    en = render(code, params, lang="en")
    zh = render(code, params, lang="zh")
    print(f"ERROR [{code}]: {en}", file=sys.stderr)
    print(f"錯誤 [{code}]：{zh}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Default probe implementations (real behaviour)
# ---------------------------------------------------------------------------

class _DefaultProbes:
    """Real probe implementations used in production."""

    def resolve_session(self, base_dir: Path):
        import session_file
        return session_file.resolve(base_dir)

    def start_server(self, base_dir: Path):
        from webview_server import WebViewServer
        srv = WebViewServer(host="127.0.0.1", port=0)
        srv.start()
        return srv

    def wait_ready(self, url: str, timeout: float = DEFAULT_READY_TIMEOUT) -> bool:
        return _wait_ready_default(url, timeout)

    def write_session(
        self,
        base_dir: Path,
        url: str,
        port: int,
        pid: int,
        key: str,
        started_at: str,
    ) -> None:
        import session_file
        session_file.write_session(base_dir, url, port, pid, key, started_at)

    def open_browser(self, url: str) -> bool:
        import platform_seams
        return platform_seams.open_browser(url)

    def install_signal_handlers(self) -> None:
        """Install shutdown coordinator signal handlers if available (ticket 11)."""
        try:
            import shutdown_coordinator  # type: ignore[import]
            shutdown_coordinator.install()
        except ImportError:
            pass

    def exit(self, code: int) -> None:
        sys.exit(code)

    def environ(self) -> dict:
        return dict(os.environ)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def launch(probes: Any = None) -> None:
    """Launch the local app session on Ubuntu (non-win32).

    Resolves the session file (decision 10), then:
    - *reuse*: open the existing URL in the browser and exit 0.
    - *fresh / takeover*: start WebViewServer, wait for /health readiness,
      write the session file, open the browser; on browser-open failure keep
      serving and print bilingual URL + Ctrl+C hint; block until Ctrl+C.

    Startup failure (OSError / ImportError from start_server) exits 2 with a
    coded bilingual message to stderr and never opens a browser.

    Respects ``QWEN_NO_BROWSER=1`` for headless CI: skips browser open entirely.
    """
    if probes is None:
        probes = _DefaultProbes()

    base_dir = _default_base_dir()
    environ = probes.environ()
    _exit = probes.exit

    # ---- 1. Resolve session file (decision 10) ----------------------------
    try:
        decision = probes.resolve_session(base_dir)
    except Exception as exc:
        print(f"ERROR [STARTUP_FAILURE]: {exc}", file=sys.stderr)
        print(f"錯誤 [STARTUP_FAILURE]：{exc}", file=sys.stderr)
        _exit(EXIT_STARTUP_FAILURE)
        return

    # ---- 2. Reuse path: open existing URL, exit 0 -------------------------
    if decision.kind == "reuse":
        if not environ.get("QWEN_NO_BROWSER"):
            probes.open_browser(decision.url)
        _exit(EXIT_OK)
        return

    # ---- 3. Fresh / takeover path -----------------------------------------

    # Install shutdown coordinator signal handlers if available (ticket 11)
    try:
        probes.install_signal_handlers()
    except Exception:
        pass

    # Start the local HTTP server
    try:
        srv = probes.start_server(base_dir)
    except OSError as exc:
        _print_startup_failure_stderr("LOOPBACK_PORT_UNAVAILABLE", port="?")
        print(f"  detail: {exc}", file=sys.stderr)
        _exit(EXIT_STARTUP_FAILURE)
        return
    except ImportError as exc:
        module = str(exc).split("'")[-2] if "'" in str(exc) else str(exc)
        _print_startup_failure_stderr("DEP_IMPORT_FAILED", module=module)
        _exit(EXIT_STARTUP_FAILURE)
        return

    url = srv.url

    # Wait for /health (bounded)
    ready = probes.wait_ready(url, DEFAULT_READY_TIMEOUT)
    if not ready:
        print(
            f"ERROR [STARTUP_FAILURE]: Server did not become ready at {url}",
            file=sys.stderr,
        )
        print(
            f"錯誤 [STARTUP_FAILURE]：伺服器未在 {url} 就緒",
            file=sys.stderr,
        )
        try:
            srv.stop()
        except Exception:
            pass
        _exit(EXIT_STARTUP_FAILURE)
        return

    # Write session file (advisory; failure is non-fatal)
    key = secrets.token_hex(16)
    started_at = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        probes.write_session(base_dir, url, srv.port, os.getpid(), key, started_at)
    except Exception:
        pass

    # ---- 4. Open browser (unless headless CI) -----------------------------
    no_browser = bool(environ.get("QWEN_NO_BROWSER"))
    if no_browser:
        print(f"[QWEN_NO_BROWSER] Serving at {url} (browser suppressed)")
        print(f"[QWEN_NO_BROWSER] 在 {url} 提供服務（已抑制瀏覽器）")
    else:
        opened = probes.open_browser(url)
        if not opened:
            # Decision 02: keep serving, print URL + Ctrl+C hint
            _print_browser_failure(url)

    # ---- 5. Block until Ctrl+C / shutdown signal --------------------------
    _wait_forever()

    _exit(EXIT_OK)


# ---------------------------------------------------------------------------
# Entry point (called by run.sh on Linux via: uv run python ubuntu_launcher.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    launch()
