# platform_seams.py with real Linux child cleanup

Ticket: 03
Wave: A
Blocked by: 01
Status: open

Decision sources: 05 (one module, six functions, call sites never branch on sys.platform; Linux gets start_new_session + killpg + PR_SET_PDEATHSIG; Windows-only engine files keep their CREATE_NO_WINDOW/STARTUPINFO constants untouched; os.startfile at webview_backend.py:705 becomes open_path() backed by xdg-open), 11 (subprocess terminate rung; force-exit kills the group), 01/04 (Linux never downloads Windows binaries; FFmpeg and cloudflared are discovered on PATH).

Deliverables - platform_seams.py exposing exactly these six public functions (each branches internally on sys.platform; accept an optional platform= kwarg for tests):
- app_dir() -> Path: the directory beside the checkout that holds settings/models (frozen-aware like app.py's BASE_DIR; do not move directories).
- open_path(path) -> bool: win32 os.startfile; linux xdg-open via spawn(); darwin open. Returns False (never raises) when no opener exists.
- find_executable(name, extra_dirs=()) -> Path | None: PATH first (shutil.which), then extra_dirs; on win32 also tries name + ".exe". Never downloads.
- spawn(cmd, **popen_kwargs) -> subprocess.Popen: linux/darwin: start_new_session=True and a preexec_fn that calls prctl(PR_SET_PDEATHSIG=1, SIGTERM) via ctypes (libc) and then re-checks os.getppid() to close the race where the parent already died; win32: CREATE_NO_WINDOW + STARTUPINFO hide, and registration with proc_guard's job object when present. Every spawned Popen is tracked in a module-level registry (weak list) for guard_children.
- guard_children() -> ChildGuard: win32 delegates to proc_guard.setup_kill_on_close_job(); linux installs atexit + SIGTERM/SIGINT-safe cleanup that killpg()s every tracked child's process group; ChildGuard.terminate_all(timeout=5.0): SIGTERM the groups, wait, then SIGKILL the groups. Fix proc_guard.py's false docstring claim that POSIX reaps children on parent death and make it delegate (keep its Windows behaviour byte-identical).
- open_browser(url) -> bool: webbrowser.open then xdg-open fallback on linux; returns False when nothing can open (caller prints the URL). Never invokes pywebview/Edge.
Wiring (minimal, behaviour-preserving on Windows): webview_backend.py:705 and app.py:1250 os.startfile -> open_path; ffmpeg_utils.find_ffmpeg and cf_tunnel.find_cloudflared use find_executable (PATH first; on non-win32 the download helpers download_ffmpeg / download_cloudflared raise a PlatformUnsupported error instead of fetching Windows binaries - ticket 06 owns downloader.py internals, so only touch the two helper functions' non-win32 guard here and keep the Windows path unchanged); cf_tunnel.CloudflareTunnel.start uses spawn(). Do NOT edit crisp_engine.py, chatllm_engine.py, fa_aligner.py.
Tests (tests/test_platform_seams.py, Linux, real processes, all bounded <5 s): (a) PDEATHSIG: a helper script started with subprocess spawns "sleep 30" through platform_seams.spawn and then the test SIGKILLs the helper; assert the sleep pid is gone within 2 s. (b) terminate_all kills a child and its grandchild ("sh -c 'sleep 30 & wait'"). (c) find_executable finds "sh" and returns None for a nonsense name; win32 ".exe" suffix logic via platform kwarg. (d) open_path returns False (no raise) with an empty PATH. (e) app_dir is the repo root here. (f) importing platform_seams on a simulated win32 code path does not fail (guard ctypes/libc access).
