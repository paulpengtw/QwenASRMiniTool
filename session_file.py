"""session_file.py — Local app session file coordination (Linux/Ubuntu only).

Pure module with injectable probes for testing. Windows launch path is
byte-for-byte unchanged; this module is only used on Linux by the launcher
(ticket 13).

Session file layout (mode 0600, atomic write):
    {
        "url":         "http://127.0.0.1:<port>/",
        "port":        <int>,
        "pid":         <int>,
        "identity":    {"start_time": "<str>", "exe": "<str>"},
        "access_key":  "<str>",
        "started_at":  "<ISO8601 str>"
    }
"""
from __future__ import annotations

import json
import os
import signal
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SESSION_DIR = ".session"
_SESSION_FILE = "session.json"
_REQUIRED_KEYS = frozenset({"url", "port", "pid", "identity", "access_key", "started_at"})
_REQUIRED_IDENTITY_KEYS = frozenset({"start_time", "exe"})

# The access key header name expected by the server.
_KEY_HEADER = "X-Access-Key"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def session_path(base_dir: Path | str) -> Path:
    """Return the path to the session file (does not create it)."""
    return Path(base_dir) / _SESSION_DIR / _SESSION_FILE


# ---------------------------------------------------------------------------
# Process identity
# ---------------------------------------------------------------------------

def process_identity(pid: int) -> dict:
    """Read the process identity for *pid* from /proc.

    Returns {"start_time": "<str>", "exe": "<str>"}.
    Falls back to empty strings for both fields when /proc is unavailable or
    the PID does not exist (e.g. on Windows or for a dead PID).
    No psutil dependency.
    """
    start_time = ""
    exe = ""

    # Read starttime from /proc/<pid>/stat (field index 22, 0-based 21).
    # Field layout per proc(5): (1) pid (2) comm (3) state (4) ppid ... (22) starttime
    # The comm field may contain spaces and parentheses, so we strip it first.
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text()
        # Strip the comm field: everything between the first '(' and last ')'
        paren_end = stat_text.rfind(")")
        if paren_end != -1:
            after_comm = stat_text[paren_end + 1:].split()
            # After stripping '(comm)', fields are: state ppid pgrp session ...
            # starttime is field 22 in the original (1-indexed), which is index 20
            # after the two stripped fields (pid and comm).
            # Position in after_comm: 0=state, 1=ppid, 2=pgrp, 3=session, 4=tty_nr,
            # 5=tpgid, 6=flags, 7=minflt, 8=cminflt, 9=majflt, 10=cmajflt,
            # 11=utime, 12=stime, 13=cutime, 14=cstime, 15=priority, 16=nice,
            # 17=num_threads, 18=itrealvalue, 19=starttime
            start_time = after_comm[19]
    except (OSError, IndexError, ValueError):
        start_time = ""

    # Read exe from /proc/<pid>/exe (symlink).
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = ""

    return {"start_time": start_time, "exe": exe}


# ---------------------------------------------------------------------------
# Write / read / delete session
# ---------------------------------------------------------------------------

def write_session(
    base_dir: Path | str,
    url: str,
    port: int,
    pid: int,
    access_key: str,
    started_at: str,
) -> None:
    """Atomically write the session file with mode 0600.

    Uses a temp file + os.replace to ensure no reader sees a partial write.
    The identity is captured from the live process identified by *pid*.
    """
    base_dir = Path(base_dir)
    session_dir = base_dir / _SESSION_DIR
    session_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "url": url,
        "port": port,
        "pid": pid,
        "identity": process_identity(pid),
        "access_key": access_key,
        "started_at": started_at,
    }
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")

    # Write to a temp file in the same directory, then atomically rename.
    tmp_fd, tmp_path = _make_temp(session_dir)
    try:
        os.write(tmp_fd, payload)
        os.fchmod(tmp_fd, 0o600)
    finally:
        os.close(tmp_fd)

    os.replace(tmp_path, session_path(base_dir))


def _make_temp(directory: Path):
    """Create a temp file in *directory* and return (fd, path_str)."""
    import tempfile
    fd, path = tempfile.mkstemp(dir=str(directory), prefix=".session_tmp_")
    return fd, path


def read_session(base_dir: Path | str) -> Optional[dict]:
    """Read and validate the session file.

    Returns the parsed dict or None if the file is missing, contains invalid
    JSON, or is missing any required key.
    """
    path = session_path(Path(base_dir))
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    if not _REQUIRED_KEYS.issubset(data.keys()):
        return None

    identity = data.get("identity")
    if not isinstance(identity, dict):
        return None
    if not _REQUIRED_IDENTITY_KEYS.issubset(identity.keys()):
        return None

    return data


def delete_session(base_dir: Path | str) -> None:
    """Delete the session file, silently ignoring a missing file."""
    path = session_path(Path(base_dir))
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Process liveness
# ---------------------------------------------------------------------------

def is_alive(pid: int) -> bool:
    """Return True if *pid* is a running process, False otherwise."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it.
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------

def probe_health(url: str, key: str, timeout: float = 1.0) -> bool:
    """Return True if the session server at *url* responds healthy.

    Sends GET <url>/health with the Host header set to the server's
    host:port (required by the server's DNS-rebinding protection) and
    an X-Access-Key header for future key-gated health endpoints.

    Returns False on any error (connection refused, timeout, non-200, etc.).
    """
    # Normalise URL: strip trailing slash before appending /health
    base = url.rstrip("/")
    health_url = base + "/health"

    parsed = urlparse(health_url)
    host_header = parsed.netloc  # e.g. "127.0.0.1:8888"

    req = urllib.request.Request(
        health_url,
        headers={
            "Host": host_header,
            _KEY_HEADER: key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode("utf-8"))
            return isinstance(body, dict) and body.get("status") == "ok"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Terminate and wait
# ---------------------------------------------------------------------------

def terminate_and_wait(
    pid: int,
    deadline: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Send SIGTERM to *pid* and poll until it dies or the deadline passes.

    Returns True if the process exited within the deadline, False otherwise.
    Never sends SIGKILL.
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        # Already dead.
        return False
    except PermissionError:
        return False

    poll_interval = 0.1
    elapsed = 0.0
    while elapsed < deadline:
        if not is_alive(pid):
            return True
        sleep(poll_interval)
        elapsed += poll_interval

    return not is_alive(pid)


# ---------------------------------------------------------------------------
# Decision type
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    """Outcome of resolve()."""

    kind: str  # "reuse" | "start_fresh" | "start_fresh_after_takeover" | "start_new_port_report_orphan"
    url: str = ""
    pid: int = 0
    access_key: str = ""

    def __post_init__(self):
        valid = {"reuse", "start_fresh", "start_fresh_after_takeover",
                 "start_new_port_report_orphan"}
        if self.kind not in valid:
            raise ValueError(f"Invalid Decision.kind: {self.kind!r}")


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------

def resolve(base_dir: Path | str, probes: Any = None) -> Decision:
    """Decide what to do with an existing session file.

    *probes* is an object with optional callable attributes (all injectable
    for testing):
        .is_alive(pid) -> bool
        .probe_health(url, key, timeout) -> bool
        .process_identity(pid) -> dict
        .terminate_and_wait(pid, deadline, sleep) -> bool

    Decision table
    --------------
    - Missing or invalid session file          -> start_fresh
    - Dead pid                                 -> start_fresh
    - Live + healthy                           -> reuse
    - Live + unhealthy + identity matches
        + process dies within deadline         -> start_fresh_after_takeover
        + process won't die                    -> start_new_port_report_orphan
    - Live + unhealthy + identity mismatch     -> start_new_port_report_orphan
    """
    base_dir = Path(base_dir)

    # --- resolve probe callables (fall back to module-level defaults) ---
    _is_alive = getattr(probes, "is_alive", None) or is_alive
    _probe_health = getattr(probes, "probe_health", None) or probe_health
    _process_identity = getattr(probes, "process_identity", None) or process_identity
    _terminate_and_wait = getattr(probes, "terminate_and_wait", None) or terminate_and_wait

    # 1. Read and validate session file.
    session = read_session(base_dir)
    if session is None:
        return Decision(kind="start_fresh")

    pid = session["pid"]
    url = session["url"]
    key = session.get("access_key", "")
    stored_identity = session.get("identity", {})

    # 2. Check if process is alive.
    if not _is_alive(pid):
        return Decision(kind="start_fresh")

    # 3. Health-check the live process.
    if _probe_health(url, key):
        return Decision(kind="reuse", url=url, pid=pid, access_key=key)

    # 4. Process is alive but unhealthy. Check identity.
    live_identity = _process_identity(pid)
    identity_matches = (
        live_identity.get("start_time") == stored_identity.get("start_time")
        and live_identity.get("start_time") != ""  # empty start_time means unreadable
    )

    if not identity_matches:
        return Decision(kind="start_new_port_report_orphan", url=url, pid=pid)

    # 5. Identity matches: attempt graceful takeover.
    died = _terminate_and_wait(pid, deadline=10.0)
    if died:
        return Decision(kind="start_fresh_after_takeover")
    else:
        return Decision(kind="start_new_port_report_orphan", url=url, pid=pid)
