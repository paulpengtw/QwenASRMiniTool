# Terminal preflight with tiered failures and bilingual coded messages

Ticket: 02
Wave: A
Blocked by: 01
Status: open

Decision sources: 04 (tiered failure: only "cannot serve" is fatal; FFmpeg absent and no browser degrade; preflight prints English and Chinese together because no language preference is readable yet; capability reasons/remedies are a CODE plus PARAMS rendered by i18n.js), 03 (backend is the sole source of reasons/remedies).

Deliverables
- capability_codes.py: a registry CODES = {code: {"en": template, "zh": template, "severity": "fatal"|"degraded"|"info"}} using {param} placeholders, with render(code, params, lang) and as_json() (so a later ticket can serve it to the frontend). Include at least: PY_VERSION_TOO_OLD, BASE_DIR_NOT_WRITABLE, LOOPBACK_PORT_UNAVAILABLE, DEP_IMPORT_FAILED (param module), FFMPEG_MISSING (remedy: sudo apt install ffmpeg; affects video + recording), BROWSER_OPEN_FAILED (prints URL), VAD_MISSING, MODEL_MISSING (param model), CA_CERTS_MISSING, CLOUDFLARED_MISSING, ALIGN_WINDOWS_ONLY, BACKEND_PLATFORM_UNSUPPORTED (param backend), USING_OPENVINO_CPU_UBUNTU_PREF_PRESERVED, SETTINGS_RECOVERED (param backup_path), UV_ENV_OUT_OF_DATE. Unknown code renders as the code itself (never raises).
- preflight.py: run_preflight(probes=None, platform=sys.platform, base_dir=None) -> PreflightReport(items=[PreflightItem(code, severity, params)], fatal: bool, exit_code: int). Probes are injectable callables (dict) so tests never touch the real machine: python_version, base_dir_writable, loopback_port_free, import_probe(module) for openvino/onnxruntime/numpy/soundfile/librosa, ffmpeg_on_path, browser_available (xdg-open on PATH or webbrowser has a usable browser), vad_present, model_present. Fatal only: python too old, base dir not writable, loopback port unavailable, core import failure (openvino/onnxruntime/numpy). Everything else is degraded. CLI: "python preflight.py" prints one line per non-ok item as "[FATAL|DEGRADED] CODE  <en>  |  <zh>" and a final summary line, exits 2 on fatal else 0; "--json" prints the report as JSON.
- Tests (tests/test_preflight.py, tests/test_capability_codes.py): fatal vs degraded classification via injected probes; exit codes; stdout contains both the English and the Chinese rendering; unknown code safe; every CODES entry has en, zh, severity and all {params} used in en also appear in zh.
Do not wire run.sh here beyond what ticket 01 already guards; keep the module free of Tk/openvino imports at module load (probes import lazily).
