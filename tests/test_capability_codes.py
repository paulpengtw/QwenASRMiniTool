"""Tests for capability_codes.py."""

import json
import re
import pytest

from capability_codes import CODES, render, as_json


class TestRegistry:
    def test_all_codes_have_en_zh_severity(self):
        for code, entry in CODES.items():
            assert "en" in entry, f"{code} missing 'en'"
            assert "zh" in entry, f"{code} missing 'zh'"
            assert "severity" in entry, f"{code} missing 'severity'"
            assert entry["severity"] in ("fatal", "degraded", "info"), (
                f"{code} has invalid severity: {entry['severity']}"
            )

    def test_all_params_in_en_also_in_zh(self):
        param_re = re.compile(r"\{(\w+)\}")
        for code, entry in CODES.items():
            en_params = set(param_re.findall(entry["en"]))
            zh_params = set(param_re.findall(entry["zh"]))
            assert en_params == zh_params, (
                f"{code}: en params {en_params} != zh params {zh_params}"
            )

    def test_required_codes_present(self):
        required = [
            "PY_VERSION_TOO_OLD",
            "BASE_DIR_NOT_WRITABLE",
            "LOOPBACK_PORT_UNAVAILABLE",
            "DEP_IMPORT_FAILED",
            "FFMPEG_MISSING",
            "BROWSER_OPEN_FAILED",
            "VAD_MISSING",
            "MODEL_MISSING",
            "CA_CERTS_MISSING",
            "CLOUDFLARED_MISSING",
            "ALIGN_WINDOWS_ONLY",
            "BACKEND_PLATFORM_UNSUPPORTED",
            "USING_OPENVINO_CPU_UBUNTU_PREF_PRESERVED",
            "SETTINGS_RECOVERED",
            "UV_ENV_OUT_OF_DATE",
        ]
        for code in required:
            assert code in CODES, f"Missing required code: {code}"


class TestRender:
    def test_render_en_with_params(self):
        result = render("DEP_IMPORT_FAILED", {"module": "numpy"}, lang="en")
        assert "numpy" in result
        assert "numpy" in result

    def test_render_zh_with_params(self):
        result = render("DEP_IMPORT_FAILED", {"module": "numpy"}, lang="zh")
        assert "numpy" in result
        # Should contain Chinese characters
        assert any("一" <= c <= "鿿" for c in result)

    def test_render_unknown_code_returns_code_itself(self):
        result = render("TOTALLY_UNKNOWN_CODE_XYZ", {}, lang="en")
        assert result == "TOTALLY_UNKNOWN_CODE_XYZ"

    def test_render_unknown_code_zh_returns_code_itself(self):
        result = render("TOTALLY_UNKNOWN_CODE_XYZ", {}, lang="zh")
        assert result == "TOTALLY_UNKNOWN_CODE_XYZ"

    def test_render_unknown_code_does_not_raise(self):
        # Must not raise for any code
        render("COMPLETELY_BOGUS", None, "en")
        render("COMPLETELY_BOGUS", None, "zh")

    def test_render_no_params_needed(self):
        result = render("FFMPEG_MISSING", {}, lang="en")
        assert "FFmpeg" in result

    def test_render_model_missing(self):
        result = render("MODEL_MISSING", {"model": "whisper-large"}, lang="en")
        assert "whisper-large" in result

    def test_render_settings_recovered(self):
        result = render("SETTINGS_RECOVERED", {"backup_path": "/home/user/.backup"}, lang="zh")
        assert "/home/user/.backup" in result

    def test_render_default_lang_is_en(self):
        result_default = render("FFMPEG_MISSING", {})
        result_en = render("FFMPEG_MISSING", {}, lang="en")
        assert result_default == result_en

    def test_render_none_params_treated_as_empty(self):
        # Should not raise
        result = render("FFMPEG_MISSING", None, "en")
        assert isinstance(result, str)


class TestAsJson:
    def test_as_json_returns_valid_json(self):
        data = json.loads(as_json())
        assert isinstance(data, dict)

    def test_as_json_contains_all_codes(self):
        data = json.loads(as_json())
        for code in CODES:
            assert code in data

    def test_as_json_preserves_structure(self):
        data = json.loads(as_json())
        for code, entry in data.items():
            assert "en" in entry
            assert "zh" in entry
            assert "severity" in entry
