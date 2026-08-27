"""tests/test_platform_seams_import.py — portable import invariant for platform_seams.

This test verifies that platform_seams can be imported on any supported
platform (Windows and Ubuntu 24.04) without error.  It is one of the two
cross-platform invariants that the Windows CI job must run (decision doc 07).

Ticket 15 adds: simulated win32 code paths that run on every platform so the
cross-platform seams are regression-guarded without needing a real Windows host.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_platform_seams_imports_without_error():
    """platform_seams must be importable on every supported platform."""
    mod = importlib.import_module("platform_seams")
    assert mod is not None


def test_platform_seams_exports_public_functions():
    """The six public functions must be present after import."""
    import platform_seams  # noqa: PLC0415

    expected = {"app_dir", "open_path", "find_executable", "spawn",
                "guard_children", "open_browser"}
    for name in expected:
        assert hasattr(platform_seams, name), f"platform_seams missing: {name}"


# ---------------------------------------------------------------------------
# Simulated win32 code-path invariants (ticket 15 — Windows regression guard)
# These run on Linux/CI without a real Windows host so the platform-branching
# logic is always regression-guarded.
# ---------------------------------------------------------------------------

class TestSimulatedWin32CodePaths:
    """Guard the win32 branches of platform_seams without a real Windows host.

    Each test passes platform="win32" explicitly and verifies that:
    - The function returns without raising
    - The return type is correct (Path | None | bool)
    """

    def test_find_executable_win32_adds_exe_suffix(self, tmp_path):
        """find_executable with platform='win32' must try name + '.exe'."""
        import platform_seams

        # Create 'notepad.exe' in a temp dir.
        fake_exe = tmp_path / "notepad.exe"
        fake_exe.touch()

        result = platform_seams.find_executable(
            "notepad", extra_dirs=[tmp_path], platform="win32"
        )
        assert result == fake_exe

    def test_find_executable_win32_returns_none_for_nonsense(self):
        """find_executable returns None (not raises) for an unknown name on win32."""
        import platform_seams

        result = platform_seams.find_executable(
            "__nonexistent_binary_xyz__", platform="win32"
        )
        assert result is None

    def test_open_path_win32_does_not_raise(self):
        """open_path with platform='win32' must not raise (may return False)."""
        import platform_seams

        try:
            result = platform_seams.open_path("/tmp", platform="win32")
        except Exception as exc:
            raise AssertionError(
                f"open_path raised on simulated win32: {exc}"
            ) from exc
        assert isinstance(result, bool)

    def test_guard_children_win32_does_not_raise(self):
        """guard_children() with platform='win32' must not raise."""
        import platform_seams

        try:
            guard = platform_seams.guard_children(platform="win32")
        except Exception as exc:
            raise AssertionError(
                f"guard_children raised on simulated win32: {exc}"
            ) from exc
        assert guard is not None

    def test_open_browser_win32_does_not_raise(self):
        """open_browser with platform='win32' must not raise."""
        import platform_seams

        try:
            result = platform_seams.open_browser(
                "http://127.0.0.1:9999", platform="win32"
            )
        except Exception as exc:
            raise AssertionError(
                f"open_browser raised on simulated win32: {exc}"
            ) from exc
        assert isinstance(result, bool)

    def test_app_dir_win32_returns_path(self):
        """app_dir returns a Path regardless of platform kwarg."""
        import platform_seams

        result = platform_seams.app_dir(platform="win32")
        assert isinstance(result, Path)

    def test_child_guard_terminate_all_win32_does_not_raise(self):
        """ChildGuard.terminate_all() on simulated win32 with no children must not raise."""
        import platform_seams

        guard = platform_seams.ChildGuard(_platform="win32")
        try:
            guard.terminate_all(timeout=1.0)
        except Exception as exc:
            raise AssertionError(
                f"terminate_all raised on simulated win32: {exc}"
            ) from exc
