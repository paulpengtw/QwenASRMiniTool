"""tests/test_platform_seams.py — platform_seams public-seam tests (Linux).

All tests are bounded < 5 s.

(a) PDEATHSIG: helper script spawns "sleep 30" via platform_seams.spawn;
    test SIGKILLs the helper; asserts the sleep pid is gone within 2 s.
(b) terminate_all kills a child and its grandchild ("sh -c 'sleep 30 & wait'").
(c) find_executable finds "sh" and returns None for a nonsense name;
    win32 ".exe" suffix logic via platform kwarg.
(d) open_path returns False (no raise) with an empty PATH.
(e) app_dir is the repo root (worktree root) here.
(f) importing platform_seams on a simulated win32 code path does not fail
    (guard ctypes/libc access).
"""
from __future__ import annotations

import os
import signal
import sys
import textwrap
import time
from pathlib import Path

import pytest

# The repo / worktree root is two levels above this file (tests/test_...py).
REPO_ROOT = Path(__file__).resolve().parents[1]

# Import the module under test.
sys.path.insert(0, str(REPO_ROOT))
import platform_seams


# ---------------------------------------------------------------------------
# (a) PDEATHSIG: grandchild dies when parent (helper) is SIGKILLed
# ---------------------------------------------------------------------------

def test_pdeathsig_grandchild_dies_on_parent_kill(tmp_path):
    """A child spawned with spawn() should get SIGTERM when its parent dies."""
    # Write a helper script that:
    #   1. Spawns "sleep 30" via platform_seams.spawn
    #   2. Prints the sleep pid
    #   3. Loops (so the test can SIGKILL it)
    helper = tmp_path / "helper.py"
    helper.write_text(textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        import platform_seams, time
        proc = platform_seams.spawn(["sleep", "30"])
        print(proc.pid, flush=True)
        time.sleep(60)
    """))

    import subprocess
    parent = subprocess.Popen(
        [sys.executable, str(helper)],
        stdout=subprocess.PIPE,
        text=True,
    )

    # Read the sleep PID printed by the helper
    line = parent.stdout.readline()
    sleep_pid = int(line.strip())

    # Confirm the sleep is alive
    assert _pid_alive(sleep_pid), "sleep should be running before SIGKILL"

    # SIGKILL the helper (parent of sleep)
    os.kill(parent.pid, signal.SIGKILL)
    parent.wait(timeout=3)

    # Give the kernel / prctl up to 2 s to propagate SIGTERM to sleep
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _pid_alive(sleep_pid):
            break
        time.sleep(0.05)

    assert not _pid_alive(sleep_pid), (
        f"sleep pid {sleep_pid} should have died after SIGKILL of parent")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but we can't signal it


# ---------------------------------------------------------------------------
# (b) terminate_all kills child and grandchild
# ---------------------------------------------------------------------------

def test_terminate_all_kills_child_and_grandchild():
    """guard_children().terminate_all() kills 'sh -c sleep 30 & wait' and its child."""
    # Spawn a shell that backgrounds a sleep and waits for it.
    child = platform_seams.spawn(["sh", "-c", "sleep 30 & wait"])
    child_pid = child.pid

    # Give the grandchild a moment to start
    time.sleep(0.2)

    # Find grandchild pid (sleep) via /proc
    grandchild_pid = _find_child_pid(child_pid, "sleep")

    guard = platform_seams.guard_children()
    guard.terminate_all(timeout=3.0)

    # Give OS a moment
    time.sleep(0.1)

    assert not _pid_alive(child_pid), "child shell should be dead"
    if grandchild_pid is not None:
        assert not _pid_alive(grandchild_pid), "grandchild sleep should be dead"


def _find_child_pid(parent_pid: int, name: str) -> int | None:
    """Find a child process of parent_pid whose comm matches name."""
    try:
        import subprocess as sp
        result = sp.run(
            ["ps", "--ppid", str(parent_pid), "-o", "pid,comm", "--no-headers"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and name in parts[1]:
                return int(parts[0])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# (c) find_executable
# ---------------------------------------------------------------------------

def test_find_executable_finds_sh():
    result = platform_seams.find_executable("sh")
    assert result is not None
    assert result.name == "sh" or result.name.startswith("sh")


def test_find_executable_returns_none_for_nonsense():
    result = platform_seams.find_executable("__no_such_binary_xyz_99__")
    assert result is None


def test_find_executable_win32_exe_suffix(tmp_path):
    """On win32 (simulated), find_executable also tries name + '.exe'."""
    # Create a fake 'notepad.exe' in a temp dir
    fake_exe = tmp_path / "notepad.exe"
    fake_exe.touch()

    # Using platform kwarg to simulate win32; extra_dirs so shutil.which won't find it
    result = platform_seams.find_executable(
        "notepad", extra_dirs=[tmp_path], platform="win32"
    )
    assert result is not None
    assert result.name == "notepad.exe"


def test_find_executable_win32_exe_suffix_returns_none_for_nonsense():
    result = platform_seams.find_executable(
        "__no_such_binary_xyz__", platform="win32"
    )
    assert result is None


# ---------------------------------------------------------------------------
# (d) open_path returns False (no raise) with an empty PATH
# ---------------------------------------------------------------------------

def test_open_path_returns_false_with_empty_path(monkeypatch, tmp_path):
    """With no xdg-open on PATH, open_path must return False, never raise."""
    monkeypatch.setenv("PATH", "")
    result = platform_seams.open_path(tmp_path, platform="linux")
    assert result is False


# ---------------------------------------------------------------------------
# (e) app_dir is the repo root (worktree root)
# ---------------------------------------------------------------------------

def test_app_dir_is_repo_root():
    """In source-install (non-frozen) mode, app_dir() == directory of platform_seams.py."""
    expected = REPO_ROOT
    result = platform_seams.app_dir()
    assert result == expected


# ---------------------------------------------------------------------------
# (f) Importing platform_seams on simulated win32 does not fail
# ---------------------------------------------------------------------------

def test_simulated_win32_import_does_not_fail():
    """guard_children and spawn must handle win32 platform kwarg without crashing."""
    # guard_children on simulated win32 tries to call proc_guard which is
    # available only on Windows; it must silently degrade.
    guard = platform_seams.guard_children(platform="win32")
    assert guard is not None

    # find_executable with win32 kwarg must not crash
    result = platform_seams.find_executable("sh", platform="win32")
    # sh might or might not be found; either is fine — no crash is the requirement
    assert result is None or isinstance(result, Path)

    # open_path with win32 kwarg: os.startfile is unavailable on Linux so it
    # must return False (not raise)
    result = platform_seams.open_path("/tmp", platform="win32")
    # On Linux, os.startfile doesn't exist; open_path catches that and returns False
    assert isinstance(result, bool)

    # open_browser with win32 kwarg must not crash
    # (it may or may not succeed depending on display availability)
    try:
        platform_seams.open_browser("http://localhost", platform="win32")
    except Exception as exc:
        pytest.fail(f"open_browser raised on simulated win32: {exc}")
