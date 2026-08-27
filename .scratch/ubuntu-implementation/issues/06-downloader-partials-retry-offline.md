# Downloader: .part-then-rename, Range resume, transient retry, offline fast-fail, Linux trust

Ticket: 06
Wave: A
Blocked by: 01
Status: open

Decision sources: 04 (partial files stop lying; retry distinguishes transient from offline; Linux drops the CERT_NONE rung; VAD ensured for both model sizes; Linux never downloads Windows binaries), 11 (download cancel keeps the resumable partial; .tmp-staged small downloads discard on cancel), 07 (CI exercises the downloader against a local HTTP fixture server: Range resume, .part rename, truncated file).

Deliverables in downloader.py (keep public function names/signatures; add optional kwargs only):
- _download_file(url, dest, progress_cb=None, cancel_event=None): stream into dest.with_suffix(dest.suffix + ".part"); on completion os.replace into dest. Resume with a Range header from an existing .part (keep the existing behaviour if the server ignores Range: restart from zero). A file at its final name is complete by construction, so _file_is_real() no longer needs to guess about truncation beyond the existing LFS-pointer check; quick_check functions must ignore stray .part files.
- Retry policy: mid-stream failures (http.client.IncompleteRead, socket.timeout, ConnectionResetError, HTTP 5xx) retry 3 times with backoff 1 s / 2 s / 4 s (backoff injectable via a module-level _sleep for tests), resuming from the .part; connect-phase failures (URLError wrapping socket.gaierror / ConnectionRefusedError / OSError ENETUNREACH-EHOSTUNREACH) raise OfflineError immediately with no retry. Keep the existing primary-to-fallback repository switch in _download_file_with_fallback. The partial survives every failure path; cancel_event set between chunk writes stops promptly and keeps the .part (raise DownloadCancelled).
- _ssl_ctx(): on non-win32 never fall back to CERT_NONE; use certifi's bundle if importable else system trust; an SSLCertVerificationError is re-raised as a DownloadError whose message carries the CA_CERTS_MISSING remedy ("sudo apt install ca-certificates"). Windows behaviour unchanged.
- VAD is a shared prerequisite: add ensure_vad(model_dir, progress_cb=None) used by both the 0.6B and 1.7B quick_check/download paths (find where silero VAD is fetched today and reuse it) so the 1.7B-only path can no longer skip it.
- download_ffmpeg() and cf_tunnel.download_cloudflared() raise PlatformUnsupported on non-win32 (ticket 03 may have added a guard in the helper functions; if it exists keep one implementation and make both agree).
Tests (tests/test_downloader.py) using a local http.server in a thread (no external network): full download lands at the final name with no .part left; resume from an existing .part sends Range and the server serves the tail; a server that closes the connection mid-stream (truncate) triggers retry and completes with the correct bytes; connection refused on a closed port raises OfflineError in well under 1 s with zero retries; cancel_event mid-stream leaves the .part and raises DownloadCancelled; on linux _ssl_ctx().verify_mode == ssl.CERT_REQUIRED; quick_check ignores .part files; ensure_vad is invoked by the 1.7B path (monkeypatch).
