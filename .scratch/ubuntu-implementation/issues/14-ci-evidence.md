# CI: per-PR ubuntu-24.04 + windows-latest, scheduled real-path job

Ticket: 14
Wave: B
Blocked by: 01, 03, 04, 06
Status: open

Decision source: 07 (read in full).

Deliverables
- .github/workflows/ci.yml: job "ubuntu" on ubuntu-24.04: apt-get install the documented prerequisites, install uv (astral-sh/setup-uv), "uv sync --extra dev", run preflight (expect exit 0: degraded is fine, fatal is not), "uv run pytest -q", "node --test tests/js/", and scripts/check-requirements-sync.sh. Absolutely no Hugging Face traffic (set HF_HUB_OFFLINE=1 and make sure no test downloads). Job "windows" on windows-latest: setup-uv, uv sync, run only the portable invariants: tests/test_settings_store.py, an import test for platform_seams (add tests/test_platform_seams_import.py if missing), and the requirements sync check.
- .github/workflows/scheduled-real-path.yml: cron weekly + workflow_dispatch on ubuntu-24.04: cache ov_models/, download the 0.6B model through the app's own downloader (python -c using downloader functions), run a headless transcription of tests/fixtures/sample.wav through app.py's OpenVINO engine and assert a result object comes back (if no suitable speech fixture can be committed, generate a 2-second 16 kHz WAV with a spoken-like tone using numpy and assert the pipeline completes with either segments or the explicit no-voice diagnostic - and say so in the workflow comments).
- tests/test_ci_workflows.py: the workflow files parse as YAML (add pyyaml to the dev extra in pyproject if needed) and contain the required jobs/steps (ubuntu-24.04, windows-latest, HF_HUB_OFFLINE, requirements sync step, node --test).
