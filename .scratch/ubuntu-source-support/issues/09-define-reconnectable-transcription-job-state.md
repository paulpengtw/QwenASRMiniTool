# Define reconnectable transcription job state

Type: prototype
Status: resolved
Prototype asset: assets/09-job-state-prototype.html
Blocked by: 02

## Question

Which server-owned state machine and data contract should represent single-file, batch, and recording transcription jobs so every trusted browser client can recover progress, editable results, errors, and session-lifetime history—while respecting that live microphone capture ends with its capturing client and only durable files survive process restart?

## Answer

The local app session owns an ordered, session-lifetime **job registry**; browser clients only render snapshots of it. All three prototype policy recommendations were accepted.

- **State machine**: `queued → running → completed | failed | cancelled`, one job running at a time — later submissions queue regardless of which client submitted them. Recording jobs add `capturing`, bound to their capture client.
- **A batch is one job containing items**: one registry entry, one history line, one cancel; each item carries its own state and error, and a failing item never stops the remaining items.
- **Recording**: live capture ends with its capture client. If that client closes mid-recording, the job becomes `completed` with an explicit "ended early — capture client closed" note; every already-transcribed segment is retained and recoverable by any later client. A user stop completes it normally.
- **Editable results are server-owned**: segment edits apply to the registry snapshot immediately, are visible to every connected client, and survive the editing tab closing. Saving writes a durable output file and records its path on the job.
- **Errors** keep the failed state, the error message, and any partial result in the registry for the rest of the session.
- **Recovery contract**: a reconnecting client renders purely from the registry snapshot — job kind, state, progress, per-item states, result segments (with edit flags), errors, notes, and saved-file paths. Nothing renderable is tab-local.
- **Durability**: process restart wipes the registry and session history by design; only saved output files (plus durable settings and model assets per the lifecycle contract) survive.

Prototype (policies as accepted): [assets/09-job-state-prototype.html](../assets/09-job-state-prototype.html)
