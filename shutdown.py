"""shutdown.py — Cooperative shutdown coordinator for QwenASRMiniTool.

ShutdownCoordinator orchestrates ordered, bounded shutdown steps, starts a
10-second watchdog that force-exits if steps stall, and ensures a second
SIGINT forces immediate termination.

Windows behaviour is unchanged; this module is used by the Linux launcher.
Signal handlers are installed only on non-win32.

Exit codes (decision docs 02 and 10):
    user-quit -> 0
    signal    -> 130  (SIGINT / Ctrl+C)
    replaced  -> 143  (SIGTERM or stale-session replacement)
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from typing import Callable, Sequence

# ---------------------------------------------------------------------------
# Exit code table
# ---------------------------------------------------------------------------

#: Map of shutdown reason -> process exit code.
EXIT_CODES: dict[str, int] = {
    "user-quit": 0,
    "signal": 130,    # SIGINT (Ctrl+C)
    "replaced": 143,  # SIGTERM or launcher replacement
}

# Error code used in APP_STOPPING 503 responses.
APP_STOPPING = "APP_STOPPING"


# ---------------------------------------------------------------------------
# ShutdownCoordinator
# ---------------------------------------------------------------------------


class ShutdownCoordinator:
    """Orchestrate ordered, bounded shutdown.

    Parameters
    ----------
    steps:
        Ordered sequence of zero-argument callables representing shutdown work.
        Each is called in turn; exceptions are swallowed so later steps still
        run.  Injectable for tests (pass a list of recording fakes).
    exit_fn:
        Callable(int) that terminates the process.  Defaults to os._exit.
        Injectable for tests.
    clock:
        Callable() -> float returning a monotonic timestamp.  Defaults to
        time.monotonic.  Injectable for tests.
    watchdog_timeout:
        Seconds before the watchdog force-exits.  Default 10.
    """

    def __init__(
        self,
        steps: Sequence[Callable[[], None]] | None = None,
        *,
        exit_fn: Callable[[int], None] | None = None,
        clock: Callable[[], float] | None = None,
        watchdog_timeout: float = 10.0,
    ) -> None:
        self._steps = list(steps) if steps is not None else []
        self._exit_fn = exit_fn if exit_fn is not None else os._exit
        self._clock = clock if clock is not None else time.monotonic
        self._watchdog_timeout = watchdog_timeout
        self._began = threading.Event()
        self._exit_code: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def begin(self, reason: str, exit_code: int | None = None) -> None:
        """Start shutdown for *reason*.

        Only the first call runs the steps; subsequent calls are no-ops
        (idempotent).  *exit_code* overrides the default derived from *reason*.

        Starts a watchdog thread, runs steps synchronously, then calls
        exit_fn with the resolved exit code.
        """
        if self._began.is_set():
            return
        code = exit_code if exit_code is not None else EXIT_CODES.get(reason, 1)
        self._exit_code = code
        self._began.set()
        self._start_watchdog(code)
        self._run_steps()
        self._exit_fn(code)

    def install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers (non-win32 only).

        SIGINT  -> begin("signal", exit_code=130)  # Ctrl+C
        SIGTERM -> begin("signal", exit_code=143)

        A second SIGINT while shutdown is already in progress force-exits
        immediately with the original exit code.
        """
        if sys.platform == "win32":
            return

        coordinator = self

        def _sigint(signum, frame):  # type: ignore[misc]
            if coordinator._began.is_set():
                # Second SIGINT: force exit immediately.
                coordinator._exit_fn(coordinator._exit_code)
            else:
                # Run shutdown in a thread so the signal handler returns fast.
                threading.Thread(
                    target=coordinator.begin,
                    args=("signal",),
                    kwargs={"exit_code": 130},
                    daemon=True,
                ).start()

        def _sigterm(signum, frame):  # type: ignore[misc]
            threading.Thread(
                target=coordinator.begin,
                args=("signal",),
                kwargs={"exit_code": 143},
                daemon=True,
            ).start()

        signal.signal(signal.SIGINT, _sigint)
        signal.signal(signal.SIGTERM, _sigterm)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_watchdog(self, code: int) -> None:
        """Start a daemon thread that force-exits after watchdog_timeout."""
        timeout = self._watchdog_timeout
        exit_fn = self._exit_fn
        clock = self._clock
        deadline = clock() + timeout

        def _watch() -> None:
            while clock() < deadline:
                time.sleep(0.05)
            exit_fn(code)

        t = threading.Thread(target=_watch, daemon=True, name="shutdown-watchdog")
        t.start()

    def _run_steps(self) -> None:
        for step in self._steps:
            try:
                step()
            except Exception:
                pass  # swallow; later steps still run
