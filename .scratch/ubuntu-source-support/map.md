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

## Not yet specified

- The implementation sequence and code-change boundaries cannot be fixed until the settings-schema, bootstrap, reconnectable-work, cancellation, and platform-seam decisions are resolved.
- The exact automated test layers, fixtures, and CI jobs depend on which shared seams the platform design exposes.
- Documentation structure and troubleshooting guidance depend on the final prerequisite and first-run contracts.

## Out of scope

- Linux packages, installers, frozen artifacts, and automatic application updates; this destination supports running from source.
- Linux CrispASR, chatllm, Vulkan, or CUDA inference backends; OpenVINO CPU is the Ubuntu backend for this effort.
- A native Ubuntu desktop window or the legacy CustomTkinter UI as the official Ubuntu experience; the browser UI is the supported surface.
- Ubuntu releases other than 24.04, architectures other than x86-64, and Linux distributions other than Ubuntu.
- Exact forced word alignment on Ubuntu, whether by a Linux-native or user-provided chatllm aligner executable; Ubuntu presents proportional timing honestly ([Choose Ubuntu alignment behaviour](issues/08-choose-ubuntu-alignment-behaviour.md)).
