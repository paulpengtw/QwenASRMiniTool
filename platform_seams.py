"""platform_seams.py — portable OS integration for QwenASRMiniTool

Exposes exactly six public functions; each branches internally on sys.platform.
Call sites never branch on sys.platform.  An optional `platform` kwarg overrides
sys.platform for testing.

Functions:
    app_dir()               -> Path
    open_path(path)         -> bool
    find_executable(name)   -> Path | None
    spawn(cmd, **kwargs)    -> subprocess.Popen
    guard_children()        -> ChildGuard
    open_browser(url)       -> bool
"""
from __future__ import annotations

import atexit
import ctypes
import os
import shutil
import signal
import subprocess
import sys
import weakref
from pathlib import Path
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# PlatformUnsupported — raised by download helpers on non-win32
# ---------------------------------------------------------------------------

class PlatformUnsupported(RuntimeError):
    """Raised when a Windows-only operation is attempted on a non-Windows platform."""


# ---------------------------------------------------------------------------
# PR_SET_PDEATHSIG constant (Linux prctl)
# ---------------------------------------------------------------------------
_PR_SET_PDEATHSIG = 1

# ---------------------------------------------------------------------------
# Module-level weak registry of spawned Popen objects (for guard_children)
# ---------------------------------------------------------------------------
_child_registry: list[weakref.ref] = []


# ---------------------------------------------------------------------------
# Helper: resolve the effective platform
# ---------------------------------------------------------------------------
def _platform(platform: str | None) -> str:
    return platform if platform is not None else sys.platform


# ---------------------------------------------------------------------------
# app_dir
# ---------------------------------------------------------------------------

def app_dir(*, platform: str | None = None) -> Path:
    """Return the directory beside the checkout that holds settings / models.

    Frozen-aware (matches app.py's BASE_DIR logic).  Never moves directories.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# open_path
# ---------------------------------------------------------------------------

def open_path(path, *, platform: str | None = None) -> bool:
    """Open a file or folder with the platform's default application.

    Returns False (never raises) when no opener exists or the call fails.
    """
    plat = _platform(platform)
    try:
        if plat == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        elif plat == "darwin":
            proc = spawn(["open", str(path)], platform=platform)
            proc.wait(timeout=5)
            return proc.returncode == 0
        else:
            # linux / other POSIX — use xdg-open if available
            xdg = shutil.which("xdg-open")
            if not xdg:
                return False
            proc = spawn([xdg, str(path)], platform=platform)
            # xdg-open forks; we don't wait for it
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# find_executable
# ---------------------------------------------------------------------------

def find_executable(
    name: str,
    extra_dirs: Iterable[str | Path] = (),
    *,
    platform: str | None = None,
) -> Path | None:
    """Locate an executable by name.  Never downloads anything.

    Search order: PATH (shutil.which) -> extra_dirs.
    On win32 also tries name + ".exe" if name has no extension.
    """
    plat = _platform(platform)

    def _which(n: str) -> Path | None:
        hit = shutil.which(n)
        return Path(hit) if hit else None

    result = _which(name)
    if result:
        return result

    if plat == "win32" and not name.lower().endswith(".exe"):
        result = _which(name + ".exe")
        if result:
            return result

    for d in extra_dirs:
        candidate = Path(d) / name
        if candidate.exists():
            return candidate
        if plat == "win32" and not name.lower().endswith(".exe"):
            candidate_exe = Path(d) / (name + ".exe")
            if candidate_exe.exists():
                return candidate_exe

    return None


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------

def _linux_preexec(ppid: int) -> None:
    """Called in the child (Linux/POSIX) after fork, before exec.

    Sets PR_SET_PDEATHSIG so the child receives SIGTERM when its parent dies,
    then re-checks os.getppid() to close the race where the parent already died
    before prctl ran.
    """
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except Exception:
        pass
    # Race-close: if parent already died (reparented to init=1), exit now.
    if os.getppid() != ppid:
        os._exit(1)


def spawn(
    cmd: Sequence[str],
    *,
    platform: str | None = None,
    **popen_kwargs,
) -> subprocess.Popen:
    """Start a subprocess with platform-appropriate child-cleanup setup.

    Linux/Darwin:
        start_new_session=True  (own process group for killpg)
        preexec_fn sets PR_SET_PDEATHSIG=SIGTERM via libc prctl (Linux only)
    Win32:
        CREATE_NO_WINDOW + hidden STARTUPINFO
        Registered with proc_guard's Job Object when available

    The returned Popen is added to the module-level weak registry so that
    guard_children() can reach it.
    """
    plat = _platform(platform)

    if plat == "win32":
        CREATE_NO_WINDOW = 0x08000000
        si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        si.wShowWindow = 0  # SW_HIDE
        popen_kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
        popen_kwargs.setdefault("startupinfo", si)
    else:
        popen_kwargs.setdefault("start_new_session", True)
        if plat == "linux" and "preexec_fn" not in popen_kwargs:
            ppid = os.getpid()
            popen_kwargs["preexec_fn"] = lambda: _linux_preexec(ppid)

    proc = subprocess.Popen(cmd, **popen_kwargs)

    # Track in weak registry
    _child_registry.append(weakref.ref(proc))

    if plat == "win32":
        # Register with the job object if proc_guard is available
        try:
            import proc_guard
            if proc_guard._JOB_HANDLE is not None:
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                k32.AssignProcessToJobObject(proc_guard._JOB_HANDLE,
                                             k32.OpenProcess(0x001F0FFF, False, proc.pid))
        except Exception:
            pass

    return proc


# ---------------------------------------------------------------------------
# ChildGuard
# ---------------------------------------------------------------------------

class ChildGuard:
    """Context manager / explicit controller for child process cleanup."""

    def __init__(self, _platform: str | None = None):
        self._plat = _platform

    def terminate_all(self, timeout: float = 5.0) -> None:
        """SIGTERM all tracked children (and their groups on POSIX), then wait,
        then SIGKILL any survivors.
        """
        plat = _platform(self._plat)
        procs = [ref() for ref in _child_registry]
        procs = [p for p in procs if p is not None]

        if plat == "win32":
            for p in procs:
                try:
                    p.terminate()
                except Exception:
                    pass
            for p in procs:
                try:
                    p.wait(timeout=timeout)
                except Exception:
                    pass
                try:
                    p.kill()
                except Exception:
                    pass
        else:
            # POSIX: killpg the session / process-group
            pgrps: list[int] = []
            for p in procs:
                try:
                    pgrp = os.getpgid(p.pid)
                    pgrps.append(pgrp)
                except Exception:
                    pass

            for pgrp in pgrps:
                try:
                    os.killpg(pgrp, signal.SIGTERM)
                except Exception:
                    pass

            import time
            deadline = time.monotonic() + timeout
            for p in procs:
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    p.wait(timeout=remaining)
                except Exception:
                    pass

            for pgrp in pgrps:
                try:
                    os.killpg(pgrp, signal.SIGKILL)
                except Exception:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.terminate_all()


def _posix_atexit_cleanup() -> None:
    """Atexit handler: killpg every tracked child group."""
    for ref in list(_child_registry):
        p = ref()
        if p is None:
            continue
        try:
            pgrp = os.getpgid(p.pid)
            os.killpg(pgrp, signal.SIGKILL)
        except Exception:
            pass


def _posix_signal_cleanup(signum, frame) -> None:
    """SIGTERM / SIGINT handler: kill children then re-raise."""
    _posix_atexit_cleanup()
    # Re-raise with default handler
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def guard_children(*, platform: str | None = None) -> ChildGuard:
    """Install platform-appropriate child-cleanup hooks and return a ChildGuard.

    Win32:  delegates to proc_guard.setup_kill_on_close_job().
    POSIX:  installs atexit + SIGTERM/SIGINT cleanup that killpg()s every
            tracked child's process group.

    Returns a ChildGuard whose terminate_all() method SIGTERMs then SIGKILLs.
    """
    plat = _platform(platform)

    if plat == "win32":
        try:
            import proc_guard
            proc_guard.setup_kill_on_close_job()
        except Exception:
            pass
    else:
        atexit.register(_posix_atexit_cleanup)
        try:
            signal.signal(signal.SIGTERM, _posix_signal_cleanup)
        except Exception:
            pass
        try:
            signal.signal(signal.SIGINT, _posix_signal_cleanup)
        except Exception:
            pass

    return ChildGuard(_platform=platform)


# ---------------------------------------------------------------------------
# open_browser
# ---------------------------------------------------------------------------

def open_browser(url: str, *, platform: str | None = None) -> bool:
    """Open url in the default browser.

    Never invokes pywebview / Edge.
    Returns False when nothing can open (caller should print the URL).
    """
    plat = _platform(platform)
    try:
        import webbrowser
        opened = webbrowser.open(url)
        if opened:
            return True
    except Exception:
        pass

    # Linux fallback: xdg-open
    if plat not in ("win32", "darwin"):
        xdg = shutil.which("xdg-open")
        if xdg:
            try:
                spawn([xdg, url], platform=platform)
                return True
            except Exception:
                pass

    return False
