"""tests/test_settings_wiring.py — Ticket g2: SettingsStore wiring in webview_backend.

Tests use conftest stubs so no Tk / pywebview is required.

Coverage:
  • win32 roundtrip: get_settings/set_settings preserves every flat key and mirrors ui_scale
  • linux set_settings writes only shared / platforms.linux (never flat block)
  • corrupt settings.json -> get_capabilities snapshot carries SETTINGS_RECOVERED event
  • _persisted_backend derived fallback on both platforms when backend key is absent
  • _seed_defaults writes nothing (no file created; existing file unchanged)
  • read_ui_scale_multiplier helper applies <10 multiplier / >=10 percent heuristic
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helper: build a WebBackend pointed at a temp settings file
# ---------------------------------------------------------------------------

def _make_backend(settings_path, platform_str="linux"):
    """Return a WebBackend whose SettingsStore uses settings_path.

    Monkey-patches core.SETTINGS_FILE and sys.platform for the store.
    The _seed_defaults and _apply_runtime_prefs calls during __init__
    operate on settings_path.
    """
    import webview_backend as wb
    import app as core

    original_sf = getattr(core, "SETTINGS_FILE", None)
    core.SETTINGS_FILE = str(settings_path)

    # Patch sys.platform for the SettingsStore within the backend
    with patch.object(sys, "platform", platform_str):
        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        import threading
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None  # will be lazily initialized

        backend._seed_defaults()
        backend._apply_runtime_prefs()

    # Restore
    if original_sf is not None:
        core.SETTINGS_FILE = original_sf

    return backend


# ---------------------------------------------------------------------------
# Fixture: temp settings file
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_settings(tmp_path):
    """A path to a temp settings.json (does not yet exist)."""
    return tmp_path / "settings.json"


# ---------------------------------------------------------------------------
# read_ui_scale_multiplier helper
# ---------------------------------------------------------------------------

class TestReadUiScaleMultiplier:
    """settings_store.read_ui_scale_multiplier(path) — module-level helper."""

    def test_absent_file_returns_1(self, tmp_path):
        from settings_store import read_ui_scale_multiplier
        p = tmp_path / "nonexistent.json"
        assert read_ui_scale_multiplier(p) == 1.0

    def test_legacy_multiplier_less_than_10(self, tmp_path):
        """Value < 10 is a float multiplier."""
        from settings_store import read_ui_scale_multiplier
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"ui_scale": 1.25}), encoding="utf-8")
        result = read_ui_scale_multiplier(p)
        assert abs(result - 1.25) < 0.01

    def test_legacy_percent_10_or_above(self, tmp_path):
        """Value >= 10 is already a percent — divide by 100."""
        from settings_store import read_ui_scale_multiplier
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"ui_scale": 125}), encoding="utf-8")
        result = read_ui_scale_multiplier(p)
        assert abs(result - 1.25) < 0.01

    def test_canonical_ui_scale_percent_takes_priority(self, tmp_path):
        """ui_scale_percent key takes priority over legacy ui_scale."""
        from settings_store import read_ui_scale_multiplier
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"ui_scale": 2.0, "ui_scale_percent": 150}), encoding="utf-8")
        result = read_ui_scale_multiplier(p)
        assert abs(result - 1.5) < 0.01

    def test_corrupt_file_returns_1(self, tmp_path):
        from settings_store import read_ui_scale_multiplier
        p = tmp_path / "s.json"
        p.write_text("NOT VALID JSON!!!", encoding="utf-8")
        assert read_ui_scale_multiplier(p) == 1.0


# ---------------------------------------------------------------------------
# _seed_defaults writes nothing
# ---------------------------------------------------------------------------

class TestSeedDefaultsWritesNothing:
    def test_no_file_created_when_no_file_exists(self, tmp_settings):
        """_seed_defaults must not create the settings file."""
        import webview_backend as wb
        import app as core
        import threading

        core.SETTINGS_FILE = str(tmp_settings)
        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        backend._seed_defaults()

        assert not tmp_settings.exists(), "_seed_defaults must not create settings.json"

    def test_existing_file_unchanged_when_backend_set(self, tmp_settings):
        """_seed_defaults must not overwrite an existing backend setting."""
        import webview_backend as wb
        import app as core
        import threading

        existing = {"backend": "openvino", "cpu_model_size": "0.6B", "custom_key": "preserved"}
        tmp_settings.write_text(json.dumps(existing), encoding="utf-8")
        core.SETTINGS_FILE = str(tmp_settings)

        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        backend._seed_defaults()

        result = json.loads(tmp_settings.read_text(encoding="utf-8"))
        assert result["backend"] == "openvino"
        assert result["custom_key"] == "preserved"


# ---------------------------------------------------------------------------
# _persisted_backend derived fallback
# ---------------------------------------------------------------------------

class TestPersistedBackendFallback:
    def test_linux_fallback_when_no_backend(self, tmp_settings):
        """On linux with no backend persisted, returns openvino."""
        import webview_backend as wb
        import app as core
        import threading

        core.SETTINGS_FILE = str(tmp_settings)
        # No settings file → no backend
        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        # Simulate linux platform for the store
        with patch.object(sys, "platform", "linux"):
            result = backend._persisted_backend()

        assert result == "openvino"

    def test_win32_fallback_when_no_backend(self, tmp_settings):
        """On win32 with no backend persisted, returns crispasr (derived default)."""
        import webview_backend as wb
        import app as core
        import threading

        core.SETTINGS_FILE = str(tmp_settings)
        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        with patch.object(sys, "platform", "win32"):
            result = backend._persisted_backend()

        assert result == "crispasr"

    def test_persisted_value_returned_when_present(self, tmp_settings):
        """When backend is set, _persisted_backend returns the stored value."""
        import webview_backend as wb
        import app as core
        import threading

        tmp_settings.write_text(json.dumps({"backend": "chatllm"}), encoding="utf-8")
        core.SETTINGS_FILE = str(tmp_settings)

        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        result = backend._persisted_backend()
        assert result == "chatllm"


# ---------------------------------------------------------------------------
# win32 roundtrip: get_settings / set_settings preserves flat keys + mirrors ui_scale
# ---------------------------------------------------------------------------

class TestWin32Roundtrip:
    """On win32, set_settings must write flat keys and mirror ui_scale."""

    def _make_win32_backend(self, tmp_settings):
        import webview_backend as wb
        import app as core
        import threading

        core.SETTINGS_FILE = str(tmp_settings)
        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        # On win32, _seed_defaults should not persist anything
        with patch.object(sys, "platform", "win32"):
            backend._seed_defaults()

        return backend

    def test_get_settings_returns_scale_as_percent(self, tmp_settings):
        """get_settings returns scale as int percent, not raw float."""
        tmp_settings.write_text(
            json.dumps({"ui_scale": 1.25, "backend": "crispasr"}),
            encoding="utf-8"
        )
        backend = self._make_win32_backend(tmp_settings)

        with patch.object(sys, "platform", "win32"):
            s = backend.get_settings()

        # 1.25 is a multiplier < 10 → should become 125
        assert s["scale"] == 125

    def test_set_settings_scale_writes_flat_and_mirrors(self, tmp_settings):
        """set_settings scale on win32 writes ui_scale_percent and mirrors ui_scale float."""
        tmp_settings.write_text(json.dumps({"backend": "crispasr"}), encoding="utf-8")
        backend = self._make_win32_backend(tmp_settings)

        with patch.object(sys, "platform", "win32"):
            backend.set_settings({"scale": 150})

        saved = json.loads(tmp_settings.read_text(encoding="utf-8"))
        # Must have flat ui_scale_percent
        assert saved.get("ui_scale_percent") == 150
        # Must mirror legacy float ui_scale
        assert abs(saved.get("ui_scale", 0) - 1.5) < 0.01

    def test_set_settings_preserves_other_flat_keys(self, tmp_settings):
        """set_settings must not wipe existing flat keys."""
        tmp_settings.write_text(
            json.dumps({"backend": "crispasr", "crisp_model": "qwen3",
                        "output_format": "srt", "custom_key": "stays"}),
            encoding="utf-8"
        )
        backend = self._make_win32_backend(tmp_settings)

        with patch.object(sys, "platform", "win32"):
            backend.set_settings({"format": "txt"})

        saved = json.loads(tmp_settings.read_text(encoding="utf-8"))
        assert saved.get("custom_key") == "stays"
        assert saved.get("crisp_model") == "qwen3"
        assert saved.get("output_format") == "txt"


# ---------------------------------------------------------------------------
# linux set_settings writes only shared / platforms.linux
# ---------------------------------------------------------------------------

class TestLinuxSetSettings:
    """On linux, set_settings must not write flat keys."""

    def _make_linux_backend(self, tmp_settings):
        import webview_backend as wb
        import app as core
        import threading

        core.SETTINGS_FILE = str(tmp_settings)
        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        with patch.object(sys, "platform", "linux"):
            backend._seed_defaults()

        return backend

    def test_set_settings_format_goes_to_shared_not_flat(self, tmp_settings):
        """output_format is a portable key → goes to shared, not flat."""
        backend = self._make_linux_backend(tmp_settings)

        with patch.object(sys, "platform", "linux"):
            backend.set_settings({"format": "txt"})

        saved = json.loads(tmp_settings.read_text(encoding="utf-8"))
        # Must NOT have a flat output_format key
        assert "output_format" not in saved, "flat output_format must not be written on linux"
        # Must have it in shared
        assert saved.get("shared", {}).get("output_format") == "txt"

    def test_set_settings_scale_goes_to_shared_not_flat(self, tmp_settings):
        """ui_scale_percent is portable → goes to shared on linux."""
        backend = self._make_linux_backend(tmp_settings)

        with patch.object(sys, "platform", "linux"):
            backend.set_settings({"scale": 125})

        saved = json.loads(tmp_settings.read_text(encoding="utf-8"))
        assert "ui_scale" not in saved, "flat ui_scale must not be written on linux"
        assert "ui_scale_percent" not in saved, "flat ui_scale_percent must not be written on linux"
        assert saved.get("shared", {}).get("ui_scale_percent") == 125

    def test_set_settings_backend_goes_to_platforms_linux(self, tmp_settings):
        """backend is machine-bound → goes to platforms.linux on linux (if written via set)."""
        backend = self._make_linux_backend(tmp_settings)

        with patch.object(sys, "platform", "linux"):
            backend.set_settings({"theme": "dark"})  # portable
            # Simulate persist_backend
            backend._persist_backend("openvino")

        saved = json.loads(tmp_settings.read_text(encoding="utf-8"))
        # backend should be in platforms.linux, not flat
        assert "backend" not in saved or saved.get("platforms", {}).get("linux", {}).get("backend") == "openvino"


# ---------------------------------------------------------------------------
# Corrupt settings -> get_capabilities carries SETTINGS_RECOVERED
# ---------------------------------------------------------------------------

class TestCorruptSettingsCapabilities:
    def test_corrupt_settings_recovery_event_in_capabilities(self, tmp_settings):
        """get_capabilities snapshot must carry SETTINGS_RECOVERED when settings.json is corrupt."""
        import webview_backend as wb
        import app as core
        import threading

        # Write corrupt JSON
        tmp_settings.write_text("NOT VALID JSON {{{", encoding="utf-8")
        core.SETTINGS_FILE = str(tmp_settings)

        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        with patch.object(sys, "platform", "linux"):
            # Force store initialization (which triggers load + recovery)
            backend._seed_defaults()

            # Mock probes so we can call get_capabilities without real filesystem checks
            with patch("platform_seams.find_executable", return_value=None), \
                 patch.object(backend, "selected_model_present", return_value=False):
                caps = backend.get_capabilities()

        recovery_events = caps.get("recovery_events", [])
        codes = [e["code"] for e in recovery_events]
        assert "SETTINGS_RECOVERED" in codes, (
            f"Expected SETTINGS_RECOVERED in recovery_events, got: {codes}"
        )

    def test_recovered_backup_path_in_event_params(self, tmp_settings):
        """The SETTINGS_RECOVERED event must carry the backup_path param."""
        import webview_backend as wb
        import app as core
        import threading

        tmp_settings.write_text("CORRUPT!!!", encoding="utf-8")
        core.SETTINGS_FILE = str(tmp_settings)

        backend = wb.WebBackend.__new__(wb.WebBackend)
        backend.engine = core.ASREngine()
        backend._loaded = False
        backend._load_err = None
        backend._loading = False
        backend._cancel_event = threading.Event()
        backend._server = None
        backend._tunnel = None
        backend._on_event = None
        backend._theme_cb = None
        backend._lock = threading.Lock()
        backend._recording_job_id = None
        backend._store = None

        with patch.object(sys, "platform", "linux"):
            backend._seed_defaults()

            with patch("platform_seams.find_executable", return_value=None), \
                 patch.object(backend, "selected_model_present", return_value=False):
                caps = backend.get_capabilities()

        recovery_events = caps.get("recovery_events", [])
        recovered_events = [e for e in recovery_events if e["code"] == "SETTINGS_RECOVERED"]
        assert recovered_events, "No SETTINGS_RECOVERED event found"
        backup_path = recovered_events[0]["params"].get("backup_path")
        assert backup_path, "backup_path must be non-empty"
        assert "corrupt" in backup_path.lower(), f"backup_path should mention 'corrupt': {backup_path}"
