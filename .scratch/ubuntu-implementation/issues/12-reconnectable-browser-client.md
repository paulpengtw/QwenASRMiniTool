# Reconnectable browser client: canonical snapshot, SSE reconnect, Local app stopped, server-owned jobs

Ticket: 12
Wave: B
Blocked by: 05, 09, 11
Status: open

Decision sources: 02 (reconnecting clients recover the canonical model/job/result/endpoint/tunnel snapshot; disconnected state retries health checks then gives relaunch instructions; never silently enters mock mode; "Local app stopped" before intentional disconnect), 09 (clients render purely from the registry snapshot; edits server-owned; saving records the path), 10 (one client state for stop vs crash, differing only in reason).

Deliverables
- Backend: GET /api/snapshot = {status (incl. capabilities), jobs: registry.snapshot(), endpoint, tunnel}; POST /api/transcribe and the batch path create registry jobs (kinds single/batch) and run them through the single inference lane; SSE publishes "job" events from registry.subscribe; GET /api/jobs, POST /api/jobs/<id>/cancel, POST /api/jobs/<id>/segments/<idx> (edit text -> edited flag), POST /api/jobs/<id>/saved (record path). All mutating routes keep the existing access-key check.
- Frontend: webview/js/session_state.js (pure, UMD like segments.js) with a reducer: applySnapshot(state, snapshot), applyEvent(state, event, payload) covering job progress/results/edits/errors/notes/saved paths, connection states {connecting, connected, reconnecting, stopped(reason)}. app.js: on load and on every SSE (re)connect fetch /api/snapshot and render from it; SSE reconnect with backoff (1 s, 2 s, 4 s, max 10 s) plus keyed /health retries; on the "stopping" event or after retries are exhausted render a full-screen "Local app stopped / 本機應用程式已停止" state with the reason and instructions (close the tab, or relaunch from the terminal with ./run.sh); remove or hard-disable any mock/demo fallback in bridge.js so a lost server never shows fake data. Segment edits in the editor POST to the server (keep the local optimistic update); saving records the path on the job.
Tests: node --test for session_state.js (snapshot then events; stopped transitions; reconnect backoff schedule as a pure function); HTTP tests with a stub engine: submit -> job in snapshot; edit -> edited flag; cancel -> cancelled with retained segments; SSE emits job events.
