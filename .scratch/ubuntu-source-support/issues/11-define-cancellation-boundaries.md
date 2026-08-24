# Define cancellation boundaries

Type: grilling
Status: resolved
Blocked by: 09

## Question

Which operations—single transcription, batch items and queues, recording uploads, model downloads or loads, endpoint requests, and tunnel startup—are cancellable; who may cancel them; what partial result or durable output each cancellation leaves; and how does bounded shutdown escalate an operation that cannot stop cooperatively?

## Answer

Cancellation is cooperative, non-destructive, and uniform in-process; process-level terminate exists only for subprocesses and the shutdown watchdog.

- **Mechanism**: a per-operation cancel event checked at chunk boundaries (the batch tab's existing pattern, generalized) is the only in-process interruption — no mid-chunk aborts, no thread kills. Subprocesses (cloudflared; Windows-only engine helpers) stop via `terminate()`.
- **Who may cancel**: any trusted loopback client may cancel any registry job, including another client's live `capturing` job — the server marks it cancelled, broadcasts the state over SSE, and refuses further segment uploads. One trust boundary (the access key); no per-client ownership ACL. Destructive confirmations naming affected work stay as decided in the lifecycle contract.
- **Inference jobs (single, batch, recording)**: cancel retains every already-transcribed segment in the registry (terminal state `cancelled`), viewable and editable like any result; durable files come only from explicit saves. Batch cancel: completed items keep results, the in-flight item keeps its partial segments, never-started items end unrun.
- **Model downloads**: cancellable between chunk writes; the partial file is deliberately kept as resumable durable state (the existing HTTP Range resume), presented honestly as "stopped — N% kept, resume anytime". The `.tmp`-staged small downloads (cloudflared, chatllm binary) discard their temp file on cancel.
- **Model loads**: explicitly not cancellable — the load is atomic, the UI shows a busy state with no cancel affordance, and a different model choice applies after the in-flight load settles. Shutdown abandons a load harmlessly (disk assets untouched).
- **Endpoint requests**: connection-bound registry entries occupying the single inference slot, visible to browser clients. Auto-cancelled at the next chunk boundary when the caller disconnects (socket probe in the progress callback); cancellable from the UI, in which case the caller gets an error response. Partial results are discarded; session history keeps metadata only (source, timing, outcome). On shutdown, new requests are refused and in-flight ones are cancelled and answered with an error before the listener closes.
- **Tunnel startup**: a 30-second hard timeout — no URL by then means terminate the subprocess and set a failed status carrying the captured output; cancellable by any trusted client during startup. Start-timeout, cancel, stop, and shutdown all converge on the one `terminate()` path; nothing partial survives beyond session state.
- **Shutdown escalation ladder**: (1) the stopping broadcast sets every cancel event at once — jobs, queue, downloads — releasing the engine so durable writes finish; (2) owned subprocesses are terminated directly; (3) the 10-second watchdog or a second `Ctrl+C` force-exits with the contract's exit codes, abandoning anything non-cooperative. There is deliberately no thread-kill rung: durable state (settings, saved files, resumable download partials) is crash-safe by construction. On Ubuntu, subprocesses are spawned into the server's process group and force-exit kills the group, mirroring the Windows Job Object's kill-on-close guarantee.
