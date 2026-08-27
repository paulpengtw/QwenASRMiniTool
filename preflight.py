"""
Terminal preflight check with tiered failures and bilingual coded messages.

Usage:
    python preflight.py          # print human-readable report, exit 2 on fatal
    python preflight.py --json   # print JSON report
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Callable

from capability_codes import CODES, render


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PreflightItem:
    code: str
    severity: str       # "fatal" | "degraded" | "info"
    params: dict = field(default_factory=dict)


@dataclass
class PreflightReport:
    items: list[PreflightItem] = field(default_factory=list)
    fatal: bool = False
    exit_code: int = 0


# ---------------------------------------------------------------------------
# Default probes (touch the real machine)
# Each probe returns True on success, False (or a value) on failure.
# ---------------------------------------------------------------------------

def _default_python_version() -> tuple[int, int]:
    """Return the running Python (major, minor)."""
    return sys.version_info[:2]


def _default_base_dir_writable(base_dir: str) -> bool:
    import os
    return os.access(base_dir, os.W_OK)


def _default_loopback_port_free(port: int = 7860) -> bool:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _default_import_probe(module: str) -> bool:
    import importlib
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def _default_ffmpeg_on_path() -> bool:
    import shutil
    return shutil.which("ffmpeg") is not None


def _default_browser_available() -> bool:
    import shutil
    if shutil.which("xdg-open"):
        return True
    try:
        import webbrowser
        b = webbrowser.get()
        return b is not None
    except Exception:
        return False


def _default_vad_present() -> bool:
    """Check if the VAD model file exists in standard locations."""
    import os
    from pathlib import Path
    # Common VAD model filenames used by silero-vad
    candidates = [
        Path("silero_vad.jit"),
        Path("silero_vad.onnx"),
        Path("models") / "silero_vad.jit",
        Path("models") / "silero_vad.onnx",
    ]
    for p in candidates:
        if p.exists():
            return True
    # Also check the app's default base_dir if set
    return False


def _default_model_present(model: str) -> bool:
    """Check if an ASR model directory exists."""
    from pathlib import Path
    p = Path(model)
    return p.exists()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

_CORE_IMPORT_MODULES = ["openvino", "onnxruntime", "numpy"]
_OPTIONAL_IMPORT_MODULES = ["soundfile", "librosa"]
_MIN_PYTHON = (3, 10)
_DEFAULT_PORT = 7860


def run_preflight(
    probes: dict[str, Callable] | None = None,
    platform: str | None = None,
    base_dir: str | None = None,
) -> PreflightReport:
    """Run all preflight checks and return a PreflightReport.

    Parameters
    ----------
    probes:
        Dict of injectable callables that override the default machine-touching
        probes.  Keys: python_version, base_dir_writable, loopback_port_free,
        import_probe, ffmpeg_on_path, browser_available, vad_present,
        model_present.
    platform:
        Override sys.platform (default: sys.platform).
    base_dir:
        Directory to check for writability.  Default: current directory.
    """
    if platform is None:
        platform = sys.platform
    if base_dir is None:
        import os
        base_dir = os.getcwd()
    if probes is None:
        probes = {}

    items: list[PreflightItem] = []

    def _probe(name: str, default_fn: Callable, *args, **kwargs):
        fn = probes.get(name, default_fn)
        return fn(*args, **kwargs)

    # ------------------------------------------------------------------
    # 1. Python version  (fatal)
    # ------------------------------------------------------------------
    py_ver = _probe("python_version", _default_python_version)
    if py_ver < _MIN_PYTHON:
        items.append(PreflightItem(
            code="PY_VERSION_TOO_OLD",
            severity="fatal",
            params={
                "required": ".".join(str(x) for x in _MIN_PYTHON),
                "found": ".".join(str(x) for x in py_ver),
            },
        ))

    # ------------------------------------------------------------------
    # 2. Base directory writable  (fatal)
    # ------------------------------------------------------------------
    base_dir_ok = _probe("base_dir_writable", _default_base_dir_writable, base_dir)
    if not base_dir_ok:
        items.append(PreflightItem(
            code="BASE_DIR_NOT_WRITABLE",
            severity="fatal",
            params={"path": base_dir},
        ))

    # ------------------------------------------------------------------
    # 3. Loopback port free  (fatal)
    # ------------------------------------------------------------------
    port_ok = _probe("loopback_port_free", _default_loopback_port_free, _DEFAULT_PORT)
    if not port_ok:
        items.append(PreflightItem(
            code="LOOPBACK_PORT_UNAVAILABLE",
            severity="fatal",
            params={"port": str(_DEFAULT_PORT)},
        ))

    # ------------------------------------------------------------------
    # 4. Core imports  (fatal)
    # ------------------------------------------------------------------
    for module in _CORE_IMPORT_MODULES:
        ok = _probe("import_probe", _default_import_probe, module)
        if not ok:
            items.append(PreflightItem(
                code="DEP_IMPORT_FAILED",
                severity="fatal",
                params={"module": module},
            ))

    # ------------------------------------------------------------------
    # 5. Optional imports  (degraded)
    # ------------------------------------------------------------------
    for module in _OPTIONAL_IMPORT_MODULES:
        ok = _probe("import_probe", _default_import_probe, module)
        if not ok:
            items.append(PreflightItem(
                code="DEP_IMPORT_FAILED",
                severity="degraded",
                params={"module": module},
            ))

    # ------------------------------------------------------------------
    # 6. FFmpeg  (degraded)
    # ------------------------------------------------------------------
    ffmpeg_ok = _probe("ffmpeg_on_path", _default_ffmpeg_on_path)
    if not ffmpeg_ok:
        items.append(PreflightItem(
            code="FFMPEG_MISSING",
            severity="degraded",
            params={},
        ))

    # ------------------------------------------------------------------
    # 7. Browser  (degraded)
    # ------------------------------------------------------------------
    browser_ok = _probe("browser_available", _default_browser_available)
    if not browser_ok:
        items.append(PreflightItem(
            code="BROWSER_OPEN_FAILED",
            severity="degraded",
            params={"url": "http://127.0.0.1:7860"},
        ))

    # ------------------------------------------------------------------
    # 8. VAD model  (degraded)
    # ------------------------------------------------------------------
    vad_ok = _probe("vad_present", _default_vad_present)
    if not vad_ok:
        items.append(PreflightItem(
            code="VAD_MISSING",
            severity="degraded",
            params={},
        ))

    # ------------------------------------------------------------------
    # Derive fatal flag and exit code
    # ------------------------------------------------------------------
    has_fatal = any(it.severity == "fatal" for it in items)
    return PreflightReport(
        items=items,
        fatal=has_fatal,
        exit_code=2 if has_fatal else 0,
    )


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_line(item: PreflightItem) -> str:
    label = item.severity.upper()
    en_msg = render(item.code, item.params, lang="en")
    zh_msg = render(item.code, item.params, lang="zh")
    return f"[{label}] {item.code}  {en_msg}  |  {zh_msg}"


def format_report(report: PreflightReport) -> str:
    lines = []
    for item in report.items:
        lines.append(_format_line(item))
    if report.fatal:
        lines.append("PREFLIGHT FAILED — fatal issues found. Exiting.")
    else:
        lines.append("Preflight complete — no fatal issues.")
    return "\n".join(lines)


def format_json(report: PreflightReport) -> str:
    data = {
        "fatal": report.fatal,
        "exit_code": report.exit_code,
        "items": [
            {
                "code": it.code,
                "severity": it.severity,
                "params": it.params,
                "en": render(it.code, it.params, lang="en"),
                "zh": render(it.code, it.params, lang="zh"),
            }
            for it in report.items
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    report = run_preflight()

    if "--json" in argv:
        print(format_json(report))
    else:
        print(format_report(report))

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
