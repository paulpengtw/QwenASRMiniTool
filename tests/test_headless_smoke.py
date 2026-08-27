"""Bounded browser-server smoke test for the Ubuntu webview contract."""
from __future__ import annotations

import io
import json
import threading
import time
import urllib.request
import wave

from shutdown import ShutdownCoordinator
from webview_server import WebViewServer


def _get_json(port: int, path: str, *, access_key: str = "") -> dict:
    headers = {"Host": f"127.0.0.1:{port}"}
    if access_key:
        headers["Authorization"] = f"Bearer {access_key}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=1.0) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def _post_json(port: int, path: str, body: dict, *, access_key: str = "") -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Content-Length": str(len(data)),
    }
    if access_key:
        headers["Authorization"] = f"Bearer {access_key}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1.0) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def _wav_16khz() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 160)
    return output.getvalue()


def _post_multipart(port: int, path: str, wav_data: bytes, *, access_key: str = "") -> dict:
    boundary = b"----qwen-contract-smoke"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="smoke.wav"\r\n'
        b"Content-Type: audio/wav\r\n\r\n"
        + wav_data
        + b"\r\n--"
        + boundary
        + b"--\r\n"
    )
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
        "Content-Length": str(len(body)),
    }
    if access_key:
        headers["Authorization"] = f"Bearer {access_key}"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1.0) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def test_headless_webview_contract_completes_within_ten_seconds():
    """Exercise the browser routes, a WAV job, polling, and keyed quit."""
    started = time.monotonic()
    server = WebViewServer(host="127.0.0.1", port=0)
    server.start()
    exit_done = threading.Event()
    access_key = "headless-smoke-key"
    exit_codes: list[int] = []

    def _exit(code: int) -> None:
        exit_codes.append(code)
        exit_done.set()

    server.quit_access_key = access_key
    server.access_key = access_key
    server.shutdown_coordinator = ShutdownCoordinator(
        steps=[server.stop],
        exit_fn=_exit,
    )

    def _stub_transcribe(opts, progress_cb=None):
        if progress_cb:
            progress_cb(100, "smoke complete")
        return {
            "segments": [{"start": 0.0, "end": 0.1, "text": "smoke"}],
            "srtPath": "smoke.srt",
        }

    server.backend.transcribe = _stub_transcribe
    try:
        port = server.port
        root_request = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"Host": f"127.0.0.1:{port}"},
        )
        with urllib.request.urlopen(root_request, timeout=1.0) as response:
            assert response.status == 200
            assert "<html" in response.read().decode("utf-8").lower()

        for path in (
            "/api/status",
            "/api/capabilities",
            "/api/snapshot",
            "/api/message-codes",
            "/api/jobs",
        ):
            assert isinstance(_get_json(port, path, access_key=access_key), dict)

        submitted = _post_multipart(
            port, "/api/transcribe", _wav_16khz(), access_key=access_key
        )
        assert submitted["ok"] is True
        job_id = submitted["job_id"]

        deadline = started + 10.0
        while time.monotonic() < deadline:
            job = _get_json(port, f"/api/jobs/{job_id}", access_key=access_key)
            if job.get("state") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("headless smoke job did not reach a terminal state")

        assert job["state"] == "completed"
        assert job["segments"][0]["text"] == "smoke"

        assert _post_json(port, "/api/quit", {}, access_key=access_key) == {"ok": True}
        assert exit_done.wait(timeout=max(0.1, deadline - time.monotonic()))
        assert exit_codes == [0]
        assert time.monotonic() - started < 10.0
    finally:
        server.stop()
