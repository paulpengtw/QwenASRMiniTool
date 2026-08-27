# Server-owned session-lifetime job registry (pure module)

Ticket: 09
Wave: A
Blocked by: 01
Status: open

Decision sources: 09 (read in full), 11 (cooperative cancel event at chunk boundaries; non-destructive; any trusted client may cancel; batch semantics), 04 (download lane exempt from the single-runner rule; submit-time validation refuses instead of degrading silently).

Deliverables - job_registry.py (pure, thread-safe, no server/engine imports):
- JobRegistry(clock=time.monotonic, id_factory=None). submit(kind, spec, lane="inference", client_id=None, validator=None) -> Job; validator(spec) may return a Refusal(code, params, action) which makes submit raise SubmissionRefused carrying it. kind in {"single","batch","recording","download","endpoint"}.
- States: queued -> running -> completed | failed | cancelled; recording adds capturing (bound to client_id). Exactly one running job per lane "inference"; lane "download" runs independently and concurrently (exempt); later submissions queue in order regardless of submitting client. next_runnable(lane) / start(job_id) / finish(job_id, result) / fail(job_id, error) / cancel(job_id): cancel sets job.cancel_event (threading.Event) and, when the job is queued, moves it straight to cancelled; a running job stays running until the runner observes the event and calls finish_cancelled(job_id) - already-transcribed segments are retained (terminal state cancelled).
- Batch: one job whose spec lists items; per-item state/error/result via item_start/item_finish/item_fail; a failing item never stops the batch; batch cancel: completed items keep results, in-flight keeps partials, never-started items end "unrun".
- Progress and results: update_progress(job_id, done, total, message); append_segments(job_id, segments); edit_segment(job_id, index, text) marks {"edited": True} (server-owned edits); record_saved_path(job_id, path); errors keep state failed + message + partial result.
- Recording: capture_client_closed(job_id) -> completed with note "ended early - capture client closed", segments retained; user stop completes normally.
- Endpoint requests: kind "endpoint" entries are connection-bound; a disconnect() marks them cancelled and discards partial segments but keeps metadata (source, timing, outcome).
- snapshot() -> JSON-serialisable dict: ordered jobs (session history), each with kind, state, progress, per-item states, segments with edit flags, errors, notes, saved paths, timestamps; subscribe(callback) fires (event_name, payload) on every change (for the SSE bridge in a later ticket). Registry is session-lifetime only (no persistence).
Tests (tests/test_job_registry.py): every transition; single-runner queuing across clients; download lane concurrency; batch partial failure and cancel semantics; cancel retains segments; snapshot is json.dumps-able and round-trips; refusal path; capture_client_closed note; endpoint disconnect keeps metadata only; subscriber notified. No wiring into the server in this ticket.
