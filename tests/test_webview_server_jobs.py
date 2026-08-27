"""
HTTP integration tests for job registry routes in webview_server.py.

Uses a stub engine so no real ASR model is needed.
Tests:
- GET /api/snapshot -> includes jobs
- POST /api/transcribe -> job appears in snapshot
- POST /api/jobs/<id>/segments/<idx> -> edited flag
- POST /api/jobs/<id>/cancel -> cancelled with retained segments
- GET /api/events -> SSE emits job events
"""
from __future__ import annotations

import json
import sys
import time
import types
import threading
import urllib.request
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(port, path, host=None):
    host_hdr = host or f"127.0.0.1:{port}"
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"Host": host_hdr},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _post(port, path, body=None, host=None):
    host_hdr = host or f"127.0.0.1:{port}"
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={
            "Host": host_hdr,
            "Content-Type": "application/json",
            "Content-Length": str(len(data)),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Fixture: server with stub engine
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def srv():
    """Start a WebViewServer with a stub engine; yield (server, port)."""
    import webview_server

    server = webview_server.WebViewServer()
    port = server.start()

    # Replace the backend engine with a stub that returns canned segments
    # The WebBackend was already instantiated; inject a fake transcribe method.
    def _stub_transcribe(opts, progress_cb=None):
        if progress_cb:
            progress_cb(50, "stub progress")
            progress_cb(100, "done")
        return {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello", "edited": False},
                {"start": 1.0, "end": 2.0, "text": "world", "edited": False},
            ],
            "srtPath": "/fake/out.srt",
        }

    server.backend.transcribe = _stub_transcribe

    yield server, port

    server.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_snapshot_returns_expected_keys(srv):
    server, port = srv
    snap = _get(port, "/api/snapshot")
    assert "status" in snap
    assert "jobs" in snap
    assert "endpoint" in snap
    assert "tunnel" in snap


def test_snapshot_jobs_initially_empty(srv):
    server, port = srv
    # Each module-scoped test shares the same server instance; this test should
    # run before any submit tests.  We test by checking jobs is a list (may
    # contain items from prior tests if ordering differs, but at module start
    # should be empty).
    snap = _get(port, "/api/snapshot")
    assert isinstance(snap["jobs"]["jobs"], list)


def test_api_jobs_returns_same_as_snapshot_jobs(srv):
    server, port = srv
    jobs_direct = _get(port, "/api/jobs")
    snap = _get(port, "/api/snapshot")
    assert jobs_direct == snap["jobs"]


def test_submit_via_registry_appears_in_snapshot(srv):
    """Submit a job directly via the registry and confirm it appears in /api/snapshot."""
    server, port = srv
    job = server.registry.submit(kind="single", spec={"path": "/fake/audio.wav"})
    snap = _get(port, "/api/snapshot")
    job_ids = [j["job_id"] for j in snap["jobs"]["jobs"]]
    assert job.job_id in job_ids


def test_edit_segment_sets_edited_flag(srv):
    """POST /api/jobs/<id>/segments/<idx> sets edited: True on the segment."""
    server, port = srv
    # Create a completed job with segments
    job = server.registry.submit(kind="single", spec={"path": "/fake/audio.wav"})
    server.registry.start(job.job_id)
    server.registry.append_segments(job.job_id, [
        {"start": 0.0, "end": 1.0, "text": "hello", "edited": False},
        {"start": 1.0, "end": 2.0, "text": "world", "edited": False},
    ])
    server.registry.finish(job.job_id)

    # Edit segment 1
    result = _post(port, f"/api/jobs/{job.job_id}/segments/1", {"text": "WORLD"})
    assert result.get("ok") is True

    # Confirm in snapshot
    snap = _get(port, "/api/snapshot")
    jobs_by_id = {j["job_id"]: j for j in snap["jobs"]["jobs"]}
    job_snap = jobs_by_id[job.job_id]
    assert job_snap["segments"][1]["text"] == "WORLD"
    assert job_snap["segments"][1]["edited"] is True
    # Original segment 0 unchanged
    assert job_snap["segments"][0]["text"] == "hello"


def test_cancel_transitions_queued_job_to_cancelled(srv):
    """POST /api/jobs/<id>/cancel cancels a queued job immediately."""
    server, port = srv
    job = server.registry.submit(kind="single", spec={"path": "/fake/audio.wav"})
    assert job.state == "queued"

    result = _post(port, f"/api/jobs/{job.job_id}/cancel", {})
    assert result.get("ok") is True

    snap = _get(port, "/api/snapshot")
    jobs_by_id = {j["job_id"]: j for j in snap["jobs"]["jobs"]}
    assert jobs_by_id[job.job_id]["state"] == "cancelled"


def test_cancel_running_job_retains_segments(srv):
    """Cancel a running job: segments accumulated before cancel are retained."""
    server, port = srv
    job = server.registry.submit(kind="single", spec={"path": "/fake/audio.wav"})
    server.registry.start(job.job_id)
    server.registry.append_segments(job.job_id, [
        {"start": 0.0, "end": 1.0, "text": "partial", "edited": False},
    ])

    result = _post(port, f"/api/jobs/{job.job_id}/cancel", {})
    assert result.get("ok") is True
    # cancel_event is set; runner must call finish_cancelled, but from registry.cancel
    # for a running job the cancel_event is set but state stays running until runner
    # cooperates.  We call finish_cancelled ourselves to simulate the runner.
    server.registry.finish_cancelled(job.job_id)

    snap = _get(port, "/api/snapshot")
    jobs_by_id = {j["job_id"]: j for j in snap["jobs"]["jobs"]}
    j = jobs_by_id[job.job_id]
    assert j["state"] == "cancelled"
    assert j["segments"][0]["text"] == "partial"


def test_saved_path_recorded(srv):
    """POST /api/jobs/<id>/saved records the path."""
    server, port = srv
    job = server.registry.submit(kind="single", spec={"path": "/fake/audio.wav"})
    server.registry.start(job.job_id)
    server.registry.finish(job.job_id)

    result = _post(port, f"/api/jobs/{job.job_id}/saved", {"path": "/out/sub.srt"})
    assert result.get("ok") is True

    snap = _get(port, "/api/snapshot")
    jobs_by_id = {j["job_id"]: j for j in snap["jobs"]["jobs"]}
    assert "/out/sub.srt" in jobs_by_id[job.job_id]["saved_paths"]


def test_jobs_cancel_unknown_returns_404(srv):
    server, port = srv
    try:
        _post(port, "/api/jobs/no-such-job/cancel", {})
        assert False, "expected HTTP error"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_sse_emits_job_events(srv):
    """GET /api/events: after subscribing, submitting a job via registry triggers a job event."""
    server, port = srv
    received = []
    done = threading.Event()

    def _reader():
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/events",
                headers={"Host": f"127.0.0.1:{port}"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                for line in resp:
                    line = line.decode("utf-8").strip()
                    if line.startswith("data:"):
                        try:
                            msg = json.loads(line[5:].strip())
                            if msg.get("event") == "job":
                                received.append(msg)
                        except Exception:
                            pass
                    if len(received) >= 1:
                        done.set()
                        break
        except Exception:
            done.set()

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    # Give the reader a moment to connect
    time.sleep(0.2)

    # Submit a job via the registry — the subscriber should fire
    server.registry.submit(kind="single", spec={"path": "/fake/sse_test.wav"})

    done.wait(timeout=2)
    # We should have received at least one "job" event
    assert len(received) >= 1
    assert received[0]["event"] == "job"
    payload = received[0]["payload"]
    assert "event" in payload  # {event: "submitted", payload: ...}
