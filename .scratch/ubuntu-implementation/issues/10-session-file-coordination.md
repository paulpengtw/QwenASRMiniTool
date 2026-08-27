# Local app session file: discovery, reuse, stale takeover (pure module)

Ticket: 10
Wave: A
Blocked by: 01
Status: open

Decision source: 10 (read in full). Windows launch path stays byte-for-byte unchanged: this module is only used on Linux by the launcher (ticket 13).

Deliverables - session_file.py (pure; injectable probes for tests):
- session_path(base_dir) -> base_dir/".session/session.json" (everything stays beside the checkout per tickets 05/12).
- write_session(base_dir, url, port, pid, access_key, started_at) atomic (temp + os.replace) with mode 0600, document {url, port, pid, identity: {start_time, exe}, access_key, started_at}. process_identity(pid) reads /proc/<pid>/stat field 22 (starttime) and /proc/<pid>/exe (fallbacks when unreadable; no psutil). read_session(base_dir) -> dict | None (invalid JSON/missing keys -> None). delete_session(base_dir).
- is_alive(pid), probe_health(url, key, timeout=1.0) -> bool (GET <url>/health with the key header the server already expects - read webview_server.py _check_host / key handling to match), terminate_and_wait(pid, deadline=10.0, sleep=time.sleep) -> bool (SIGTERM, poll, never SIGKILL).
- resolve(base_dir, probes) -> Decision where Decision.kind in {"reuse", "start_fresh", "start_fresh_after_takeover", "start_new_port_report_orphan"} with url/pid fields: missing or invalid file -> start_fresh; dead pid -> start_fresh; live + healthy -> reuse; live + unhealthy + identity matches -> SIGTERM, wait up to 10 s, then start_fresh_after_takeover; identity mismatch or the process will not die -> start_new_port_report_orphan (caller prints the orphan pid and stop instructions).
Tests (tests/test_session_file.py): file mode 0600 and atomicity; identity of the current process matches itself and mismatches a bogus start_time; dead-pid path; resolve decision table with fake probes (health, alive, identity, terminate) including the bounded wait using an injected sleep/clock; read of garbage returns None; delete is idempotent.
