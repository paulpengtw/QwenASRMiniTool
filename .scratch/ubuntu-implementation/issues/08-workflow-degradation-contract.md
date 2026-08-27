# Workflow compatibility contract: FFmpeg/cloudflared degradation, endpoint exposure disclosure, tunnel timeout

Ticket: 08
Wave: B
Blocked by: 02, 03, 05, 06
Status: open

Decision sources: 06 (read in full), 11 (tunnel startup 30-second hard timeout; endpoint requests connection-bound), 02 (recording capture ends with its client, segments retained).

Deliverables
- FFmpeg absent (find_executable returns None): POST /api/transcribe with a video file returns a coded refusal VIDEO_NEEDS_FFMPEG (HTTP 409 JSON {error: {code, params, remedy}}) and audio files still transcribe; the recording upload path (WebM/Opus) returns RECORDING_NEEDS_FFMPEG; the batch tab skips video items with the same coded per-item error. The UI disables the video and recording controls with the remedy from the capability snapshot (ticket 05) instead of failing later.
- cloudflared absent on Linux: toggle_tunnel returns {ok: false, error: {code: CLOUDFLARED_MISSING, ...}} with install instructions and never calls download_cloudflared; the tunnel control is disabled with the remedy. Windows keeps its download path.
- Tunnel startup: cf_tunnel.CloudflareTunnel.start gets a hard timeout (default 30 s, injectable): no URL by then -> terminate the subprocess, status failed with the captured output; cancellable during startup; start-timeout, cancel, stop, and shutdown converge on one terminate path.
- LAN endpoint: keep binding 0.0.0.0 (api_server.py:134). toggle_endpoint's response and GET /api/endpoint include lan_urls (every non-loopback IPv4 of this host + port) and exposure_notice {code: ENDPOINT_LAN_EXPOSED, params}; the UI shows the reachable URLs and states plainly, in all three languages, that other machines on the network can reach the endpoint (consent by disclosure - Ubuntu has no firewall prompt).
- Recording: if the job registry (ticket 09) is in the tree, wire the capture client's SSE disconnect / beforeunload to registry.capture_client_closed so segments are retained and the job completes with the note; otherwise leave a TODO comment naming the function.
Tests: tests/test_workflow_contract.py - transcribe a video with ffmpeg missing (monkeypatch platform_seams.find_executable) -> coded 409 and no crash; an audio path with a stub engine still succeeds; tunnel toggle on linux without cloudflared -> coded failure and download_cloudflared not called; tunnel start with a fake subprocess that never prints a URL fails within the injected timeout and terminate() is called; endpoint payload carries lan_urls and the exposure code; node --test for the pure "control state from snapshot" mapping if you add one.
