"""
Server-owned session-lifetime job registry (pure module).

No server/engine imports. Thread-safe. Session-lifetime only (no persistence).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Exceptions and value objects
# ---------------------------------------------------------------------------


@dataclass
class Refusal:
    """Validator return value that causes submit() to raise SubmissionRefused."""
    code: str
    params: Dict[str, Any]
    action: Optional[str] = None


class SubmissionRefused(Exception):
    def __init__(self, refusal: Refusal) -> None:
        self.refusal = refusal
        super().__init__(f"Submission refused: {refusal.code}")


# ---------------------------------------------------------------------------
# Valid job kinds
# ---------------------------------------------------------------------------

VALID_KINDS = frozenset({"single", "batch", "recording", "download", "endpoint"})


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


class Job:
    """One unit of work tracked by the registry."""

    def __init__(
        self,
        job_id: str,
        kind: str,
        spec: Any,
        lane: str,
        client_id: Optional[str],
        clock: Callable[[], float],
    ) -> None:
        self.job_id = job_id
        self.kind = kind
        self.spec = spec
        self.lane = lane
        self.client_id = client_id
        self._clock = clock

        # State machine
        # recording starts in "capturing"; everything else starts "queued"
        self.state: str = "capturing" if kind == "recording" else "queued"
        self.cancel_event: threading.Event = threading.Event()

        # Timestamps
        self.queued_at: float = clock()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

        # Progress
        self.progress_done: Optional[int] = None
        self.progress_total: Optional[int] = None
        self.progress_message: Optional[str] = None

        # Results
        self.segments: List[Dict[str, Any]] = []
        self.result: Any = None
        self.error: Optional[str] = None
        self.notes: List[str] = []
        self.saved_paths: List[str] = []

        # Batch items — populated when kind == "batch" and spec has "items"
        self.items: List[Dict[str, Any]] = []
        if kind == "batch" and spec and isinstance(spec, dict) and "items" in spec:
            for item_spec in spec["items"]:
                self.items.append({
                    "spec": item_spec,
                    "state": "queued",
                    "error": None,
                    "result": None,
                    "segments": [],
                })

        # Endpoint metadata (preserved after disconnect)
        self.source: Optional[str] = None
        self.timing: Optional[float] = None
        self.outcome: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of this job."""
        d: Dict[str, Any] = {
            "job_id": self.job_id,
            "kind": self.kind,
            "lane": self.lane,
            "state": self.state,
            "client_id": self.client_id,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": {
                "done": self.progress_done,
                "total": self.progress_total,
                "message": self.progress_message,
            },
            "segments": [dict(s) for s in self.segments],
            "result": self.result,
            "error": self.error,
            "notes": list(self.notes),
            "saved_paths": list(self.saved_paths),
        }
        if self.kind == "batch":
            d["items"] = [
                {
                    "spec": item["spec"],
                    "state": item["state"],
                    "error": item["error"],
                    "result": item["result"],
                    "segments": [dict(s) for s in item["segments"]],
                }
                for item in self.items
            ]
        if self.kind == "endpoint":
            d["source"] = self.source
            d["timing"] = self.timing
            d["outcome"] = self.outcome
        return d


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class JobRegistry:
    """
    Session-lifetime, thread-safe job registry.

    Parameters
    ----------
    clock:
        Callable returning a monotonic float (default: time.monotonic).
    id_factory:
        Callable returning a unique string job ID (default: uuid4).
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self._clock = clock
        self._id_factory: Callable[[], str] = id_factory or (lambda: str(uuid.uuid4()))
        self._lock = threading.Lock()
        # Insertion-ordered dict (Python 3.7+) preserves session history order.
        self._jobs: Dict[str, Job] = {}
        self._subscribers: List[Callable] = []

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Register a callback fired as (event_name, payload) on every change."""
        with self._lock:
            self._subscribers.append(callback)

    def _notify(self, event_name: str, payload: Any = None) -> None:
        for cb in list(self._subscribers):
            try:
                cb(event_name, payload)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit(
        self,
        kind: str,
        spec: Any,
        lane: str = "inference",
        client_id: Optional[str] = None,
        validator: Optional[Callable[[Any], Optional[Refusal]]] = None,
    ) -> Job:
        """
        Create and enqueue a new job.

        If *validator* is provided it is called with *spec*; if it returns a
        :class:`Refusal`, :class:`SubmissionRefused` is raised and no job is
        created.

        Raises
        ------
        ValueError
            If *kind* is not one of the recognised job kinds.
        SubmissionRefused
            If the validator rejects the spec.
        """
        if kind not in VALID_KINDS:
            raise ValueError(
                f"Invalid kind {kind!r}. Must be one of {sorted(VALID_KINDS)}"
            )

        if validator is not None:
            verdict = validator(spec)
            if isinstance(verdict, Refusal):
                raise SubmissionRefused(verdict)

        with self._lock:
            job_id = self._id_factory()
            job = Job(job_id, kind, spec, lane, client_id, self._clock)
            self._jobs[job_id] = job

        self._notify("submitted", {"job_id": job_id, "kind": kind, "lane": lane})
        return job

    # ------------------------------------------------------------------
    # Scheduling helpers
    # ------------------------------------------------------------------

    def next_runnable(self, lane: str) -> Optional[Job]:
        """
        Return the first queued job in *lane* that may start now, or None.

        For lane ``"inference"`` this is blocked while any inference job is
        already running (single-runner rule).  For lane ``"download"`` (and
        any other lane) there is no such restriction.
        """
        with self._lock:
            if lane == "inference":
                for job in self._jobs.values():
                    if job.lane == "inference" and job.state == "running":
                        return None
            for job in self._jobs.values():
                if job.lane == lane and job.state == "queued":
                    return job
            return None

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def start(self, job_id: str) -> None:
        """Transition a queued (or capturing) job to running."""
        with self._lock:
            job = self._jobs[job_id]
            if job.state not in ("queued", "capturing"):
                raise RuntimeError(
                    f"start() requires state queued or capturing, got {job.state!r}"
                )
            job.state = "running"
            job.started_at = self._clock()
        self._notify("started", {"job_id": job_id})

    def finish(self, job_id: str, result: Any = None) -> None:
        """Transition a running (or capturing) job to completed."""
        with self._lock:
            job = self._jobs[job_id]
            if job.state not in ("running", "capturing"):
                raise RuntimeError(
                    f"finish() requires state running or capturing, got {job.state!r}"
                )
            job.state = "completed"
            job.result = result
            job.finished_at = self._clock()
        self._notify("finished", {"job_id": job_id})

    def fail(self, job_id: str, error: str) -> None:
        """Mark a job failed, retaining partial segments and the error message."""
        with self._lock:
            job = self._jobs[job_id]
            job.state = "failed"
            job.error = error
            job.finished_at = self._clock()
        self._notify("failed", {"job_id": job_id, "error": error})

    def cancel(self, job_id: str) -> None:
        """
        Set the cancel event.

        If the job is queued it moves immediately to cancelled.  If it is
        running, the runner must observe ``job.cancel_event`` and call
        :meth:`finish_cancelled` to complete the transition.
        """
        with self._lock:
            job = self._jobs[job_id]
            job.cancel_event.set()
            if job.state == "queued":
                job.state = "cancelled"
                job.finished_at = self._clock()
        self._notify("cancelled", {"job_id": job_id})

    def finish_cancelled(self, job_id: str) -> None:
        """
        Called by the runner after observing cancel_event.

        Already-transcribed segments are retained.  Terminal state is
        ``cancelled``.
        """
        with self._lock:
            job = self._jobs[job_id]
            if job.state != "running":
                raise RuntimeError(
                    f"finish_cancelled() requires state running, got {job.state!r}"
                )
            job.state = "cancelled"
            job.finished_at = self._clock()
        self._notify("cancelled", {"job_id": job_id})

    # ------------------------------------------------------------------
    # Progress and results
    # ------------------------------------------------------------------

    def update_progress(
        self,
        job_id: str,
        done: int,
        total: int,
        message: Optional[str] = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.progress_done = done
            job.progress_total = total
            job.progress_message = message
        self._notify(
            "progress",
            {"job_id": job_id, "done": done, "total": total, "message": message},
        )

    def append_segments(
        self,
        job_id: str,
        segments: Sequence[Dict[str, Any]],
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for seg in segments:
                job.segments.append(dict(seg))
        self._notify(
            "segments_appended",
            {"job_id": job_id, "count": len(segments)},
        )

    def edit_segment(self, job_id: str, index: int, text: str) -> None:
        """Server-owned edit: updates text and sets ``edited: True``."""
        with self._lock:
            job = self._jobs[job_id]
            job.segments[index]["text"] = text
            job.segments[index]["edited"] = True
        self._notify("segment_edited", {"job_id": job_id, "index": index, "text": text})

    def record_saved_path(self, job_id: str, path: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.saved_paths.append(path)
        self._notify("path_saved", {"job_id": job_id, "path": path})

    # ------------------------------------------------------------------
    # Batch item operations
    # ------------------------------------------------------------------

    def item_start(self, job_id: str, item_index: int) -> None:
        with self._lock:
            self._jobs[job_id].items[item_index]["state"] = "running"
        self._notify("item_started", {"job_id": job_id, "item_index": item_index})

    def item_finish(
        self,
        job_id: str,
        item_index: int,
        result: Any = None,
    ) -> None:
        with self._lock:
            item = self._jobs[job_id].items[item_index]
            item["state"] = "completed"
            item["result"] = result
        self._notify("item_finished", {"job_id": job_id, "item_index": item_index})

    def item_fail(self, job_id: str, item_index: int, error: str) -> None:
        """Fail one item; the batch continues with remaining items."""
        with self._lock:
            item = self._jobs[job_id].items[item_index]
            item["state"] = "failed"
            item["error"] = error
        self._notify(
            "item_failed",
            {"job_id": job_id, "item_index": item_index, "error": error},
        )

    def item_append_segments(
        self,
        job_id: str,
        item_index: int,
        segments: Sequence[Dict[str, Any]],
    ) -> None:
        with self._lock:
            item = self._jobs[job_id].items[item_index]
            for seg in segments:
                item["segments"].append(dict(seg))
        self._notify(
            "item_segments_appended",
            {"job_id": job_id, "item_index": item_index, "count": len(segments)},
        )

    def cancel_batch(self, job_id: str) -> None:
        """
        Cancel a batch job:
        - completed items keep their results
        - the in-flight item keeps its partial segments
        - never-started (queued) items transition to ``"unrun"``

        The batch job itself follows the same cancel semantics as a single job.
        """
        with self._lock:
            job = self._jobs[job_id]
            job.cancel_event.set()
            for item in job.items:
                if item["state"] == "queued":
                    item["state"] = "unrun"
            if job.state == "queued":
                job.state = "cancelled"
                job.finished_at = self._clock()
        self._notify("cancelled", {"job_id": job_id})

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def capture_client_closed(self, job_id: str) -> None:
        """
        The capturing browser client disconnected mid-recording.

        Transitions the job to ``completed`` with a note; already-transcribed
        segments are retained.
        """
        with self._lock:
            job = self._jobs[job_id]
            job.notes.append("ended early - capture client closed")
            job.state = "completed"
            job.finished_at = self._clock()
        self._notify(
            "finished",
            {"job_id": job_id, "note": "capture_client_closed"},
        )

    # ------------------------------------------------------------------
    # Endpoint
    # ------------------------------------------------------------------

    def disconnect(self, job_id: str) -> None:
        """
        The endpoint connection closed.

        Discards partial segments; retains metadata (source, timing, outcome).
        Marks the job cancelled.
        """
        with self._lock:
            job = self._jobs[job_id]
            job.cancel_event.set()
            job.segments = []  # discard partial segments
            job.outcome = "disconnected"
            job.state = "cancelled"
            job.finished_at = self._clock()
        self._notify("cancelled", {"job_id": job_id, "reason": "disconnect"})

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """
        Return a JSON-serialisable dict for a single job.

        Raises
        ------
        KeyError
            If *job_id* is not known.
        """
        with self._lock:
            return self._jobs[job_id].to_dict()

    def snapshot(self) -> Dict[str, Any]:
        """
        Return a JSON-serialisable dict representing the full session history.

        Jobs are listed in submission order.
        """
        with self._lock:
            return {"jobs": [job.to_dict() for job in self._jobs.values()]}
