# Quit endpoint, stopping broadcast, signal handling, 10 s watchdog, cancellation ladder

Ticket: 11
Wave: B
Blocked by: 03, 09, 10
Status: open

Decision sources: 02 (exit codes: UI quit 0, Ctrl+C 130, SIGTERM 143; second Ctrl+C forces; shutdown order), 10 (stopping broadcast with reason, session file deleted on clean exit, keyed POST /api/quit), 11 (read in full: cooperative cancel events at chunk boundaries as the only in-process interruption; escalation ladder: set every cancel event -> terminate owned subprocesses -> 10-second watchdog force-exit; no thread-kill rung).

Deliverables
- shutdown.py: ShutdownCoordinator(steps injectable): begin(reason in {"user-quit","signal","replaced"}) runs, in order: broadcast SSE "stopping" {reason}; stop accepting new work (server flag -> 503 with code APP_STOPPING); set all registry cancel events (job_registry from ticket 09); terminate owned subprocesses via platform_seams.guard_children().terminate_all(); stop tunnel and LAN endpoint; flush durable writes (settings store save); close SSE subscribers; stop the listener; delete the session file (ticket 10, linux only); exit with the reason's code. A watchdog thread force-exits (os._exit) with the same code after 10 s; a second SIGINT force-exits immediately. exit_fn and clock injectable for tests.
- Wire: POST /api/quit (requires the access key; 401/403 otherwise) -> begin("user-quit") -> exit 0; SIGINT/SIGTERM handlers installed by the launcher (app_webview.py main on non-win32; do not change the Windows path) -> exit 130 / 143.
- Cancellation at chunk boundaries: app.py ASREngine.process_file (and the batch path) accept an optional cancel_event checked at each chunk boundary; when set they stop, keep the segments transcribed so far, and return them (non-destructive); webview_backend.cancel() sets the event of the running registry job. Endpoint requests (api_server.py): a socket-disconnect probe in the progress callback cancels at the next chunk boundary; during shutdown new requests are refused and in-flight ones answered with an error before the listener closes.
Tests: tests/test_shutdown.py - step order recorded by fakes; watchdog forces exit with the right code when a step hangs (injected clock); exit code per reason; second signal forces immediately; POST /api/quit over HTTP on an ephemeral port with a stub backend: an SSE client receives the stopping event and the server stops within 10 s; wrong key -> 401/403; process_file with a stub engine stops at the chunk boundary and returns the partial segments.
