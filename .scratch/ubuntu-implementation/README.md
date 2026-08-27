# Ubuntu source support - implementation tickets

Reconstructed from the resolved decision map in ../ubuntu-source-support/map.md (the original ticket files referenced by PR #6 were never committed). Sequencing: wave A tickets are independent and run in parallel; wave B integrates them; ticket 15 is the final proof.

| # | Ticket | Wave | Blocked by |
|---|---|---|---|
| 01 | [uv packaging baseline: pyproject, lock, generated requirements, run.sh gate](issues/01-uv-packaging-baseline.md) | A | - |
| 02 | [Terminal preflight with tiered failures and bilingual coded messages](issues/02-terminal-preflight-coded-messages.md) | A | 01 |
| 03 | [platform_seams.py with real Linux child cleanup](issues/03-platform-seams-child-cleanup.md) | A | 01 |
| 04 | [Versioned cross-platform settings store (schema v2)](issues/04-settings-schema-v2.md) | A | 01 |
| 06 | [Downloader: .part-then-rename, Range resume, transient retry, offline fast-fail, Linux trust](issues/06-downloader-partials-retry-offline.md) | A | 01 |
| 07 | [Ubuntu alignment: platform-unsupported exact alignment, visibly proportional timing](issues/07-honest-proportional-alignment.md) | A | 01 |
| 09 | [Server-owned session-lifetime job registry (pure module)](issues/09-job-registry.md) | A | 01 |
| 10 | [Local app session file: discovery, reuse, stale takeover (pure module)](issues/10-session-file-coordination.md) | A | 01 |
| 05 | [Backend capability snapshot, effective backend, coded reasons rendered by the UI](issues/05-capability-snapshot.md) | B | 02, 03, 04, 06, 07 |
| 08 | [Workflow compatibility contract: FFmpeg/cloudflared degradation, endpoint exposure disclosure, tunnel timeout](issues/08-workflow-degradation-contract.md) | B | 02, 03, 05, 06 |
| 11 | [Quit endpoint, stopping broadcast, signal handling, 10 s watchdog, cancellation ladder](issues/11-bounded-shutdown-cancellation.md) | B | 03, 09, 10 |
| 12 | [Reconnectable browser client: canonical snapshot, SSE reconnect, Local app stopped, server-owned jobs](issues/12-reconnectable-browser-client.md) | B | 05, 09, 11 |
| 13 | [Ubuntu launcher behaviour, install guide, clean-VM checklist](issues/13-ubuntu-launcher-docs-checklist.md) | B | 01, 02, 03, 10 |
| 14 | [CI: per-PR ubuntu-24.04 + windows-latest, scheduled real-path job](issues/14-ci-evidence.md) | B | 01, 03, 04, 06 |
| 15 | [Windows regression guard, headless end-to-end, orphan-process proof](issues/15-windows-regression-final-integration.md) | C | 11, 12, 13, 14 |

Critical path: 01 -> 03 -> 06 -> 09 -> 10 -> 11 -> 15.
