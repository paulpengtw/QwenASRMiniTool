# Choose the portable OS-integration boundaries

Type: grilling
Status: resolved
Blocked by: 02, 03, 04, 10, 11

## Question

Which platform-specific responsibilities must sit behind explicit seams—application directories, opening folders, executable discovery, subprocess creation and cleanup, browser launch, and shutdown—and which responsibilities should remain shared so Ubuntu support is additive and Windows behaviour stays stable?

## Answer

Platform difference is confined to one module, `platform_seams.py`, exposing six functions: `app_dir`, `open_path`, `find_executable`, `spawn`, `guard_children`, and `open_browser`. Each branches internally on `sys.platform`; call sites never branch. Scattered `if sys.platform` guards are precisely what let `proc_guard.setup_kill_on_close_job()` degrade to a silent `return None` on Linux (`proc_guard.py:43`) without anything noticing, and a per-OS package would be a lot of indirection for a surface this small.

**Child cleanup gets a real Linux implementation.** `proc_guard`'s docstring asserts that POSIX reaps children when the parent dies; it does not — orphans are reparented to init and keep running, so Ubuntu currently has no subprocess cleanup whatsoever. Children start in their own session (`start_new_session=True`) so shutdown can `killpg` the whole group, and `PR_SET_PDEATHSIG` is set in the child so the kernel signals it when its parent dies. Together these match what `KILL_ON_JOB_CLOSE` already guarantees on Windows: cleanup survives a crash or a force-kill, not merely a graceful exit. This is the Linux half of ticket 11's escalation ladder, whose subprocess-terminate rung otherwise had nothing beneath it.

**The seam covers shared paths only.** FFmpeg and cloudflared discovery, browser launch, folder opening, application directories and child cleanup route through the module. `crisp_engine`, `chatllm_engine` and `fa_aligner` keep their `CREATE_NO_WINDOW` and `STARTUPINFO` constants exactly as they are: those paths never execute on Linux, so editing them buys no Ubuntu behaviour while spending Windows regression risk. The duplicated flag constant across four files is left standing deliberately.

**Directories follow ticket 12's rule.** Everything stays beside the checkout — models in `ov_models/`, settings at `BASE_DIR/settings.json`, outputs keeping their current relative behaviour. There is no XDG split on Linux, because a dual-boot or synced checkout sharing one settings file and one model directory is the property ticket 12 was designed around, and splitting model storage by whichever OS downloaded it would defeat that.

The one behaviour genuinely fixed rather than abstracted is `os.startfile` at `webview_backend.py:705`, which is Windows-only and raises on Ubuntu today; it becomes `open_path()`, backed by `xdg-open` on Linux.
