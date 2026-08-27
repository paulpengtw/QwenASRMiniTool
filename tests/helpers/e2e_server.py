#!/usr/bin/env python
"""tests/helpers/e2e_server.py — Headless E2E subprocess server for test_headless_e2e.py

This script is intended to be run as a subprocess (NOT imported by pytest).
It installs GUI stubs (tkinter, customtkinter) so the app stack can be
imported in a headless environment without a display, then starts the
WebViewServer, wires the quit endpoint and shutdown coordinator, and optionally
spawns a long-running child with a unique marker argument.

Environment variables consumed:
  QWEN_TEST_BASE_DIR  Path to an empty temp directory used as the app base dir.
                      The session file is written there.
  QWEN_E2E_SPAWN_MARKER  If set, spawn a child process via platform_seams.spawn
                          whose command includes this marker as an argument.
                          This lets the e2e test verify PDEATHSIG / orphan cleanup.

Output (line-buffered stdout):
  READY port=<int> key=<hex>
  (then blocks until the shutdown coordinator exits the process)
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve repo root and add to sys.path before any app import.
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent               # tests/helpers/
ROOT = HERE.parent.parent                            # repo root (worktree)
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Install GUI stubs (tkinter, customtkinter, pywebview) before any import
# that transitively pulls in app.py.
# ---------------------------------------------------------------------------

def _make_app_stub() -> types.ModuleType:
    """Minimal stub of 'app' module for webview_backend in headless mode."""
    stub = types.ModuleType("app")
    stub.BASE_DIR = str(ROOT)
    stub.SETTINGS_FILE = str(os.environ.get("QWEN_TEST_BASE_DIR", ROOT) + "/settings.json")
    stub.SRT_DIR = str(ROOT / "subtitles")
    stub._DEFAULT_MODEL_DIR = ROOT / "ov_models"
    stub._CHATLLM_DIR = ROOT / "chatllm"
    stub._BIN_PATH = ROOT / "ov_models" / "qwen3-asr-1.7b.bin"
    stub._MEIPASS = None
    stub._g_output_simplified = False
    stub._g_vocab_convert = True
    stub._CRISPASR_DIR = ROOT / "crispasr"

    class _FakeEngine:
        ready = False
        use_aligner = False
        _fa_bin = None
        diar_engine = None
        def transcribe(self, *a, **kw): return []
        def _load_aligner(self, cb=None): pass

    stub.ASREngine = _FakeEngine
    stub.ASREngine1p7B = _FakeEngine
    stub.probe_vulkan_devices = lambda *a, **kw: []
    return stub


def _make_ctk_stub() -> types.ModuleType:
    """Minimal customtkinter stub."""
    ctk = types.ModuleType("customtkinter")

    class _Base:
        def __init__(self, *a, **kw): pass
        def pack(self, *a, **kw): pass
        def configure(self, *a, **kw): pass
        def after(self, *a, **kw): pass
        def destroy(self): pass
        def grab_set(self): pass
        def deiconify(self): pass
        def lift(self): pass
        def focus_force(self): pass
        def protocol(self, *a, **kw): pass
        def geometry(self, *a, **kw): pass
        def resizable(self, *a, **kw): pass
        def title(self, *a, **kw): pass
        def set(self, *a, **kw): pass
        def start(self, *a, **kw): pass
        def stop(self, *a, **kw): pass

    ctk.CTkToplevel = _Base
    ctk.CTkLabel = _Base
    ctk.CTkProgressBar = _Base
    ctk.CTkButton = _Base
    ctk.CTkFrame = _Base
    ctk.CTkEntry = _Base
    ctk.CTkTextbox = _Base
    ctk.CTkScrollableFrame = _Base
    return ctk


# Install stubs before any import of the real modules.
sys.modules.setdefault("app", _make_app_stub())
sys.modules.setdefault("customtkinter", _make_ctk_stub())
for _mod_name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox",
                  "pywebview", "webview"):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))

# ---------------------------------------------------------------------------
# Override app.SETTINGS_FILE to point inside the test base dir.
# This ensures _persisted_backend() and capabilities reads from a clean dir.
# ---------------------------------------------------------------------------
_base_dir_env = os.environ.get("QWEN_TEST_BASE_DIR")
if _base_dir_env:
    base_dir = Path(_base_dir_env)
    base_dir.mkdir(parents=True, exist_ok=True)
    sys.modules["app"].SETTINGS_FILE = str(base_dir / "settings.json")
else:
    base_dir = ROOT

# ---------------------------------------------------------------------------
# Now import the server stack.
# ---------------------------------------------------------------------------
import secrets
import signal
import threading

from webview_server import WebViewServer
from shutdown import ShutdownCoordinator
from platform_seams import guard_children, spawn
import session_file


def main() -> None:
    # Start server on a random loopback port.
    srv = WebViewServer(host="127.0.0.1", port=0)
    port = srv.start()

    # Generate session access key.
    key = secrets.token_hex(16)

    # Build shutdown coordinator (mirrors app_webview.linux_main).
    children_guard = guard_children()

    def _broadcast():
        srv.hub.publish("stopping", {"reason": "user-quit"})

    def _stop_accepting():
        srv._accepting_work = False

    def _terminate_children():
        children_guard.terminate_all()

    def _stop_server():
        srv.stop()

    def _delete_session():
        try:
            session_file.delete_session(base_dir)
        except Exception:
            pass

    # _delete_session MUST run before _stop_server so it completes before the
    # server thread exits and unblocks the main thread's join().  If the session
    # deletion ran after _stop_server there is a race: Python may kill daemon
    # threads before the deletion completes when main() returns.
    steps = [_broadcast, _stop_accepting, _terminate_children,
             _delete_session, _stop_server]

    coord = ShutdownCoordinator(steps=steps)
    srv.shutdown_coordinator = coord
    srv.quit_access_key = key

    # Install SIGINT/SIGTERM handlers.
    coord.install_signal_handlers()

    # Write session file so the test can read the access key.
    import datetime
    try:
        session_file.write_session(
            base_dir,
            f"http://127.0.0.1:{port}/",
            port,
            os.getpid(),
            key,
            datetime.datetime.utcnow().isoformat() + "Z",
        )
    except Exception as exc:
        print(f"[e2e_server] WARNING: could not write session file: {exc}",
              file=sys.stderr, flush=True)

    # Optionally spawn a long-running child that embeds the marker in its
    # command line so pgrep -f <marker> can find it.  Using a Python -c
    # command ensures the marker appears in /proc/<pid>/cmdline.
    marker = os.environ.get("QWEN_E2E_SPAWN_MARKER")
    if marker:
        try:
            # The child sleeps 300 s; the marker is embedded in the -c string
            # so `pgrep -f <marker>` finds it.
            child = spawn([
                sys.executable, "-c",
                f"# {marker}\nimport time; time.sleep(300)",
            ])
            print(f"CHILD_PID={child.pid}", flush=True)
        except Exception as exc:
            print(f"[e2e_server] WARNING: could not spawn marker child: {exc}",
                  file=sys.stderr, flush=True)

    # Signal the test that we are ready.
    print(f"READY port={port} key={key}", flush=True)

    # Block until the server thread exits (coordinator will call os._exit).
    if srv._thread is not None:
        srv._thread.join()


if __name__ == "__main__":
    main()
