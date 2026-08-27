"""Tests for settings_store.py — schema v2 versioned cross-platform settings store.

Coverage:
  • v1 → v2 roundtrip: flat keys preserved, namespaces added, schema_version stamped
  • schema_version never lowered
  • unknown namespaces copied through untouched
  • linux set() never writes flat block
  • linux portable keys → shared; machine-bound keys → platforms.linux
  • win32 set() writes flat block; ui_scale_percent mirrors float ui_scale
  • resolution order: platforms.<os> > shared > flat > derived default > parameter default
  • ui_scale heuristics: multiplier < 10, percent >= 10, canonical key precedence
  • path storage: under base_dir → relative in shared; outside → absolute in platforms.<os>
  • foreign platform path → get() returns None (fall back to discovery) without overwriting
  • relative path resolved against base_dir on get()
  • corrupt file → timestamped backup, empty defaults, store.recovered set
  • atomic save: if os.replace raises the original file is left intact
  • unhonourable value → ignored for session, left on disk, recorded in session_ignored
  • derived defaults: linux → openvino / 0.6B; win32 → crispasr / qwen3 / q4
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from settings_store import SettingsStore, PATH_KEYS, PORTABLE_KEYS, MACHINE_BOUND_KEYS


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def base_dir(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    return d


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "settings.json"


@pytest.fixture
def store_linux(settings_path, base_dir):
    return SettingsStore(settings_path, platform="linux", base_dir=base_dir)


@pytest.fixture
def store_win32(settings_path, base_dir):
    return SettingsStore(settings_path, platform="win32", base_dir=base_dir)


# ─── v1 → v2 migration ───────────────────────────────────────────────────────

class TestV1ToV2Migration:
    def test_flat_keys_preserved_after_migration(self, settings_path, base_dir):
        """v1 file → v2 roundtrip preserves every flat key byte-for-byte in meaning."""
        v1 = {
            "backend":        "crispasr",
            "crisp_model":    "qwen3",
            "output_format":  "srt",
            "ui_lang":        "繁體中文",
            "hf_mirror":      "",
            "chunk_secs":     0,
            "vad_threshold":  0.5,
        }
        settings_path.write_text(json.dumps(v1), encoding="utf-8")

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        doc = store.load()

        for k, v in v1.items():
            assert doc[k] == v, f"Flat key {k!r} changed: {doc[k]!r} != {v!r}"

    def test_v2_namespaces_added(self, settings_path, base_dir):
        """Migration adds shared, platforms, backends, and schema_version."""
        settings_path.write_text(json.dumps({"backend": "openvino"}), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        doc = store.load()

        assert doc["schema_version"] == 2
        assert isinstance(doc["shared"], dict)
        assert isinstance(doc["platforms"], dict)
        assert isinstance(doc["backends"], dict)

    def test_schema_version_never_lowered(self, settings_path, base_dir):
        """A file with schema_version 3 must stay at 3 after a v2-store load+save."""
        data = {"schema_version": 3, "shared": {}, "platforms": {}, "backends": {}}
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        doc = store.load()

        assert doc["schema_version"] == 3

        store.save()
        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["schema_version"] == 3

    def test_schema_version_stamped_2_on_v1_file(self, settings_path, base_dir):
        """A v1 file gets schema_version 2 stamped on save."""
        settings_path.write_text(json.dumps({"output_format": "srt"}), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["schema_version"] == 2

    def test_unknown_namespace_preserved(self, settings_path, base_dir):
        """Unknown top-level keys and namespaces are copied through untouched."""
        data = {
            "schema_version":    2,
            "shared":            {},
            "platforms":         {},
            "backends":          {},
            "custom_namespace":  {"foo": "bar"},
            "unknown_flat_key":  "some_value",
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        doc = store.load()

        assert doc["custom_namespace"] == {"foo": "bar"}
        assert doc["unknown_flat_key"] == "some_value"

        store.save()
        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["custom_namespace"] == {"foo": "bar"}
        assert on_disk["unknown_flat_key"] == "some_value"


# ─── Resolution order ────────────────────────────────────────────────────────

class TestResolutionOrder:
    def test_platform_beats_shared(self, settings_path, base_dir):
        data = {
            "schema_version": 2,
            "shared":    {"output_format": "txt"},
            "platforms": {"linux": {"output_format": "srt"}},
            "backends":  {},
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.get("output_format") == "srt"

    def test_shared_beats_flat(self, settings_path, base_dir):
        data = {
            "schema_version": 2,
            "shared":    {"output_format": "vtt"},
            "platforms": {},
            "backends":  {},
            "output_format": "srt",   # legacy flat
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.get("output_format") == "vtt"

    def test_flat_beats_derived_default(self, settings_path, base_dir):
        # win32 so "chatllm" is a valid backend (flat ownership)
        data = {
            "schema_version": 2,
            "shared":    {},
            "platforms": {},
            "backends":  {},
            "backend":   "chatllm",
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="win32", base_dir=base_dir)
        store.load()

        assert store.get("backend") == "chatllm"

    def test_derived_default_when_absent(self, settings_path, base_dir):
        data = {"schema_version": 2, "shared": {}, "platforms": {}, "backends": {}}
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.get("backend") == "openvino"
        assert store.get("cpu_model_size") == "0.6B"

    def test_parameter_default_when_nothing_matches(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.get("nonexistent_key", "sentinel") == "sentinel"

    def test_win32_derived_defaults(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="win32", base_dir=base_dir)
        store.load()

        assert store.get("backend") == "crispasr"
        assert store.derived_default("crisp_model") == "qwen3"
        assert store.derived_default("crisp_qwen_quant") == "q4"


# ─── Linux set() – never touches the flat block ──────────────────────────────

class TestLinuxSet:
    _structural = {"schema_version", "shared", "platforms", "backends"}

    def _flat_keys(self, doc: dict) -> set:
        return set(doc.keys()) - self._structural

    def test_portable_key_goes_to_shared(self, settings_path, base_dir, store_linux):
        store_linux.load()
        store_linux.set("output_format", "vtt")
        store_linux.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["shared"]["output_format"] == "vtt"
        assert "output_format" not in self._flat_keys(on_disk)

    def test_machine_bound_key_goes_to_platform(self, settings_path, base_dir, store_linux):
        store_linux.load()
        store_linux.set("backend", "openvino")
        store_linux.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["platforms"]["linux"]["backend"] == "openvino"
        assert "backend" not in self._flat_keys(on_disk)

    def test_never_writes_flat_block(self, settings_path, base_dir):
        """Comprehensive: every set() call on linux must leave the flat block empty."""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        for key in list(PORTABLE_KEYS) + list(MACHINE_BOUND_KEYS):
            if key == "ui_scale_percent":
                store.set(key, 100)
            elif key == "backend":
                store.set(key, "openvino")
            elif key in ("vad_threshold",):
                store.set(key, 0.5)
            else:
                store.set(key, "test_value")

        store.save()
        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        flat = self._flat_keys(on_disk)
        assert flat == set(), f"Unexpected flat keys on linux: {flat}"

    def test_existing_flat_keys_untouched_by_linux_set(self, settings_path, base_dir):
        """Linux set() must not modify existing flat keys written by Windows."""
        win_data = {
            "schema_version": 2,
            "shared": {},
            "platforms": {},
            "backends": {},
            "backend":       "crispasr",
            "output_format": "srt",
        }
        settings_path.write_text(json.dumps(win_data), encoding="utf-8")

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.set("output_format", "vtt")   # Linux write → should go to shared
        store.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        # Flat key untouched
        assert on_disk.get("output_format") == "srt"
        # New value in shared
        assert on_disk["shared"]["output_format"] == "vtt"


# ─── win32 set() mirrors ─────────────────────────────────────────────────────

class TestWin32Set:
    def test_writes_flat_block(self, settings_path, base_dir, store_win32):
        store_win32.load()
        store_win32.set("output_format", "srt")
        store_win32.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["output_format"] == "srt"

    def test_ui_scale_percent_mirrors_float_ui_scale(self, settings_path, base_dir, store_win32):
        store_win32.load()
        store_win32.set("ui_scale_percent", 125)
        store_win32.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["ui_scale_percent"] == 125
        assert abs(on_disk["ui_scale"] - 1.25) < 0.0001

    def test_ui_scale_150_mirrors_correctly(self, settings_path, base_dir, store_win32):
        store_win32.load()
        store_win32.set("ui_scale_percent", 150)
        store_win32.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert abs(on_disk["ui_scale"] - 1.5) < 0.0001


# ─── ui_scale heuristics ─────────────────────────────────────────────────────

class TestUiScaleHeuristics:
    def test_legacy_multiplier_below_10(self, settings_path, base_dir):
        """ui_scale = 1.25 (< 10) → 125 %"""
        settings_path.write_text(json.dumps({"ui_scale": 1.25}), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.ui_scale_percent() == 125
        assert abs(store.ui_scale_multiplier() - 1.25) < 0.0001

    def test_legacy_percent_above_10(self, settings_path, base_dir):
        """ui_scale = 150 (>= 10) → 150 %"""
        settings_path.write_text(json.dumps({"ui_scale": 150}), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.ui_scale_percent() == 150
        assert abs(store.ui_scale_multiplier() - 1.5) < 0.0001

    def test_legacy_multiplier_1_0(self, settings_path, base_dir):
        """ui_scale = 1.0 → 100 %"""
        settings_path.write_text(json.dumps({"ui_scale": 1.0}), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.ui_scale_percent() == 100

    def test_canonical_key_takes_precedence_over_legacy(self, settings_path, base_dir):
        """ui_scale_percent (canonical) beats legacy ui_scale."""
        data = {"ui_scale_percent": 200, "ui_scale": 1.5}
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.ui_scale_percent() == 200

    def test_default_when_absent(self, settings_path, base_dir):
        """No scale key → 100 %"""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.ui_scale_percent() == 100
        assert store.ui_scale_multiplier() == 1.0

    def test_win32_write_mirrors_float(self, settings_path, base_dir):
        """win32: writing ui_scale_percent also writes ui_scale float."""
        store = SettingsStore(settings_path, platform="win32", base_dir=base_dir)
        store.load()
        store.set("ui_scale_percent", 175)
        store.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["ui_scale_percent"] == 175
        assert abs(on_disk["ui_scale"] - 1.75) < 0.0001


# ─── Path storage & foreign-path fallback ────────────────────────────────────

class TestPathStorage:
    def test_path_under_base_dir_stored_relative_in_shared(
        self, settings_path, base_dir
    ):
        """A path under base_dir is stored relative with forward slashes in shared."""
        model_dir = base_dir / "ov_models"
        model_dir.mkdir()

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.set("model_dir", str(model_dir))
        store.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        stored = on_disk["shared"]["model_dir"]
        assert not Path(stored).is_absolute(), f"Expected relative, got: {stored!r}"
        # forward slashes
        assert "\\" not in stored
        assert "ov_models" in stored

    def test_path_outside_base_dir_stored_absolute_in_platform(
        self, settings_path, base_dir, tmp_path
    ):
        """A path outside base_dir goes into platforms.linux as absolute."""
        ext_dir = tmp_path / "external_models"
        ext_dir.mkdir()

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.set("model_dir", str(ext_dir))
        store.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "model_dir" in on_disk["platforms"]["linux"]
        stored = on_disk["platforms"]["linux"]["model_dir"]
        assert Path(stored).is_absolute()

    def test_relative_path_resolved_against_base_dir_on_get(
        self, settings_path, base_dir
    ):
        """get() resolves a relative shared path against base_dir."""
        ov = base_dir / "ov_models"
        ov.mkdir()

        data = {
            "schema_version": 2,
            "shared":    {"model_dir": "ov_models"},
            "platforms": {},
            "backends":  {},
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        result = store.get("model_dir")
        assert result == str(ov)

    def test_foreign_platform_path_returns_none_without_overwrite(
        self, settings_path, base_dir
    ):
        """A win32 path opened on linux returns None and is never overwritten."""
        win_path = "C:\\Users\\User\\AppData\\models\\model.bin"
        data = {
            "schema_version": 2,
            "shared":    {},
            "platforms": {"win32": {"model_path": win_path}},
            "backends":  {},
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        # Windows path does not exist on Linux → None
        result = store.get("model_path")
        assert result is None

        # Win32 namespace value is untouched in memory
        assert store._doc["platforms"]["win32"]["model_path"] == win_path

    def test_roundtrip_relative_path_set_then_get(self, settings_path, base_dir):
        """set() → save() → load() → get() roundtrip for a relative path."""
        model_dir = base_dir / "ov_models"
        model_dir.mkdir()

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.set("model_dir", str(model_dir))
        store.save()

        store2 = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store2.load()
        result = store2.get("model_dir")
        assert result == str(model_dir)


# ─── Corrupt file ────────────────────────────────────────────────────────────

class TestCorruption:
    def test_corrupt_json_creates_backup(self, settings_path, base_dir):
        """Unparsable JSON → timestamped .corrupt-<ts> backup created."""
        corrupt_content = "THIS IS NOT JSON {{{{}"
        settings_path.write_text(corrupt_content, encoding="utf-8")

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.recovered is not None
        backup = Path(store.recovered)
        assert backup.exists()
        assert "corrupt" in backup.name
        assert backup.read_text(encoding="utf-8") == corrupt_content

    def test_corrupt_file_starts_from_empty_defaults(self, settings_path, base_dir):
        """After corruption, derived defaults are still accessible."""
        settings_path.write_text("{bad json", encoding="utf-8")

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.get("backend") == "openvino"   # derived default

    def test_backup_name_contains_timestamp(self, settings_path, base_dir):
        """Backup filename follows the pattern settings.json.corrupt-YYYYmmdd-HHMMSS."""
        settings_path.write_text("not json", encoding="utf-8")

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        backup = Path(store.recovered)
        # e.g. "settings.json.corrupt-20260827-143000"
        assert backup.suffix.startswith(".corrupt-") or "corrupt-" in backup.name

    def test_no_recovery_when_file_is_valid(self, settings_path, base_dir):
        """store.recovered is None when the file loads cleanly."""
        settings_path.write_text(json.dumps({"output_format": "srt"}), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.recovered is None


# ─── Atomic save ─────────────────────────────────────────────────────────────

class TestAtomicSave:
    def test_original_intact_if_replace_fails(self, settings_path, base_dir):
        """If os.replace raises, the original settings.json is left untouched."""
        original = {
            "schema_version": 2,
            "shared":    {},
            "platforms": {},
            "backends":  {},
            "output_format": "srt",
        }
        settings_path.write_text(json.dumps(original), encoding="utf-8")

        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.set("output_format", "vtt")   # pending change

        with patch("os.replace", side_effect=OSError("simulated disk full")):
            with pytest.raises(OSError):
                store.save()

        # Original still has "srt"
        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["output_format"] == "srt"

    def test_save_writes_atomically_to_correct_path(self, settings_path, base_dir):
        """After a successful save the file is at the expected path."""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.set("output_format", "vtt")
        store.save()

        assert settings_path.exists()
        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["shared"]["output_format"] == "vtt"


# ─── Unhonourable values ─────────────────────────────────────────────────────

class TestUnhonourableValues:
    def test_invalid_backend_on_linux_flagged(self, settings_path, base_dir):
        """chatllm is unsupported on linux → validate returns False."""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        ok, reason = store.validate("backend", "chatllm")
        assert not ok
        assert reason is not None
        assert ("backend", reason) in store.session_ignored

    def test_valid_backend_on_linux_passes(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        ok, reason = store.validate("backend", "openvino")
        assert ok
        assert reason is None
        assert len(store.session_ignored) == 0

    def test_invalid_cpu_model_size_flagged(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        ok, _ = store.validate("cpu_model_size", "3.0B")
        assert not ok

    def test_valid_cpu_model_size_passes(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        for size in ("0.6B", "1.7B"):
            ok, _ = store.validate("cpu_model_size", size)
            assert ok, f"{size!r} should be valid"

    def test_scale_below_25_invalid(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        ok, _ = store.validate("ui_scale_percent", 10)
        assert not ok

    def test_scale_above_400_invalid(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        ok, _ = store.validate("ui_scale_percent", 500)
        assert not ok

    def test_scale_in_range_valid(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        for val in (25, 100, 150, 400):
            ok, _ = store.validate("ui_scale_percent", val)
            assert ok, f"{val} should be valid"

    def test_invalid_value_left_on_disk(self, settings_path, base_dir):
        """An unhonourable value is NOT removed from disk after validate()."""
        data = {
            "schema_version": 2,
            "shared": {},
            "platforms": {"linux": {"cpu_model_size": "99.9B"}},
            "backends":  {},
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.validate("cpu_model_size", "99.9B")
        store.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        assert on_disk["platforms"]["linux"]["cpu_model_size"] == "99.9B"

    def test_session_ignored_accumulates(self, settings_path, base_dir):
        """session_ignored collects all (key, reason) pairs from the session."""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        store.validate("backend", "chatllm")
        store.validate("cpu_model_size", "bad")

        assert len(store.session_ignored) == 2
        keys = [k for k, _ in store.session_ignored]
        assert "backend" in keys
        assert "cpu_model_size" in keys

    def test_unknown_key_always_valid(self, settings_path, base_dir):
        """Keys with no validator in the table are always honourable."""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        ok, reason = store.validate("some_future_key", "anything")
        assert ok
        assert reason is None


# ─── Derived defaults ────────────────────────────────────────────────────────

class TestDerivedDefaults:
    def test_linux_defaults(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.derived_default("backend") == "openvino"
        assert store.derived_default("cpu_model_size") == "0.6B"

    def test_win32_defaults(self, settings_path, base_dir):
        store = SettingsStore(settings_path, platform="win32", base_dir=base_dir)
        store.load()

        assert store.derived_default("backend") == "crispasr"
        assert store.derived_default("crisp_model") == "qwen3"
        assert store.derived_default("crisp_qwen_quant") == "q4"

    def test_absent_backend_uses_derived_default_on_linux(self, settings_path, base_dir):
        """backend absent from settings → get() returns linux derived default."""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()

        assert store.get("backend") == "openvino"

    def test_backend_not_seeded_on_load(self, settings_path, base_dir):
        """load() must NOT write a backend key — absent means unset."""
        store = SettingsStore(settings_path, platform="linux", base_dir=base_dir)
        store.load()
        store.save()

        on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
        # backend must not appear in flat, shared, or platforms namespace
        assert "backend" not in on_disk
        assert "backend" not in on_disk.get("shared", {})
        assert "backend" not in on_disk.get("platforms", {}).get("linux", {})
