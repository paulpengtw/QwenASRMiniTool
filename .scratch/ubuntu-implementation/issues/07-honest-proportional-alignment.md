# Ubuntu alignment: platform-unsupported exact alignment, visibly proportional timing

Ticket: 07
Wave: A
Blocked by: 01
Status: open

Decision source: 08 (read in full) plus the capability vocabulary from 03.

Deliverables
- Backend: alignment_capability(platform=sys.platform) in a new small module alignment_policy.py returning {"method": "exact"|"proportional", "state": "ready"|"setup_required"|"platform_unsupported", "reason": {"code": "ALIGN_WINDOWS_ONLY", "params": {}}} - proportional/platform_unsupported on every non-win32 platform. On non-win32: webview_backend._ensure_fa() returns False without downloading; fa_aligner.ChatLLMAligner.load() returns False early (never looks for main.exe); downloader.download_aligner is never called from Linux code paths; app.py's ASREngine treats use_aligner as inert (effective method derived per session). use_aligner and the chunk-length setting are read but NEVER rewritten on Linux (settings roundtrip must preserve them; if ticket 04's SettingsStore exists in the tree use it, otherwise keep to the current JSON read path).
- get_status() (webview_backend) gains "alignment": alignment_capability() so clients render from the backend snapshot.
- Frontend (webview/index.html, webview/js/app.js, webview/css/app.css, webview/js/i18n.js): when status.alignment.method == "proportional" with state platform_unsupported: replace the 時間軸對齊 toggle with a read-only chip "字級時間軸：比例估算 ⓘ" whose tooltip/i18n explains exact alignment is Windows-only; karaoke view shows a small "≈ 估算" badge; the 每段最長秒數（字級對齊）setting is shown disabled with its preserved value and the reason; the system check lists 精確字級對齊（ForcedAligner）only inside a collapsed group titled "Not supported on Ubuntu / Ubuntu 不支援" that never counts as a health blocker and offers no download; a stable status line "精確字級對齊在 Ubuntu 不可用 · Windows 設定已保留". Add i18n keys for zh-TW / zh-CN / en. Windows rendering unchanged when method == "exact".
Tests: tests/test_alignment_policy.py (linux vs win32 outcomes; get_status includes the field with sys.platform monkeypatched and a stub backend; _ensure_fa on linux returns False and never calls download_aligner; use_aligner value preserved through a settings write). Keep the JS pure logic (which UI variant to render from a status object) in webview/js/alignment_view.js with a node --test test in tests/js/.
