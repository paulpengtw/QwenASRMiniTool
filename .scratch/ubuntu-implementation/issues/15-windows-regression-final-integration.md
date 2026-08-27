# Windows regression guard, headless end-to-end, orphan-process proof

Ticket: 15
Wave: C
Blocked by: 11, 12, 13, 14
Status: open

Decision sources: 12 (dropping _seed_defaults means every reader of a persisted backend needs a derived fallback; Windows-visible behaviour unchanged), 07 (the final orphan-process check is the only proof that PR_SET_PDEATHSIG and killpg work), 05.

Deliverables
- Audit and test every reader of the persisted backend / model choice (webview_backend, app.py, setting.py, app-gpu.py if applicable) for the derived fallback; ui_scale mirror roundtrip test for the Windows surface; tests/test_platform_seams_import.py under a simulated win32 code path.
- tests/test_headless_e2e.py (Linux): start the app via ubuntu_launcher in a subprocess with QWEN_NO_BROWSER=1, no models, an empty temp base dir; poll /health; GET /api/capabilities expects setup_required for models and a sane effective backend; GET /api/snapshot works; spawn a long-running child through the app (use an internal test-only hook or spawn one from a helper that imports platform_seams inside the app's process group); POST /api/quit with the key -> exit code 0 within 10 s, session file removed, no orphaned child (pgrep by a unique marker argument). A second test SIGKILLs the app process and asserts the child dies (PDEATHSIG).
- Update docs/ubuntu-clean-vm-checklist.md if any step changed; write .scratch/ubuntu-implementation/README.md status table marking every ticket done with its PR; add a MEMORY.md at the repo root with the durable gotchas discovered during this effort (e.g. the test_*.py gitignore rule, requirements.txt is generated, uv sync --check gate).
