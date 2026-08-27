# Ubuntu launcher behaviour, install guide, clean-VM checklist

Ticket: 13
Wave: B
Blocked by: 01, 02, 03, 10
Status: open

Decision sources: 02 (launch waits for app readiness before opening a browser; if opening fails keep serving, print the URL and Ctrl+C instructions; startup failure opens no browser, prints an actionable error, exits non-zero), 04 (three owners; run.sh gate), 07 (the clean-VM manual scenario ending with the orphan check), 10 (reuse/takeover via the session file).

Deliverables
- ubuntu_launcher.py: launch(probes/injectables) used by app_webview.main() on non-win32 (Windows path unchanged, still pywebview/Edge): resolve the session file (ticket 10): reuse -> open the existing URL and exit 0; takeover/fresh -> start WebViewServer, wait for readiness by polling /health (bounded, injectable), write the session file, open the browser through platform_seams.open_browser; on failure keep serving and print bilingual lines with the URL and "Ctrl+C 結束 / press Ctrl+C to quit"; install the shutdown coordinator's signal handlers (ticket 11) if present; honour env QWEN_NO_BROWSER=1 (headless CI). Startup failure (port/bind/import) -> coded error to stderr, no browser, exit 2.
- run.sh (from ticket 01) already gates on uv; make sure it runs preflight then the launcher and that its refusals are bilingual.
- docs/ubuntu.md: full install guide - apt prerequisites, uv install, uv sync, ./run.sh, first launch with no models, explicit 0.6B download, FFmpeg for video/recording, optional cloudflared, endpoint exposure note, quitting, troubleshooting keyed by message code (link capability_codes). docs/ubuntu-clean-vm-checklist.md: the committed manual walk (apt + uv, uv sync, first launch no models, download 0.6B, transcribe audio, convert video, record from microphone, start endpoint and call it from a second machine, quit, then confirm no orphaned ffmpeg or cloudflared processes with pgrep) with a "re-run when the prerequisite matrix changes" note. README.md: short Ubuntu section linking both docs.
Tests: tests/test_ubuntu_launcher.py with injected probes - readiness wait bounded and returns the URL; browser-open failure keeps serving and prints the URL; reuse path opens the existing URL and does not start a server; QWEN_NO_BROWSER skips the browser; startup failure exits 2 with a coded message.
