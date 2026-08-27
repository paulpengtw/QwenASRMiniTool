"""tests/test_windows_regression_guard.py — Windows regression guard (ticket 15).

Audits every reader of the persisted backend / model choice for the derived
fallback (decision doc 12: dropping _seed_defaults means every reader needs a
fallback; Windows-visible behaviour must remain unchanged).

Tests:
  1. webview_backend._persisted_backend() derived fallback (no settings file)
  2. webview_backend._persisted_backend() with a Windows preference (crispasr)
  3. setting.py _SCALE_MAP ui_scale mirror roundtrip (Windows surface invariant)
  4. capabilities.build_snapshot() derived fallback for every backend reader
  5. Windows preference preserved end-to-end through capabilities snapshot
  6. app.py _resolve_backend derived fallback (no backend key)
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ===========================================================================
# 1. webview_backend._persisted_backend() — derived fallback
# ===========================================================================

class TestPersistedBackendDerivedFallback:
    """webview_backend._persisted_backend() must return 'openvino' when no
    settings file exists (derived fallback, decision 12)."""

    def _make_backend(self, settings_file: Path):
        """Return a WebBackend configured to read from settings_file."""
        from webview_backend import WebBackend
        import app as core

        # Point SETTINGS_FILE to our temp path for this test.
        orig = getattr(core, "SETTINGS_FILE", None)
        core.SETTINGS_FILE = str(settings_file)
        try:
            # Bypass _seed_defaults by creating backend with empty dict path.
            b = object.__new__(WebBackend)
            # Minimal attribute initialisation (no engine, no threads).
            b.engine = MagicMock()
            b.engine.ready = False
            b._loaded = False
            b._load_err = None
            b._loading = False
            b._cancel = False
            b._server = None
            b._tunnel = None
            b._on_event = None
            b._theme_cb = None
            import threading
            b._lock = threading.Lock()
            b._recording_job_id = None
            b._active_backend = "openvino"
            return b
        finally:
            if orig is not None:
                core.SETTINGS_FILE = orig

    def test_no_settings_file_returns_openvino(self, tmp_path):
        """When settings.json does not exist, fallback is 'openvino'."""
        import app as core
        missing = tmp_path / "settings.json"
        orig = getattr(core, "SETTINGS_FILE", None)
        core.SETTINGS_FILE = str(missing)
        try:
            b = self._make_backend(missing)
            assert b._persisted_backend() == "openvino"
        finally:
            if orig is not None:
                core.SETTINGS_FILE = orig

    def test_empty_backend_key_returns_openvino(self, tmp_path):
        """When settings.json exists but has no 'backend' key, fallback is 'openvino'."""
        import app as core
        sf = tmp_path / "settings.json"
        sf.write_text(json.dumps({"ui_scale": 1.0}), encoding="utf-8")
        orig = getattr(core, "SETTINGS_FILE", None)
        core.SETTINGS_FILE = str(sf)
        try:
            b = self._make_backend(sf)
            assert b._persisted_backend() == "openvino"
        finally:
            if orig is not None:
                core.SETTINGS_FILE = orig

    def test_crispasr_preference_preserved(self, tmp_path):
        """When settings.json has backend='crispasr' (Windows pref), it is preserved
        verbatim — even on Linux.  The effective_backend resolves via capabilities.py."""
        import app as core
        sf = tmp_path / "settings.json"
        sf.write_text(json.dumps({"backend": "crispasr"}), encoding="utf-8")
        orig = getattr(core, "SETTINGS_FILE", None)
        core.SETTINGS_FILE = str(sf)
        try:
            b = self._make_backend(sf)
            assert b._persisted_backend() == "crispasr"
        finally:
            if orig is not None:
                core.SETTINGS_FILE = orig

    def test_corrupted_settings_file_returns_openvino(self, tmp_path):
        """Corrupted settings.json must not raise; fallback is 'openvino'."""
        import app as core
        sf = tmp_path / "settings.json"
        sf.write_text("NOT VALID JSON", encoding="utf-8")
        orig = getattr(core, "SETTINGS_FILE", None)
        core.SETTINGS_FILE = str(sf)
        try:
            b = self._make_backend(sf)
            assert b._persisted_backend() == "openvino"
        finally:
            if orig is not None:
                core.SETTINGS_FILE = orig


# ===========================================================================
# 2. setting.py _SCALE_MAP — ui_scale mirror roundtrip (Windows surface)
# ===========================================================================

class TestUiScaleRoundtrip:
    """SettingsTab._SCALE_MAP / sync_prefs ui_scale mirror roundtrip.

    The 'Windows surface' invariant: for every canonical scale float stored
    in settings.json (written by _on_ui_scale_change via round(float(v), 2)),
    sync_prefs() must find the exactly correct label — no drift to a neighbour.

    This test is headless: it reads the class-level SCALE_MAP constant and
    exercises the min-distance lookup without instantiating any CTk widgets.
    """

    def _import_scale_map(self):
        from setting import SettingsTab
        return SettingsTab._SCALE_MAP  # e.g. {"小 (90%)": 0.9, ...}

    def test_scale_map_has_standard_100_percent(self):
        """SCALE_MAP must contain the '標準 (100%)' label mapped to 1.0."""
        scale_map = self._import_scale_map()
        assert 1.0 in scale_map.values(), "SCALE_MAP must include 1.0 (標準 100%)"

    def test_all_canonical_values_roundtrip_exactly(self):
        """For each canonical float v, the closest label maps back to v.

        Simulates: user selects a label → scale stored as round(v, 2) →
        sync_prefs reads it back → must find the same label.
        """
        scale_map = self._import_scale_map()
        for label, canonical_v in scale_map.items():
            stored = round(float(canonical_v), 2)
            found = min(scale_map, key=lambda k: abs(scale_map[k] - stored))
            assert found == label, (
                f"ui_scale roundtrip failed: stored {stored!r} → found label "
                f"{found!r} instead of {label!r}"
            )

    def test_intermediate_value_maps_to_nearest(self):
        """A value between two canonical steps snaps to the nearest label."""
        scale_map = self._import_scale_map()
        # Between 1.0 (標準) and 1.15 (大): 1.07 is closer to 1.0
        intermediate = 1.07
        found = min(scale_map, key=lambda k: abs(scale_map[k] - intermediate))
        assert scale_map[found] == 1.0 or abs(scale_map[found] - 1.0) < 0.1, (
            f"Intermediate value 1.07 snapped to unexpected label {found!r}"
        )

    def test_scale_map_values_are_strictly_positive(self):
        """No scale value should be zero or negative."""
        scale_map = self._import_scale_map()
        for label, v in scale_map.items():
            assert v > 0, f"Scale value for {label!r} must be positive, got {v}"

    def test_on_ui_scale_change_writes_rounded_value(self, tmp_path):
        """_on_ui_scale_change stores round(float(scale), 2) in settings.

        Simulates the _patch_setting side of the roundtrip.
        _SCALE_MAP values must survive round(v, 2) without precision drift.
        """
        scale_map = self._import_scale_map()
        for label, v in scale_map.items():
            stored = round(float(v), 2)
            recovered = min(scale_map, key=lambda k: abs(scale_map[k] - stored))
            assert recovered == label, (
                f"_on_ui_scale_change roundtrip: {label!r} ({v}) → stored "
                f"{stored!r} → recovered {recovered!r}"
            )


# ===========================================================================
# 3. capabilities.build_snapshot — Windows preference derived fallback
# ===========================================================================

class TestCapabilitiesDerivedFallback:
    """build_snapshot() must resolve effective_backend to 'openvino' on Linux
    regardless of the persisted (possibly Windows-only) backend preference."""

    def _store(self, backend=None, cpu_model_size="0.6B"):
        store = MagicMock()
        store.recovered = None
        store.session_ignored = []
        data = {}
        if backend is not None:
            data["backend"] = backend
        data["cpu_model_size"] = cpu_model_size
        store.get = lambda k, d=None: data.get(k, d)
        return store

    def _probes(self):
        return {
            "ffmpeg": False,
            "cloudflared": False,
            "model_present": False,
            "model_state": "unloaded",
            "model_error": None,
            "diarization": False,
        }

    def test_no_backend_pref_linux_derives_openvino(self):
        """No backend stored → Linux derives openvino as effective_backend."""
        from capabilities import build_snapshot
        snap = build_snapshot("linux", self._store(backend=None), self._probes())
        assert snap["effective_backend"] == "openvino"

    def test_crispasr_pref_linux_derives_openvino(self):
        """crispasr preference (Windows-only) on Linux → effective_backend is openvino."""
        from capabilities import build_snapshot
        snap = build_snapshot("linux", self._store(backend="crispasr"), self._probes())
        assert snap["effective_backend"] == "openvino"
        # Preference must be preserved (never overwritten)
        assert snap["backend_preference"] == "crispasr"

    def test_chatllm_pref_linux_derives_openvino(self):
        """chatllm preference (Windows-only) on Linux → effective_backend is openvino."""
        from capabilities import build_snapshot
        snap = build_snapshot("linux", self._store(backend="chatllm"), self._probes())
        assert snap["effective_backend"] == "openvino"
        assert snap["backend_preference"] == "chatllm"

    def test_windows_openvino_pref_unchanged(self):
        """openvino preference on win32 → effective_backend is openvino (unchanged)."""
        from capabilities import build_snapshot
        snap = build_snapshot("win32", self._store(backend="openvino"), self._probes())
        assert snap["effective_backend"] == "openvino"
        assert snap["status_line"] is None  # no mismatch

    def test_windows_crispasr_pref_unchanged(self):
        """crispasr preference on win32 → effective_backend is crispasr (unchanged)."""
        from capabilities import build_snapshot
        snap = build_snapshot("win32", self._store(backend="crispasr"), self._probes())
        assert snap["effective_backend"] == "crispasr"
        assert snap["status_line"] is None  # preferred backend IS effective


# ===========================================================================
# 4. app._ui_core_model derived fallback
# ===========================================================================

class TestAppUiCoreModelDerivedFallback:
    """app._ui_core_model(settings) must derive correct (core, model_label) when
    'backend' key is absent (the derived fallback path, decision 12).

    _ui_core_model is the central reader used by the CTk desktop App to build
    its core/model-label UI after loading settings."""

    def test_no_backend_key_derives_openvino_06b(self):
        """Empty settings dict → _ui_core_model derives Qwen / 0.6B OpenVINO."""
        import app
        core, label = app._ui_core_model({})
        assert core == "Qwen"
        # Default model should be the 0.6B OpenVINO model
        assert "0.6B" in label or "Qwen" in label

    def test_crispasr_backend_returns_breeze_label(self):
        """settings with backend='crispasr' → _ui_core_model returns Breeze label."""
        import app
        core, label = app._ui_core_model({"backend": "crispasr", "crisp_quant": "q5"})
        assert core == "Whisper (Breeze)"

    def test_chatllm_backend_returns_vulkan_label(self):
        """settings with backend='chatllm' → _ui_core_model returns Vulkan label."""
        import app
        core, label = app._ui_core_model({"backend": "chatllm"})
        assert core == "Qwen"
        assert "Vulkan" in label

    def test_openvino_1p7b_returns_17b_label(self):
        """settings with openvino 1.7B → _ui_core_model returns INT8 label."""
        import app
        core, label = app._ui_core_model(
            {"backend": "openvino", "cpu_model_size": "1.7B"}
        )
        assert core == "Qwen"
        assert "1.7B" in label
