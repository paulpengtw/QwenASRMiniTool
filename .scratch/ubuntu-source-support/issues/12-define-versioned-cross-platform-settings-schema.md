# Define the versioned cross-platform settings schema

Type: grilling
Status: resolved
Blocked by: 03

## Question

What versioned settings schema, platform and backend namespaces, and migration rules should preserve the meaning of existing Windows preferences while adding Ubuntu-local paths and backend-specific model choices; recover corrupt or unknown data; resolve legacy key collisions such as the incompatible `ui_scale` meanings; and remain safe across upgrade and downgrade?

## Answer

`settings.json` becomes a versioned document with `schema_version: 2`. A file with no `schema_version` is v1 and — because no Linux support has ever shipped — was authored by Windows. That premise is what makes the asymmetric design below honest rather than a workaround.

**One portable document.** Settings stay beside the checkout at `BASE_DIR/settings.json` on both platforms rather than moving to XDG on Ubuntu. A dual-boot or synced checkout therefore genuinely shares one file, which is the case ticket 03 assumed, and makes platform namespacing load-bearing rather than theoretical.

**Additive overlay.** The existing flat keys are the **Windows namespace**, keeping their current position and current meaning; nothing is migrated or deleted. Added beside them are a `shared` section, a `platforms.<os>` section (`win32`, `linux`), and a `backends.<name>` section. An older build reading a v2 file still finds every key it expects.

**Append-only meanings.** A key's meaning is immutable forever; a changed meaning requires a new key. Every build reads and writes any version best-effort, copies through keys and namespaces it does not understand untouched, and never lowers `schema_version`. Because meanings never change, an old build writing into a newer file cannot corrupt it — this rule is what makes best-effort cross-version writing safe.

**Resolution order.** `platforms.<current os>` → `shared` → legacy flat → derived default; first hit wins. Writers update the authoritative new location and mirror back into the legacy flat key when one exists.

**Flat keys are Windows-owned.** Only a Windows process mirrors into the flat block. Ubuntu writes solely to `shared` and `platforms.linux`, so a Windows path, device, or preference can never be clobbered by a Linux run. Preservation is structural, not a rule someone must remember. Ubuntu still reads flat keys (last before defaults) and still copies them through untouched.

**Paths.** A path under `BASE_DIR` is stored **relative with forward slashes** in `shared`, so an `ov_models/` download made on Windows is found by Ubuntu with no re-download and no duplicated value. A path outside the checkout is machine-bound and lives in `platforms.<os>`; when it does not resolve on the current OS, fall back to platform-local discovery without overwriting it, per ticket 03. Affected keys: `model_dir`, `gpu_model_dir`, `model_path`, `gguf_path`, `chatllm_dir`, `crispasr_dir`, `ffmpeg_path`.

**No fabricated intent.** `_seed_defaults` stops persisting a backend on first run. An absent `backend` key means *unset*, and each platform derives its own default at runtime — Windows derives CrispASR / Qwen3-1.7B-Q4 exactly as it seeds today, Ubuntu derives OpenVINO CPU with the 0.6B model per ticket 03. Nothing is written until the user actually chooses, so no machine's guess can travel to the other platform as durable intent. An explicit choice is platform-scoped: a Windows choice lands in the flat block, an Ubuntu choice in `platforms.linux`.

**`ui_scale`.** The collision is real and currently breaks Windows: `app.py:1930` reads a CustomTkinter multiplier (`1.25`) while `webview_backend.py:1126` reads a percent (`125`) from the same key in the same file. Interface scale is one user concept, so the canonical key becomes `ui_scale_percent` (int), each surface converting on the way in and out. Windows continues mirroring the legacy float `ui_scale` on every write so a downgraded build still finds what it expects. A one-time read heuristic disambiguates a legacy value: below 10 is a multiplier (×100), 10 or above is already a percent.

**Unhonourable values.** A key that parses but holds a value this build cannot honour — an unsupported `backend`, an absent `device`, an out-of-range `cpu_model_size`, a wrong-typed scale — is ignored for the current session in favour of the derived default, and the stored value is left on disk untouched so the platform or machine that can honour it still gets it. This generalises ticket 03's foreign-path rule to every key, and is surfaced through the backend capability snapshot rather than a popup. It is deliberately distinct from corruption: a Windows-authored profile opened on Ubuntu is normal, not damaged.

**Durable writes.** `_save_settings` currently truncates in place, and Ubuntu's `Ctrl+C` exit route (ticket 02) makes the corruption window easier to hit. Writes become atomic: temp file in the same directory, `fsync`, then `os.replace` — atomic on both NTFS and ext4 — with read-modify-write serialised behind the existing per-process lock. Ticket 03's backup-and-recover path remains the backstop for damage originating outside the app.

**Windows reach.** Exactly one decision here touches the Windows path: dropping `_seed_defaults` means every reader of a persisted backend, including `webview_backend.py:470`, needs a derived fallback. Windows-visible behaviour is unchanged, so the workflow-compatibility and support-evidence tickets should carry a regression check for it.

`settings-gpu.json` is ruled out of scope and keeps its current flat, unversioned form.
