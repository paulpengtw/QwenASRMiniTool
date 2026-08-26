# Define Ubuntu support evidence

Type: grilling
Status: resolved
Blocked by: 05, 06

## Question

Which automated tests, representative fixtures, Ubuntu 24.04 CI jobs, clean-VM manual scenarios, and Windows regression checks are necessary and sufficient to claim Ubuntu source support for the agreed workflow contract?

## Answer

Evidence comes in three layers: fast automated checks on every change, a slower automated proof of the real download-and-transcribe path, and one manual walk of the documented install.

**Per-PR CI on `ubuntu-24.04`** — minutes, with no Hugging Face traffic. It installs the documented apt prerequisites, runs `uv sync` and the preflight, then exercises the seam functions; settings v1-to-v2 migration including the `ui_scale` disambiguation heuristic; and the downloader against a local HTTP fixture server covering `Range` resume, `.part` rename, and the truncated-file case that `_file_is_real()` waves through today. It also asserts `requirements.txt` equals `uv export` output — the guard that makes ticket 04's generated-file decision safe. Third-party uptime never blocks a merge.

**Scheduled CI** — the real path, cached: download 0.6B, transcribe a committed fixture clip, assert segments came back.

**Windows regression CI on `windows-latest`** — only what runs without a GPU or models: the settings schema round trip, importing `platform_seams`, and the same `uv export` equality check. The GPU engines, CrispASR, chatllm and the frozen-EXE first run stay a manual pre-release checklist, since no hosted runner can execute them.

**Clean-VM manual scenario** — a committed checklist walked on a fresh Ubuntu 24.04 VM, working only from the documentation: apt prerequisites and uv install, `uv sync`, first launch with no models, explicit 0.6B download, transcribe audio, convert video, record from the microphone, start the endpoint and call it from a second machine, then quit and confirm no orphaned `ffmpeg` or `cloudflared` processes remain. That final step is the only check that proves ticket 05's `PR_SET_PDEATHSIG` and `killpg` cleanup actually works. Re-run it whenever the prerequisite matrix changes.

Sufficiency: this covers every workflow in ticket 06's contract at least once, both directions of the settings schema, the three download failure modes, and the two cross-platform invariants — schema meaning, and generated requirements.
