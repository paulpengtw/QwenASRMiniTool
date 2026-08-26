# Choose the local app session coordination protocol

Type: grilling
Status: resolved
Blocked by: 02

## Question

What coordination protocol should launchers and browser clients use to discover and reuse one healthy local app session, replace stale ownership safely, advertise its loopback URL, authorize quit from trusted local clients, broadcast stopping, handle signals, enforce the cleanup deadline and exit statuses, and preserve existing Windows behaviour?

## Answer

Ubuntu adds a coordination protocol behind the platform seam; the Windows launch path is byte-for-byte unchanged.

- **Discovery — session file**: the app session atomically writes `session.json` (mode 0600) in the platform state directory with `{url, port, pid, process identity (start time + executable), access key, started_at}`. The server keeps its random loopback port; the file plus the printed URL advertise it. The file is deleted on clean exit, so an existing file pointing at a dead pid always means a crash.
- **Reuse**: a launcher reads the file and health-checks the URL with the key; healthy → open the browser to the existing session instead of starting a second server. Missing or invalid file → start fresh and atomically rewrite it.
- **Stale replacement**: dead pid → rewrite and start fresh. Live but unhealthy pid → verify the recorded process identity, send SIGTERM, wait up to the 10-second cleanup deadline, then start fresh; never SIGKILL automatically. On identity mismatch or a process that will not die, start on a new port, take over the file, and report the orphan pid with stop instructions.
- **Trust**: loopback binding plus the existing access key on every mutating call, the SSE channel, and `POST /api/quit`. A client holding the key (readable from the session file by the same user account) is a trusted local client; the quit confirmation naming affected work stays a client-side dialog.
- **Stopping broadcast**: quit, `Ctrl+C`, or SIGTERM immediately broadcasts an SSE `stopping` event (reason: user-quit / signal / replaced), stops accepting new work, finishes durable writes, closes SSE, stops the listener, deletes the session file, and exits 0 / 130 / 143 inside a 10-second force-exit watchdog; a second `Ctrl+C` forces immediately. Clients render **Local app stopped** on the event — or, after SSE reconnect plus keyed health retries fail, on the crash path — one client state, differing only in the shown reason.
- What "cancel in-flight work" means during shutdown is owned by **Define cancellation boundaries**; this protocol only fixes the ordering around it.
