# Chart Ubuntu source support

Label: wayfinder:map

## Destination

An implementation-ready decision map for Ubuntu source support: Ubuntu 24.04 x86-64 users can run the browser UI with OpenVINO CPU and use every CPU-compatible workflow from a clean source checkout, with explicit proof that Windows behaviour and shared settings remain compatible.

## Notes

- Use `wayfinder`, `grilling`, and `domain-modeling` for every decision session; use `prototype`, `research`, or `codebase-design` when the ticket calls for it.
- Ubuntu support means a source installation, not a packaged Linux application.
- The browser UI is the official Ubuntu surface; native GTK/WebKit and CustomTkinter desktop surfaces are not part of this effort.
- OpenVINO CPU is the supported Ubuntu inference backend. Windows-only GPU choices must never lead Ubuntu users into a failing path.
- Ubuntu setup uses OS packages for system libraries and executables, a virtual environment for Python packages, and the application for models and VAD.
- FFmpeg is required for video and discovered through `PATH`; cloudflared is optional and discovered through `PATH`.
- Preserve current Windows behaviour and settings compatibility.
- Support proof includes Ubuntu 24.04 automated headless CI and a clean-VM manual workflow smoke test.

## Decisions so far

- [Establish the Ubuntu 24.04 prerequisite matrix](issues/01-establish-ubuntu-prerequisite-matrix.md): Ubuntu 24.04, Python 3.12, and OpenVINO CPU are viable with explicit OS prerequisites, corrected direct dependencies, shared VAD bootstrap, and no Windows-binary fallback on Linux.
- [Choose the Ubuntu browser lifecycle contract](issues/02-choose-browser-lifecycle-contract.md): One local process owns a reconnectable browser app session with explicit, bounded shutdown; browser tabs do not own server or non-recording job lifetime.
- [Define capability presentation and settings recovery](issues/03-define-capability-presentation-and-settings-recovery.md): Ubuntu exposes only supported choices, derives OpenVINO CPU without overwriting Windows intent, and renders backend-owned capability, setup, recovery, and health states.
- [Choose Ubuntu alignment behaviour](issues/08-choose-ubuntu-alignment-behaviour.md): Ubuntu keeps word-level timing as visibly proportional estimation — exact alignment stays Windows-only, its settings preserved but inert, and no Linux aligner is adopted.
- [Define reconnectable transcription job state](issues/09-define-reconnectable-transcription-job-state.md): A session-lifetime, server-owned job registry (queued→running→completed/failed/cancelled, one at a time) where a batch is one job with per-item states, result edits are server-owned, and recordings end with their capture client while retaining transcribed segments; only saved files survive restart.
- [Choose the local app session coordination protocol](issues/10-choose-local-app-session-coordination-protocol.md): An Ubuntu-only session file (url, pid identity, access key; deleted on clean exit) drives reuse via keyed health checks, identity-verified SIGTERM takeover of stale sessions, key-authorized quit, and an SSE stopping broadcast inside the 10-second exit deadline.
- [Define cancellation boundaries](issues/11-define-cancellation-boundaries.md) — Cooperative chunk-boundary cancellation is the only in-process interruption (non-destructive: cancelled jobs keep transcribed segments; any trusted client may cancel any job); downloads keep resumable partials, model loads are atomic, endpoint requests are connection-bound, tunnel startup is 30-second-bounded, and shutdown escalates cancel events → subprocess terminate → 10-second force-exit with no thread-kill rung.
- [Define the versioned cross-platform settings schema](issues/12-define-versioned-cross-platform-settings-schema.md) — Schema v2 keeps one portable `settings.json` beside the checkout and adds `shared`/`platforms`/`backends` namespaces beside the legacy flat keys, which stay Windows-owned and Windows-written; key meanings are append-only with unknowns preserved, in-checkout paths go relative, first-run defaults are derived rather than seeded, `ui_scale_percent` replaces the colliding `ui_scale`, writes become atomic, and unhonourable values are ignored for the session without being overwritten.
- [Define first-run ownership and recovery](issues/04-define-first-run-ownership-and-recovery.md) — Three owners (user: apt packages and uv; uv: the Python environment via `pyproject.toml`/`uv.lock` on system Python 3.12; application: models and VAD), a tiered failure surface where only "cannot serve" is fatal and FFmpeg or a missing browser merely degrade, `.part`-then-rename downloads with bounded transient retry and offline fast-fail, downloads as reconnectable registry jobs in a lane exempt from the single-runner rule with submit-time validation, Linux-only removal of the unverified-TLS rung, and bilingual terminal messages with coded capability remedies.

## Not yet specified

- The implementation sequence and code-change boundaries cannot be fixed until the platform-seam decisions are resolved.
- The exact automated test layers, fixtures, and CI jobs depend on which shared seams the platform design exposes.
- Documentation structure and troubleshooting guidance depend on the final workflow-compatibility and support-evidence contracts.

## Out of scope

- Linux packages, installers, frozen artifacts, and automatic application updates; this destination supports running from source.
- Linux CrispASR, chatllm, Vulkan, or CUDA inference backends; OpenVINO CPU is the Ubuntu backend for this effort.
- A native Ubuntu desktop window or the legacy CustomTkinter UI as the official Ubuntu experience; the browser UI is the supported surface.
- Ubuntu releases other than 24.04, architectures other than x86-64, and Linux distributions other than Ubuntu.
- Exact forced word alignment on Ubuntu, whether by a Linux-native or user-provided chatllm aligner executable; Ubuntu presents proportional timing honestly ([Choose Ubuntu alignment behaviour](issues/08-choose-ubuntu-alignment-behaviour.md)).
- The separate Windows-only `settings-gpu.json` used by `app-gpu.py`; it keeps its current flat, unversioned form and is untouched by the v2 schema ([Define the versioned cross-platform settings schema](issues/12-define-versioned-cross-platform-settings-schema.md)).
- A uv-managed Python interpreter and the Tk 9.0 validation it would require; Ubuntu uses the system Python 3.12 and Tk 8.6 that ticket 01 probed, and revisiting the interpreter waits until the transitional Tk coupling is removed ([Define first-run ownership and recovery](issues/04-define-first-run-ownership-and-recovery.md)).
