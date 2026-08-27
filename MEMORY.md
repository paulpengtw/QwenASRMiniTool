# MEMORY — QwenASRMiniTool Ubuntu Source Support

Durable gotchas discovered during the 15-ticket Ubuntu source-support effort.
Update this file (commit with each new finding) so every session avoids
re-discovering the same traps.

---

## test_*.py gitignore rule (ticket 01 / 14)

`pyproject.toml` has a `[tool.pytest.ini_options] testpaths = ["tests"]`
configuration, but the repo's `.gitignore` has a `test_*.py` rule that
would exclude test files added outside the `tests/` directory.  Tests live
**only** under `tests/`; never put them at the repo root.  The CI yml uses
`git add -f` for any file that falls under an existing gitignore pattern.

When adding new test files, verify they are tracked:
```bash
git ls-files --others --exclude-standard tests/
```
If the output lists your file, use `git add -f tests/your_test.py`.

---

## requirements.txt is generated (ticket 01)

`requirements.txt` is the output of `uv export --no-hashes --no-dev` and is
checked in for the Windows PyInstaller build pipeline.  **Never hand-edit it.**
Regenerate after any change to `pyproject.toml` or `uv.lock`:
```bash
uv export --no-hashes --no-dev > requirements.txt
```
The CI gate (`uv sync --check`) enforces that the lock file is in sync.

---

## uv sync --check gate (ticket 01)

`run.sh` and the CI Ubuntu job run `uv sync --check` before starting the app.
If `uv.lock` is stale (a dependency was changed in `pyproject.toml` without
re-running `uv lock`), the gate exits non-zero.  Always commit `uv.lock`
alongside `pyproject.toml` changes.

---

## tkinter not installed in Debian 12 CI container (ticket 15)

The Debian 12 container used during development has no `python3-tk` package
available.  The `conftest.py` stubs out `tkinter`, `customtkinter`,
`pywebview`, and the `app` module so that `webview_backend` and
`webview_server` can be imported in tests without a display or GUI libraries.

Any new test that imports from the webview stack relies on `conftest.py`.
The e2e tests (`tests/test_headless_e2e.py`) use a subprocess helper
(`tests/helpers/e2e_server.py`) that installs the same stubs before importing
the server, so the subprocess itself works without tkinter.

---

## Shutdown step order: delete session BEFORE stopping server (ticket 15)

In `tests/helpers/e2e_server.py` (and any real launcher using
`ShutdownCoordinator`), the session file **must** be deleted BEFORE the server
thread is stopped.  If `_delete_session` runs after `_stop_server`:

1. `_stop_server()` → `_httpd.shutdown()` → server thread exits
2. Main thread's `srv._thread.join()` returns
3. Main thread exits → Python starts tearing down daemon threads
4. Coordinator daemon thread may be killed before `_delete_session` runs

Result: session file is not removed.  Fix: put `_delete_session` before
`_stop_server` in the steps list.

---

## _seed_defaults writes Windows-only backend on Linux (tickets 12 / 15)

`webview_backend.WebBackend._seed_defaults()` writes `backend=crispasr` as
the default when no settings exist.  On Linux, `crispasr` is
platform-unsupported, so `capabilities.build_snapshot()` derives the effective
backend as `openvino` while preserving the persisted `crispasr` preference.

**The preference must never be silently overwritten.**  `_persisted_backend()`
returns the raw stored value; `capabilities.build_snapshot()` resolves the
effective backend for the current session.  Tests for both behaviours are in
`tests/test_windows_regression_guard.py`.

---

## pgrep -f matches the test shell process itself (ticket 15)

In `test_headless_e2e.py`, `pgrep -f <marker>` may match the test runner's
own shell if the marker string appears in its environment
(`QWEN_E2E_SPAWN_MARKER=<marker>` is set in the subprocess env, which bash
shows in `/proc/<pid>/environ`, which `pgrep -f` searches).

**Always verify orphan-process death by PID (`os.kill(pid, 0)`) rather than
by `pgrep`.** Use `pgrep` only as a secondary, informational check, and expect
false positives from the test process itself.

---

## PR_SET_PDEATHSIG propagates only one level (ticket 03 / 15)

`platform_seams.spawn()` sets `PR_SET_PDEATHSIG=SIGTERM` via libc prctl in
the child's `preexec_fn`.  This means:

- When the **direct parent** dies, the child gets SIGTERM.
- A grandchild spawned by the child (e.g. `sh -c 'sleep 30 & wait'`) will NOT
  automatically receive PDEATHSIG from the grandparent's death.

For deeper process trees, `start_new_session=True` + `killpg` (via
`guard_children().terminate_all()`) is the reliable cleanup mechanism.

---

## app_webview.linux_main wires the quit endpoint (ticket 11)

`ubuntu_launcher.py` does NOT call `linux_main`.  The quit endpoint
(`POST /api/quit`) is wired by setting `srv.quit_access_key` and
`srv.shutdown_coordinator` on the server object.  If you create a new launcher
entry point, you must replicate this wiring — without it, `/api/quit` always
returns 403 ("quit endpoint not configured").

The e2e server helper (`tests/helpers/e2e_server.py`) shows the minimal
wiring needed.

---

## CHATLLM_DIR / chatllm import guards (ticket 07 / 15)

`webview_backend.py` imports `chatllm_engine` lazily (inside methods) so that
the module-level import does not fail on Linux where `chatllm` native
libraries are absent.  Do not hoist chatllm imports to the module level.

---
