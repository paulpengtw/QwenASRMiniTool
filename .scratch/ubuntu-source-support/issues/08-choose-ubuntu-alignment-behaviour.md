# Choose Ubuntu alignment behaviour

Type: prototype
Status: resolved
Blocked by: 03

## Question

What should Ubuntu users see and receive when exact forced word alignment cannot use the current Windows-only `main.exe` runner: support proportional subtitle timing only, adopt a Linux-native aligner within this effort, or offer another clearly bounded behaviour—and how should existing alignment settings recover without changing their Windows meaning?

## Answer

Ubuntu ships **honest degraded alignment** (prototype variant B):

- Exact forced word alignment stays **platform unsupported** on Ubuntu: the Windows-only chatllm `main.exe` runner is never invoked, downloaded, or discovered on Linux. Adopting a Linux-native aligner — including a user-provided chatllm executable on `PATH` (variant C) — is out of scope for this effort.
- Word-level timing remains an Ubuntu feature whose method is proportional estimation, and the method is visible:
  - The 時間軸對齊 toggle is replaced by a read-only state chip「字級時間軸：比例估算 ⓘ」explaining that exact alignment is Windows-only.
  - Karaoke mode carries a small「≈ 估算」badge.
  - The system check lists 精確字級對齊（ForcedAligner）only inside the collapsed Windows-only group — never a health blocker, never downloadable on Ubuntu — plus a stable status line「精確字級對齊在 Ubuntu 不可用 · Windows 設定已保留」, following the capability-presentation contract.
  - The 每段最長秒數（字級對齊）setting stays visible but inert, showing its preserved value and the reason it does not apply.
- Settings recovery: `use_aligner` and chunk-length values are read but never rewritten; the effective method (proportional) is derived per session, mirroring the backend-preference / effective-backend pattern. Nothing Ubuntu-specific is persisted for alignment.

Prototype (variants A/B/C; B chosen): [assets/08-ubuntu-alignment-prototype.html](../assets/08-ubuntu-alignment-prototype.html)
