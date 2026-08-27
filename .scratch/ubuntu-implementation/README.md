# Ubuntu source support - implementation tickets

Reconstructed from the resolved decision map in ../ubuntu-source-support/map.md (the original ticket files referenced by PR #6 were never committed). Sequencing: wave A tickets are independent and run in parallel; wave B integrates them; ticket 15 is the final proof.

| # | Ticket | Wave | Blocked by | Status (merged PRs) |
|---|---|---|---|---|
| 01 | [uv packaging baseline: pyproject, lock, generated requirements, run.sh gate](issues/01-uv-packaging-baseline.md) | A | - | done — implementation [#11](https://github.com/paulpengtw/QwenASRMiniTool/pull/11) |
| 02 | [Terminal preflight with tiered failures and bilingual coded messages](issues/02-terminal-preflight-coded-messages.md) | A | 01 | done — implementation [#10](https://github.com/paulpengtw/QwenASRMiniTool/pull/10) |
| 03 | [platform_seams.py with real Linux child cleanup](issues/03-platform-seams-child-cleanup.md) | A | 01 | done — implementation [#12](https://github.com/paulpengtw/QwenASRMiniTool/pull/12) |
| 04 | [Versioned cross-platform settings store (schema v2)](issues/04-settings-schema-v2.md) | A | 01 | done — implementation [#13](https://github.com/paulpengtw/QwenASRMiniTool/pull/13), contract [#31](https://github.com/paulpengtw/QwenASRMiniTool/pull/31) |
| 06 | [Downloader: .part-then-rename, Range resume, transient retry, offline fast-fail, Linux trust](issues/06-downloader-partials-retry-offline.md) | A | 01 | done — implementation [#17](https://github.com/paulpengtw/QwenASRMiniTool/pull/17) |
| 07 | [Ubuntu alignment: platform-unsupported exact alignment, visibly proportional timing](issues/07-honest-proportional-alignment.md) | A | 01 | done — implementation [#15](https://github.com/paulpengtw/QwenASRMiniTool/pull/15), critic [#27](https://github.com/paulpengtw/QwenASRMiniTool/pull/27) |
| 09 | [Server-owned session-lifetime job registry (pure module)](issues/09-job-registry.md) | A | 01 | done — implementation [#14](https://github.com/paulpengtw/QwenASRMiniTool/pull/14), contract [#33](https://github.com/paulpengtw/QwenASRMiniTool/pull/33) |
| 10 | [Local app session file: discovery, reuse, stale takeover (pure module)](issues/10-session-file-coordination.md) | A | 01 | done — implementation [#16](https://github.com/paulpengtw/QwenASRMiniTool/pull/16) |
| 05 | [Backend capability snapshot, effective backend, coded reasons rendered by the UI](issues/05-capability-snapshot.md) | B | 02, 03, 04, 06, 07 | done — implementation [#18](https://github.com/paulpengtw/QwenASRMiniTool/pull/18), critic [#29](https://github.com/paulpengtw/QwenASRMiniTool/pull/29), contract [#33](https://github.com/paulpengtw/QwenASRMiniTool/pull/33) |
| 08 | [Workflow compatibility contract: FFmpeg/cloudflared degradation, endpoint exposure disclosure, tunnel timeout](issues/08-workflow-degradation-contract.md) | B | 02, 03, 05, 06 | done — implementation [#22](https://github.com/paulpengtw/QwenASRMiniTool/pull/22), critic [#28](https://github.com/paulpengtw/QwenASRMiniTool/pull/28), contract [#33](https://github.com/paulpengtw/QwenASRMiniTool/pull/33) |
| 11 | [Quit endpoint, stopping broadcast, signal handling, 10 s watchdog, cancellation ladder](issues/11-bounded-shutdown-cancellation.md) | B | 03, 09, 10 | done — implementation [#20](https://github.com/paulpengtw/QwenASRMiniTool/pull/20), critic [#25](https://github.com/paulpengtw/QwenASRMiniTool/pull/25), contract [#30](https://github.com/paulpengtw/QwenASRMiniTool/pull/30), [#33](https://github.com/paulpengtw/QwenASRMiniTool/pull/33) |
| 12 | [Reconnectable browser client: canonical snapshot, SSE reconnect, Local app stopped, server-owned jobs](issues/12-reconnectable-browser-client.md) | B | 05, 09, 11 | done — implementation [#19](https://github.com/paulpengtw/QwenASRMiniTool/pull/19), critic [#26](https://github.com/paulpengtw/QwenASRMiniTool/pull/26), contract [#32](https://github.com/paulpengtw/QwenASRMiniTool/pull/32), [#33](https://github.com/paulpengtw/QwenASRMiniTool/pull/33) |
| 13 | [Ubuntu launcher behaviour, install guide, clean-VM checklist](issues/13-ubuntu-launcher-docs-checklist.md) | B | 01, 02, 03, 10 | done — implementation [#21](https://github.com/paulpengtw/QwenASRMiniTool/pull/21) |
| 14 | [CI: per-PR ubuntu-24.04 + windows-latest, scheduled real-path job](issues/14-ci-evidence.md) | B | 01, 03, 04, 06 | done — implementation [#23](https://github.com/paulpengtw/QwenASRMiniTool/pull/23) |
| 15 | [Windows regression guard, headless end-to-end, orphan-process proof](issues/15-windows-regression-final-integration.md) | C | 11, 12, 13, 14 | done — implementation [#24](https://github.com/paulpengtw/QwenASRMiniTool/pull/24) |

Critical path: 01 -> 03 -> 06 -> 09 -> 10 -> 11 -> 15.

All 15 tickets complete. The Ubuntu source-support effort is finished.

Follow-up PRs are included in the status cells above. The merged PR titles
confirm the sequence: critic fixes #25–#29 covered tickets 11, 12, 07, 08,
and 05 respectively; contract fixes #30–#33 covered the endpoint, settings,
browser transcription, and cross-cutting browser/server contracts.
