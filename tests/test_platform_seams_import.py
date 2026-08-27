"""tests/test_platform_seams_import.py — portable import invariant for platform_seams.

This test verifies that platform_seams can be imported on any supported
platform (Windows and Ubuntu 24.04) without error.  It is one of the two
cross-platform invariants that the Windows CI job must run (decision doc 07).
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
