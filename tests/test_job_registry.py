"""
Tests for job_registry.py — ticket 09.

Covers every state transition, single-runner queuing, download-lane concurrency,
batch partial failure and cancel semantics, cancel retaining segments, snapshot
JSON round-trip, refusal path, capture_client_closed note, endpoint disconnect
keeps metadata, and subscriber notification.
"""
from __future__ import annotations

import json
import threading
from typing import Any, List, Tuple

import pytest

from job_registry import (
    Job,
    JobRegistry,
    Refusal,
    SubmissionRefused,
    VALID_KINDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MonoClock:
    """Deterministic fake monotonic clock."""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        return self._t

    def advance(self, delta: float = 1.0) -> None:
        self._t += delta


def _counter_id():
    """Factory that returns '1', '2', '3', … in sequence."""
    n = 0

    def _next():
        nonlocal n
        n += 1
        return str(n)

    return _next


def make_registry(**kwargs) -> JobRegistry:
    clock = kwargs.pop("clock", MonoClock())
    id_factory = kwargs.pop("id_factory", _counter_id())
    return JobRegistry(clock=clock, id_factory=id_factory, **kwargs)


# ---------------------------------------------------------------------------
# Basic submission
# ---------------------------------------------------------------------------


class TestSubmit:
    def test_submit_returns_job(self):
        reg = make_registry()
        job = reg.submit("single", spec={"file": "a.wav"})
        assert isinstance(job, Job)

    def test_submit_all_valid_kinds(self):
        reg = make_registry()
        for kind in VALID_KINDS:
            spec = {"items": ["x"]} if kind == "batch" else {}
            job = reg.submit(kind, spec=spec)
            assert job.kind == kind

    def test_submit_invalid_kind_raises(self):
        reg = make_registry()
        with pytest.raises(ValueError, match="Invalid kind"):
            reg.submit("unknown", spec={})

    def test_submit_assigns_unique_ids(self):
        reg = make_registry()
        j1 = reg.submit("single", spec={})
        j2 = reg.submit("single", spec={})
        assert j1.job_id != j2.job_id

    def test_submit_default_lane_is_inference(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        assert job.lane == "inference"

    def test_submit_custom_lane(self):
        reg = make_registry()
        job = reg.submit("download", spec={}, lane="download")
        assert job.lane == "download"

    def test_submit_stores_client_id(self):
        reg = make_registry()
        job = reg.submit("single", spec={}, client_id="client-abc")
        assert job.client_id == "client-abc"

    def test_submit_recording_starts_capturing(self):
        reg = make_registry()
        job = reg.submit("recording", spec={}, client_id="c1")
        assert job.state == "capturing"

    def test_submit_non_recording_starts_queued(self):
        reg = make_registry()
        for kind in ("single", "batch", "download", "endpoint"):
            spec = {"items": []} if kind == "batch" else {}
            job = reg.submit(kind, spec=spec)
            assert job.state == "queued", f"{kind} should start queued"


# ---------------------------------------------------------------------------
# Validator / refusal
# ---------------------------------------------------------------------------


class TestValidator:
    def test_validator_pass_creates_job(self):
        reg = make_registry()
        job = reg.submit("single", spec={"file": "ok.wav"}, validator=lambda s: None)
        assert job is not None

    def test_validator_refusal_raises_submission_refused(self):
        reg = make_registry()
        refusal = Refusal(code="MODEL_MISSING", params={"model": "diarize"}, action="download")

        def bad_validator(spec):
            return refusal

        with pytest.raises(SubmissionRefused) as exc_info:
            reg.submit("single", spec={}, validator=bad_validator)
        assert exc_info.value.refusal is refusal

    def test_validator_refusal_creates_no_job(self):
        reg = make_registry()

        def always_refuse(spec):
            return Refusal(code="ERR", params={})

        with pytest.raises(SubmissionRefused):
            reg.submit("single", spec={}, validator=always_refuse)
        assert reg.snapshot()["jobs"] == []

    def test_refusal_code_and_params_preserved(self):
        reg = make_registry()
        ref = Refusal(code="CUSTOM_CODE", params={"x": 42}, action="do_something")

        with pytest.raises(SubmissionRefused) as exc_info:
            reg.submit("single", spec={}, validator=lambda _: ref)

        assert exc_info.value.refusal.code == "CUSTOM_CODE"
        assert exc_info.value.refusal.params == {"x": 42}
        assert exc_info.value.refusal.action == "do_something"


# ---------------------------------------------------------------------------
# State machine — single job
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_queued_to_running_via_start(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        assert job.state == "running"

    def test_running_to_completed_via_finish(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.finish(job.job_id, result={"text": "hello"})
        assert job.state == "completed"
        assert job.result == {"text": "hello"}

    def test_running_to_failed_via_fail(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.fail(job.job_id, error="decode error")
        assert job.state == "failed"
        assert job.error == "decode error"

    def test_fail_retains_partial_segments(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "partial", "start": 0.0, "end": 1.0}])
        reg.fail(job.job_id, error="oops")
        assert len(job.segments) == 1

    def test_queued_cancel_moves_to_cancelled_immediately(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.cancel(job.job_id)
        assert job.state == "cancelled"

    def test_queued_cancel_sets_event(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.cancel(job.job_id)
        assert job.cancel_event.is_set()

    def test_running_cancel_sets_event_but_stays_running(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.cancel(job.job_id)
        assert job.cancel_event.is_set()
        assert job.state == "running"

    def test_finish_cancelled_from_running_sets_cancelled(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.cancel(job.job_id)
        reg.append_segments(job.job_id, [{"text": "seg1", "start": 0.0, "end": 1.0}])
        reg.finish_cancelled(job.job_id)
        assert job.state == "cancelled"

    def test_cancel_retains_segments(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "kept", "start": 0.0, "end": 1.0}])
        reg.cancel(job.job_id)
        reg.finish_cancelled(job.job_id)
        assert len(job.segments) == 1
        assert job.segments[0]["text"] == "kept"

    def test_finish_cancelled_requires_running(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.cancel(job.job_id)  # queued → cancelled
        with pytest.raises(RuntimeError):
            reg.finish_cancelled(job.job_id)

    def test_timestamps_set_correctly(self):
        clock = MonoClock()
        reg = make_registry(clock=clock)
        job = reg.submit("single", spec={})
        assert job.queued_at == 0.0
        clock.advance(1.0)
        reg.start(job.job_id)
        assert job.started_at == 1.0
        clock.advance(2.0)
        reg.finish(job.job_id)
        assert job.finished_at == 3.0


# ---------------------------------------------------------------------------
# Single-runner rule (inference lane)
# ---------------------------------------------------------------------------


class TestSingleRunner:
    def test_next_runnable_returns_first_queued(self):
        reg = make_registry()
        j1 = reg.submit("single", spec={})
        reg.submit("single", spec={})
        assert reg.next_runnable("inference") is j1

    def test_next_runnable_blocked_while_running(self):
        reg = make_registry()
        j1 = reg.submit("single", spec={})
        reg.submit("single", spec={})
        reg.start(j1.job_id)
        assert reg.next_runnable("inference") is None

    def test_next_runnable_after_finish_returns_second(self):
        reg = make_registry()
        j1 = reg.submit("single", spec={})
        j2 = reg.submit("single", spec={})
        reg.start(j1.job_id)
        reg.finish(j1.job_id)
        assert reg.next_runnable("inference") is j2

    def test_queue_order_preserved_across_clients(self):
        reg = make_registry()
        j1 = reg.submit("single", spec={}, client_id="alice")
        j2 = reg.submit("single", spec={}, client_id="bob")
        j3 = reg.submit("single", spec={}, client_id="alice")
        reg.start(j1.job_id)
        reg.finish(j1.job_id)
        assert reg.next_runnable("inference") is j2
        reg.start(j2.job_id)
        reg.finish(j2.job_id)
        assert reg.next_runnable("inference") is j3

    def test_cancelled_queued_job_not_returned_as_runnable(self):
        reg = make_registry()
        j1 = reg.submit("single", spec={})
        reg.cancel(j1.job_id)
        assert reg.next_runnable("inference") is None


# ---------------------------------------------------------------------------
# Download lane — concurrency
# ---------------------------------------------------------------------------


class TestDownloadLane:
    def test_download_lane_not_blocked_by_inference_running(self):
        reg = make_registry()
        inf_job = reg.submit("single", spec={}, lane="inference")
        dl_job = reg.submit("download", spec={}, lane="download")
        reg.start(inf_job.job_id)
        runnable = reg.next_runnable("download")
        assert runnable is dl_job

    def test_multiple_downloads_can_run_concurrently(self):
        reg = make_registry()
        d1 = reg.submit("download", spec={}, lane="download")
        d2 = reg.submit("download", spec={}, lane="download")
        reg.start(d1.job_id)
        # second download still appears as runnable
        runnable = reg.next_runnable("download")
        assert runnable is d2

    def test_download_does_not_block_inference(self):
        reg = make_registry()
        dl = reg.submit("download", spec={}, lane="download")
        inf = reg.submit("single", spec={}, lane="inference")
        reg.start(dl.job_id)
        assert reg.next_runnable("inference") is inf


# ---------------------------------------------------------------------------
# Progress and results
# ---------------------------------------------------------------------------


class TestProgressAndResults:
    def test_update_progress_stores_values(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.update_progress(job.job_id, done=3, total=10, message="working…")
        assert job.progress_done == 3
        assert job.progress_total == 10
        assert job.progress_message == "working…"

    def test_append_segments_accumulates(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "hello", "start": 0.0, "end": 1.0}])
        reg.append_segments(job.job_id, [{"text": "world", "start": 1.0, "end": 2.0}])
        assert len(job.segments) == 2

    def test_edit_segment_updates_text_and_marks_edited(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "original", "start": 0.0, "end": 1.0}])
        reg.edit_segment(job.job_id, 0, "corrected")
        assert job.segments[0]["text"] == "corrected"
        assert job.segments[0]["edited"] is True

    def test_record_saved_path(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.record_saved_path(job.job_id, "/home/user/output.srt")
        assert "/home/user/output.srt" in job.saved_paths


# ---------------------------------------------------------------------------
# Batch jobs
# ---------------------------------------------------------------------------


class TestBatchJobs:
    def _make_batch(self):
        reg = make_registry()
        spec = {"items": ["file_a.wav", "file_b.wav", "file_c.wav"]}
        job = reg.submit("batch", spec=spec)
        return reg, job

    def test_batch_items_created(self):
        _reg, job = self._make_batch()
        assert len(job.items) == 3

    def test_batch_items_start_queued(self):
        _reg, job = self._make_batch()
        for item in job.items:
            assert item["state"] == "queued"

    def test_item_start_running(self):
        reg, job = self._make_batch()
        reg.start(job.job_id)
        reg.item_start(job.job_id, 0)
        assert job.items[0]["state"] == "running"

    def test_item_finish_completed(self):
        reg, job = self._make_batch()
        reg.start(job.job_id)
        reg.item_start(job.job_id, 0)
        reg.item_finish(job.job_id, 0, result={"text": "done"})
        assert job.items[0]["state"] == "completed"
        assert job.items[0]["result"] == {"text": "done"}

    def test_item_fail_does_not_stop_batch(self):
        reg, job = self._make_batch()
        reg.start(job.job_id)
        reg.item_start(job.job_id, 0)
        reg.item_fail(job.job_id, 0, error="decode error")
        assert job.items[0]["state"] == "failed"
        # remaining items still queued
        assert job.items[1]["state"] == "queued"
        assert job.items[2]["state"] == "queued"
        # batch job itself still running
        assert job.state == "running"

    def test_batch_partial_failure_and_finish(self):
        reg, job = self._make_batch()
        reg.start(job.job_id)
        reg.item_start(job.job_id, 0)
        reg.item_finish(job.job_id, 0, result="ok")
        reg.item_start(job.job_id, 1)
        reg.item_fail(job.job_id, 1, error="bad file")
        reg.item_start(job.job_id, 2)
        reg.item_finish(job.job_id, 2, result="ok")
        reg.finish(job.job_id)
        assert job.state == "completed"
        assert job.items[0]["state"] == "completed"
        assert job.items[1]["state"] == "failed"
        assert job.items[2]["state"] == "completed"

    def test_batch_cancel_from_queued(self):
        reg, job = self._make_batch()
        reg.cancel_batch(job.job_id)
        assert job.state == "cancelled"
        for item in job.items:
            assert item["state"] == "unrun"

    def test_batch_cancel_running_item_keeps_partials(self):
        reg, job = self._make_batch()
        reg.start(job.job_id)
        # item 0 completed
        reg.item_start(job.job_id, 0)
        reg.item_append_segments(job.job_id, 0, [{"text": "seg0", "start": 0.0, "end": 1.0}])
        reg.item_finish(job.job_id, 0, result="r0")
        # item 1 in flight with partial
        reg.item_start(job.job_id, 1)
        reg.item_append_segments(job.job_id, 1, [{"text": "partial", "start": 1.0, "end": 2.0}])
        # item 2 never started (queued)
        reg.cancel_batch(job.job_id)
        # completed item keeps result
        assert job.items[0]["state"] == "completed"
        assert job.items[0]["result"] == "r0"
        # in-flight item keeps partial segment
        assert job.items[1]["state"] == "running"
        assert len(job.items[1]["segments"]) == 1
        # never-started item → unrun
        assert job.items[2]["state"] == "unrun"

    def test_batch_cancel_event_set(self):
        reg, job = self._make_batch()
        reg.cancel_batch(job.job_id)
        assert job.cancel_event.is_set()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


class TestRecording:
    def test_capture_client_closed_completes_with_note(self):
        reg = make_registry()
        job = reg.submit("recording", spec={}, client_id="c1")
        assert job.state == "capturing"
        reg.capture_client_closed(job.job_id)
        assert job.state == "completed"
        assert "ended early - capture client closed" in job.notes

    def test_capture_client_closed_retains_segments(self):
        reg = make_registry()
        job = reg.submit("recording", spec={}, client_id="c1")
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "live", "start": 0.0, "end": 1.0}])
        reg.capture_client_closed(job.job_id)
        assert len(job.segments) == 1
        assert job.segments[0]["text"] == "live"

    def test_user_stop_completes_normally(self):
        reg = make_registry()
        job = reg.submit("recording", spec={}, client_id="c1")
        reg.start(job.job_id)
        reg.finish(job.job_id, result={"segments": []})
        assert job.state == "completed"
        assert "ended early - capture client closed" not in job.notes

    def test_recording_capturing_state_appears_in_snapshot(self):
        reg = make_registry()
        job = reg.submit("recording", spec={}, client_id="c1")
        snap = reg.snapshot()
        states = [j["state"] for j in snap["jobs"]]
        assert "capturing" in states


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class TestEndpoint:
    def test_disconnect_marks_cancelled(self):
        reg = make_registry()
        job = reg.submit("endpoint", spec={"source": "api"}, lane="inference", client_id="x")
        job.source = "api"
        job.timing = 1.5
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "partial", "start": 0.0, "end": 0.5}])
        reg.disconnect(job.job_id)
        assert job.state == "cancelled"

    def test_disconnect_discards_partial_segments(self):
        reg = make_registry()
        job = reg.submit("endpoint", spec={}, lane="inference")
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "partial", "start": 0.0, "end": 0.5}])
        reg.disconnect(job.job_id)
        assert job.segments == []

    def test_disconnect_keeps_metadata(self):
        reg = make_registry()
        job = reg.submit("endpoint", spec={}, lane="inference", client_id="ep1")
        job.source = "loopback"
        job.timing = 2.3
        reg.start(job.job_id)
        reg.disconnect(job.job_id)
        # metadata preserved
        assert job.source == "loopback"
        assert job.timing == 2.3
        # outcome set
        assert job.outcome == "disconnected"

    def test_disconnect_sets_cancel_event(self):
        reg = make_registry()
        job = reg.submit("endpoint", spec={}, lane="inference")
        reg.start(job.job_id)
        reg.disconnect(job.job_id)
        assert job.cancel_event.is_set()

    def test_endpoint_metadata_in_snapshot(self):
        reg = make_registry()
        job = reg.submit("endpoint", spec={}, lane="inference", client_id="ep1")
        job.source = "loopback"
        job.timing = 1.0
        reg.start(job.job_id)
        reg.disconnect(job.job_id)
        snap = reg.snapshot()
        ep = snap["jobs"][0]
        assert "source" in ep
        assert "timing" in ep
        assert "outcome" in ep
        assert ep["outcome"] == "disconnected"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_is_json_serialisable(self):
        reg = make_registry()
        job = reg.submit("single", spec={"file": "a.wav"})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "hello", "start": 0.0, "end": 1.0}])
        reg.finish(job.job_id, result="done")
        snap = reg.snapshot()
        serialised = json.dumps(snap)
        assert isinstance(serialised, str)

    def test_snapshot_round_trips(self):
        reg = make_registry()
        job = reg.submit("single", spec={"file": "a.wav"})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "hi", "start": 0.0, "end": 0.5}])
        reg.edit_segment(job.job_id, 0, "Hi")
        reg.finish(job.job_id)
        snap = reg.snapshot()
        restored = json.loads(json.dumps(snap))
        assert restored["jobs"][0]["state"] == "completed"
        assert restored["jobs"][0]["segments"][0]["edited"] is True

    def test_snapshot_preserves_insertion_order(self):
        reg = make_registry()
        ids = []
        for i in range(3):
            job = reg.submit("single", spec={"n": i})
            ids.append(job.job_id)
        snap = reg.snapshot()
        snap_ids = [j["job_id"] for j in snap["jobs"]]
        assert snap_ids == ids

    def test_snapshot_includes_all_required_fields(self):
        reg = make_registry()
        job = reg.submit("single", spec={})
        snap = reg.snapshot()
        entry = snap["jobs"][0]
        required = {
            "job_id", "kind", "state", "progress",
            "segments", "error", "notes", "saved_paths", "timestamps"
        }
        # Check the fields that must be present (timestamps via queued_at etc.)
        assert "job_id" in entry
        assert "kind" in entry
        assert "state" in entry
        assert "progress" in entry
        assert "segments" in entry
        assert "error" in entry
        assert "notes" in entry
        assert "saved_paths" in entry
        assert "queued_at" in entry

    def test_snapshot_batch_includes_items(self):
        reg = make_registry()
        spec = {"items": ["a.wav", "b.wav"]}
        job = reg.submit("batch", spec=spec)
        snap = reg.snapshot()
        entry = snap["jobs"][0]
        assert "items" in entry
        assert len(entry["items"]) == 2

    def test_snapshot_endpoint_includes_metadata(self):
        reg = make_registry()
        job = reg.submit("endpoint", spec={}, lane="inference")
        snap = reg.snapshot()
        entry = snap["jobs"][0]
        assert "source" in entry
        assert "timing" in entry
        assert "outcome" in entry


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------


class TestSubscribers:
    def test_subscriber_notified_on_submit(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        reg.submit("single", spec={})
        assert any(e[0] == "submitted" for e in events)

    def test_subscriber_notified_on_start(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        assert any(e[0] == "started" for e in events)

    def test_subscriber_notified_on_finish(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.finish(job.job_id)
        assert any(e[0] == "finished" for e in events)

    def test_subscriber_notified_when_capture_client_closes_with_note(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("recording", spec={}, client_id="c1")

        reg.capture_client_closed(job.job_id)

        assert ("note_added", {
            "job_id": job.job_id,
            "note": "ended early - capture client closed",
        }) in events

    def test_subscriber_notified_on_cancel(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("single", spec={})
        reg.cancel(job.job_id)
        assert any(e[0] == "cancelled" for e in events)

    def test_subscriber_notified_on_fail(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.fail(job.job_id, error="err")
        assert any(e[0] == "failed" for e in events)

    def test_subscriber_notified_on_progress(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.update_progress(job.job_id, done=5, total=10)
        assert any(e[0] == "progress" for e in events)

    def test_batch_item_finished_event_includes_result(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("batch", spec={"items": ["a.wav"]})

        reg.item_start(job.job_id, 0)
        reg.item_finish(job.job_id, 0, result={"text": "done"})

        assert ("item_finished", {
            "job_id": job.job_id,
            "item_index": 0,
            "result": {"text": "done"},
        }) in events

    def test_subscriber_notified_on_segments(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "x", "start": 0.0, "end": 1.0}])
        assert any(e[0] == "segments_appended" for e in events)

    def test_subscriber_notified_on_edit_segment(self):
        reg = make_registry()
        events: List[Tuple[str, Any]] = []
        reg.subscribe(lambda name, payload: events.append((name, payload)))
        job = reg.submit("single", spec={})
        reg.start(job.job_id)
        reg.append_segments(job.job_id, [{"text": "x", "start": 0.0, "end": 1.0}])
        reg.edit_segment(job.job_id, 0, "y")
        assert any(e[0] == "segment_edited" for e in events)

    def test_subscriber_exception_does_not_propagate(self):
        reg = make_registry()

        def bad_cb(name, payload):
            raise RuntimeError("boom")

        reg.subscribe(bad_cb)
        # Should not raise
        reg.submit("single", spec={})

    def test_multiple_subscribers_all_notified(self):
        reg = make_registry()
        seen_a: List[str] = []
        seen_b: List[str] = []
        reg.subscribe(lambda name, _: seen_a.append(name))
        reg.subscribe(lambda name, _: seen_b.append(name))
        reg.submit("single", spec={})
        assert "submitted" in seen_a
        assert "submitted" in seen_b


# ---------------------------------------------------------------------------
# Thread safety (smoke test)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_submits(self):
        _counter = 0
        _counter_lock = threading.Lock()

        def unique_id():
            nonlocal _counter
            with _counter_lock:
                _counter += 1
                return str(_counter)

        reg = make_registry(id_factory=unique_id)
        errors: List[Exception] = []

        def submit_many():
            try:
                for _ in range(20):
                    reg.submit("single", spec={})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=submit_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(reg.snapshot()["jobs"]) == 100
