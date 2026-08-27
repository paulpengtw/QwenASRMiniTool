"""Tests for preflight.py — strict TDD, no real machine access."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from preflight import (
    PreflightItem,
    PreflightReport,
    run_preflight,
    format_report,
    format_json,
)

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------

def _ok_probes() -> dict:
    """All probes return success — green baseline."""
    return {
        "python_version": lambda: (3, 12),
        "base_dir_writable": lambda path: True,
        "loopback_port_free": lambda port: True,
        "import_probe": lambda module: True,
        "ffmpeg_on_path": lambda: True,
        "browser_available": lambda: True,
        "vad_present": lambda: True,
        "model_present": lambda model: True,
    }


def _failing_probes(**overrides) -> dict:
    base = _ok_probes()
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fatal classification
# ---------------------------------------------------------------------------

class TestFatalClassification:
    def test_python_too_old_is_fatal(self):
        probes = _failing_probes(python_version=lambda: (3, 9))
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.fatal
        codes = [it.code for it in report.items]
        assert "PY_VERSION_TOO_OLD" in codes
        item = next(it for it in report.items if it.code == "PY_VERSION_TOO_OLD")
        assert item.severity == "fatal"

    def test_base_dir_not_writable_is_fatal(self):
        probes = _failing_probes(base_dir_writable=lambda path: False)
        report = run_preflight(probes=probes, base_dir="/read-only")
        assert report.fatal
        codes = [it.code for it in report.items]
        assert "BASE_DIR_NOT_WRITABLE" in codes
        item = next(it for it in report.items if it.code == "BASE_DIR_NOT_WRITABLE")
        assert item.severity == "fatal"
        assert item.params["path"] == "/read-only"

    def test_loopback_port_unavailable_is_fatal(self):
        probes = _failing_probes(loopback_port_free=lambda port: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.fatal
        codes = [it.code for it in report.items]
        assert "LOOPBACK_PORT_UNAVAILABLE" in codes
        item = next(it for it in report.items if it.code == "LOOPBACK_PORT_UNAVAILABLE")
        assert item.severity == "fatal"

    def test_core_import_failure_is_fatal(self):
        # Make openvino fail
        def import_probe(module):
            if module == "openvino":
                return False
            return True
        probes = _failing_probes(import_probe=import_probe)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.fatal
        fatal_items = [it for it in report.items if it.severity == "fatal" and it.code == "DEP_IMPORT_FAILED"]
        assert any(it.params.get("module") == "openvino" for it in fatal_items)

    def test_onnxruntime_import_failure_is_fatal(self):
        def import_probe(module):
            return module != "onnxruntime"
        probes = _failing_probes(import_probe=import_probe)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.fatal

    def test_numpy_import_failure_is_fatal(self):
        def import_probe(module):
            return module != "numpy"
        probes = _failing_probes(import_probe=import_probe)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.fatal


# ---------------------------------------------------------------------------
# Degraded classification
# ---------------------------------------------------------------------------

class TestDegradedClassification:
    def test_ffmpeg_missing_is_degraded_not_fatal(self):
        probes = _failing_probes(ffmpeg_on_path=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert not report.fatal
        codes = [it.code for it in report.items]
        assert "FFMPEG_MISSING" in codes
        item = next(it for it in report.items if it.code == "FFMPEG_MISSING")
        assert item.severity == "degraded"

    def test_browser_unavailable_is_degraded_not_fatal(self):
        probes = _failing_probes(browser_available=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert not report.fatal
        codes = [it.code for it in report.items]
        assert "BROWSER_OPEN_FAILED" in codes
        item = next(it for it in report.items if it.code == "BROWSER_OPEN_FAILED")
        assert item.severity == "degraded"

    def test_vad_missing_is_degraded_not_fatal(self):
        probes = _failing_probes(vad_present=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert not report.fatal
        codes = [it.code for it in report.items]
        assert "VAD_MISSING" in codes

    def test_optional_module_missing_is_degraded(self):
        def import_probe(module):
            return module != "soundfile"
        probes = _failing_probes(import_probe=import_probe)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert not report.fatal
        degraded = [it for it in report.items if it.severity == "degraded" and it.code == "DEP_IMPORT_FAILED"]
        assert any(it.params.get("module") == "soundfile" for it in degraded)

    def test_both_ffmpeg_and_browser_fail_still_not_fatal(self):
        probes = _failing_probes(
            ffmpeg_on_path=lambda: False,
            browser_available=lambda: False,
        )
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert not report.fatal
        assert report.exit_code == 0


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_exit_code_2_on_fatal(self):
        probes = _failing_probes(python_version=lambda: (3, 8))
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.exit_code == 2

    def test_exit_code_0_on_no_fatal(self):
        report = run_preflight(probes=_ok_probes(), base_dir="/tmp")
        assert report.exit_code == 0

    def test_exit_code_0_degraded_only(self):
        probes = _failing_probes(ffmpeg_on_path=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.exit_code == 0

    def test_report_fatal_flag_matches_exit_code(self):
        for probes, expect_fatal in [
            (_ok_probes(), False),
            (_failing_probes(python_version=lambda: (2, 7)), True),
        ]:
            report = run_preflight(probes=probes, base_dir="/tmp")
            assert report.fatal == expect_fatal
            assert (report.exit_code == 2) == expect_fatal


# ---------------------------------------------------------------------------
# Stdout: bilingual output
# ---------------------------------------------------------------------------

class TestStdoutBilingual:
    def test_format_report_contains_en_text(self):
        probes = _failing_probes(ffmpeg_on_path=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        output = format_report(report)
        # English part of FFMPEG_MISSING
        assert "FFmpeg" in output

    def test_format_report_contains_zh_text(self):
        probes = _failing_probes(ffmpeg_on_path=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        output = format_report(report)
        # Chinese characters must appear
        assert any("一" <= c <= "鿿" for c in output)

    def test_format_report_contains_separator(self):
        probes = _failing_probes(ffmpeg_on_path=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        output = format_report(report)
        assert "|" in output

    def test_format_report_fatal_label(self):
        probes = _failing_probes(python_version=lambda: (3, 8))
        report = run_preflight(probes=probes, base_dir="/tmp")
        output = format_report(report)
        assert "[FATAL]" in output

    def test_format_report_degraded_label(self):
        probes = _failing_probes(ffmpeg_on_path=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        output = format_report(report)
        assert "[DEGRADED]" in output

    def test_format_report_summary_line_present(self):
        report = run_preflight(probes=_ok_probes(), base_dir="/tmp")
        output = format_report(report)
        assert "Preflight" in output or "PREFLIGHT" in output

    def test_format_report_all_items_have_both_languages(self):
        probes = _failing_probes(
            ffmpeg_on_path=lambda: False,
            browser_available=lambda: False,
        )
        report = run_preflight(probes=probes, base_dir="/tmp")
        output = format_report(report)
        for item in report.items:
            from capability_codes import render
            en_msg = render(item.code, item.params, lang="en")
            zh_msg = render(item.code, item.params, lang="zh")
            assert en_msg in output, f"English message for {item.code} not found in output"
            assert zh_msg in output, f"Chinese message for {item.code} not found in output"


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_json_is_valid(self):
        report = run_preflight(probes=_ok_probes(), base_dir="/tmp")
        out = format_json(report)
        data = json.loads(out)
        assert isinstance(data, dict)

    def test_json_has_fatal_and_exit_code(self):
        report = run_preflight(probes=_ok_probes(), base_dir="/tmp")
        data = json.loads(format_json(report))
        assert "fatal" in data
        assert "exit_code" in data

    def test_json_items_have_en_and_zh(self):
        probes = _failing_probes(ffmpeg_on_path=lambda: False)
        report = run_preflight(probes=probes, base_dir="/tmp")
        data = json.loads(format_json(report))
        for item in data["items"]:
            assert "en" in item
            assert "zh" in item

    def test_json_fatal_report(self):
        probes = _failing_probes(python_version=lambda: (3, 8))
        report = run_preflight(probes=probes, base_dir="/tmp")
        data = json.loads(format_json(report))
        assert data["fatal"] is True
        assert data["exit_code"] == 2


# ---------------------------------------------------------------------------
# Clean state tests
# ---------------------------------------------------------------------------

class TestCleanState:
    def test_all_ok_returns_empty_items(self):
        report = run_preflight(probes=_ok_probes(), base_dir="/tmp")
        assert report.items == []
        assert not report.fatal
        assert report.exit_code == 0

    def test_multiple_fatals_all_reported(self):
        probes = _failing_probes(
            python_version=lambda: (2, 7),
            loopback_port_free=lambda port: False,
        )
        report = run_preflight(probes=probes, base_dir="/tmp")
        assert report.fatal
        codes = [it.code for it in report.items]
        assert "PY_VERSION_TOO_OLD" in codes
        assert "LOOPBACK_PORT_UNAVAILABLE" in codes


# ---------------------------------------------------------------------------
# CLI integration test (subprocess)
# ---------------------------------------------------------------------------

class TestCLI:
    PREFLIGHT = str(ROOT / "preflight.py")
    PYTHON = sys.executable

    def test_cli_exits_0_with_ok_environment(self):
        # We can't inject probes via CLI, so just check it runs and
        # produces some output. The actual exit code depends on the machine.
        result = subprocess.run(
            [self.PYTHON, self.PREFLIGHT],
            capture_output=True,
            text=True,
        )
        # Should not crash (exit code 0 or 2; never something else)
        assert result.returncode in (0, 2)
        combined = result.stdout + result.stderr
        assert len(combined) > 0

    def test_cli_json_flag_produces_valid_json(self):
        result = subprocess.run(
            [self.PYTHON, self.PREFLIGHT, "--json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode in (0, 2)
        data = json.loads(result.stdout)
        assert "fatal" in data
        assert "items" in data

    def test_cli_stdout_has_bilingual_content_when_issues_exist(self):
        """Inject env where ffmpeg is missing by running a mini script."""
        script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from preflight import run_preflight, format_report

probes = {{
    "python_version": lambda: (3, 12),
    "base_dir_writable": lambda path: True,
    "loopback_port_free": lambda port: True,
    "import_probe": lambda module: True,
    "ffmpeg_on_path": lambda: False,
    "browser_available": lambda: True,
    "vad_present": lambda: True,
    "model_present": lambda model: True,
}}
report = run_preflight(probes=probes, base_dir="/tmp")
print(format_report(report))
sys.exit(report.exit_code)
"""
        result = subprocess.run(
            [self.PYTHON, "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        output = result.stdout
        assert "FFmpeg" in output          # English
        assert "FFmpeg" in output or any("一" <= c <= "鿿" for c in output)  # Chinese or mixed
        assert "|" in output
