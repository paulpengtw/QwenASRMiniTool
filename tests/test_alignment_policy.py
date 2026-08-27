"""tests/test_alignment_policy.py

Tests for ticket 07: platform-unsupported exact alignment, visibly
proportional timing.

Coverage
--------
- alignment_capability() returns correct shape for linux vs win32.
- get_status() (webview_backend) includes "alignment" key.
- _ensure_fa on linux returns False and never calls download_aligner.
- use_aligner value is preserved through a settings write (set_settings
  must not strip use_aligner on Linux).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


# ===========================================================================
# Helpers: build a minimal WebBackend instance without starting a real engine
# ===========================================================================

def _make_backend():
    """Return a WebBackend instance with a stubbed engine (no real load)."""
    import webview_backend as wb
    engine = MagicMock()
    engine.ready = False
    engine._fa_bin = None
    engine.use_aligner = False
    b = wb.WebBackend.__new__(wb.WebBackend)
    b.engine = engine
    b._loading = False
    b._load_err = None
    b._active_backend = "openvino"
    # Side-effect callbacks that set_settings/apply_* may reference
    b._theme_cb = None
    b._detect_speech_groups = lambda *a, **kw: None
    b._cancel = False
    return b


# ===========================================================================
# 1. alignment_capability – shape and platform routing
# ===========================================================================

class TestAlignmentCapability(unittest.TestCase):

    def setUp(self):
        import alignment_policy
        self.ac = alignment_policy.alignment_capability

    def test_linux_returns_proportional_platform_unsupported(self):
        result = self.ac(platform="linux")
        self.assertEqual(result["method"], "proportional")
        self.assertEqual(result["state"], "platform_unsupported")
        self.assertEqual(result["reason"]["code"], "ALIGN_WINDOWS_ONLY")
        self.assertEqual(result["reason"]["params"], {})

    def test_darwin_returns_proportional_platform_unsupported(self):
        result = self.ac(platform="darwin")
        self.assertEqual(result["method"], "proportional")
        self.assertEqual(result["state"], "platform_unsupported")

    def test_win32_returns_exact_ready(self):
        result = self.ac(platform="win32")
        self.assertEqual(result["method"], "exact")
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["reason"]["code"], "ALIGN_WINDOWS_ONLY")

    def test_result_has_required_keys(self):
        for plat in ("linux", "win32", "darwin"):
            result = self.ac(platform=plat)
            self.assertIn("method", result)
            self.assertIn("state", result)
            self.assertIn("reason", result)
            self.assertIn("code", result["reason"])
            self.assertIn("params", result["reason"])

    def test_default_platform_arg_does_not_raise(self):
        import alignment_policy
        result = alignment_policy.alignment_capability()
        self.assertIn("method", result)


# ===========================================================================
# 2. get_status() includes "alignment" field
# ===========================================================================

class TestGetStatusAlignment(unittest.TestCase):
    """webview_backend.get_status() must include 'alignment' from alignment_capability."""

    def test_get_status_includes_alignment_field(self):
        b = _make_backend()
        status = b.get_status()
        self.assertIn("alignment", status,
                      "get_status() must include the 'alignment' key from alignment_capability()")

    def test_get_status_alignment_has_required_keys(self):
        b = _make_backend()
        status = b.get_status()
        al = status["alignment"]
        self.assertIn("method", al)
        self.assertIn("state", al)
        self.assertIn("reason", al)

    def test_get_status_alignment_on_linux(self):
        import alignment_policy
        b = _make_backend()
        with patch.object(alignment_policy, "alignment_capability",
                          wraps=lambda platform="linux": {
                              "method": "proportional",
                              "state": "platform_unsupported",
                              "reason": {"code": "ALIGN_WINDOWS_ONLY", "params": {}},
                          }):
            # Re-call get_status — webview_backend calls alignment_capability()
            # at module import time or inside get_status(); either way the field
            # must be present.
            status = b.get_status()
        self.assertIn("alignment", status)

    def test_get_status_alignment_on_win32(self):
        import alignment_policy
        b = _make_backend()
        with patch.object(alignment_policy, "alignment_capability",
                          return_value={
                              "method": "exact",
                              "state": "ready",
                              "reason": {"code": "ALIGN_WINDOWS_ONLY", "params": {}},
                          }):
            status = b.get_status()
        self.assertIn("alignment", status)


# ===========================================================================
# 3. _ensure_fa on linux returns False, never calls download_aligner
# ===========================================================================

class TestEnsureFaLinux(unittest.TestCase):

    def test_ensure_fa_returns_false_on_linux_and_no_download(self):
        import webview_backend as wb
        download_called = []

        def fake_download_aligner(*args, **kwargs):
            download_called.append(True)

        b = _make_backend()
        b._st = lambda msg: None

        fake_downloader = MagicMock()
        fake_downloader.quick_check_aligner = MagicMock(return_value=False)
        fake_downloader.download_aligner = fake_download_aligner

        with patch("sys.platform", "linux"), \
             patch.dict("sys.modules", {"downloader": fake_downloader}):
            result = b._ensure_fa()

        self.assertFalse(result, "_ensure_fa() must return False on Linux")
        self.assertEqual(download_called, [],
                         "download_aligner must NOT be called on Linux")


# ===========================================================================
# 4. use_aligner value preserved through settings write
# ===========================================================================

class TestSettingsPreserveAlignerKeys(unittest.TestCase):
    """set_settings() must not overwrite use_aligner or chunk_secs on Linux."""

    def _write_settings(self, sf: Path, data: dict):
        sf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _read_settings(self, sf: Path) -> dict:
        return json.loads(sf.read_text(encoding="utf-8"))

    def _backend_with_settings(self, sf: Path):
        import webview_backend as wb
        b = _make_backend()
        import webview_backend as wb_mod
        wb_mod.core.SETTINGS_FILE = str(sf)
        return b

    def test_use_aligner_preserved_after_set_settings(self):
        """use_aligner=True in settings.json survives an unrelated set_settings call."""
        import tempfile, webview_backend as wb
        settings_data = {
            "use_aligner": True,
            "chunk_secs": 15,
            "backend": "openvino",
            "appearance": "light",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            sf = Path(tmpdir) / "settings.json"
            self._write_settings(sf, settings_data)

            b = self._backend_with_settings(sf)
            # Change only an unrelated key
            b.set_settings({"theme": "dark"})

            result = self._read_settings(sf)
            self.assertIn("use_aligner", result,
                          "use_aligner must be preserved in settings after set_settings()")
            self.assertTrue(result["use_aligner"],
                            "use_aligner must retain its True value")
            self.assertEqual(result.get("chunk_secs", 15), 15,
                             "chunk_secs must be preserved")

    def test_use_aligner_false_preserved_after_set_settings(self):
        """use_aligner=False in settings.json also survives."""
        import tempfile
        settings_data = {"use_aligner": False, "backend": "chatllm", "chunk_secs": 20}

        with tempfile.TemporaryDirectory() as tmpdir:
            sf = Path(tmpdir) / "settings.json"
            self._write_settings(sf, settings_data)

            b = self._backend_with_settings(sf)
            b.set_settings({"theme": "light"})

            result = self._read_settings(sf)
            self.assertIn("use_aligner", result)
            self.assertFalse(result["use_aligner"])
            self.assertEqual(result.get("chunk_secs"), 20)


if __name__ == "__main__":
    unittest.main()
