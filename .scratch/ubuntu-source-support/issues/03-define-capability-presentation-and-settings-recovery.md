# Define capability presentation and settings recovery

Type: grilling
Status: resolved

## Question

How should the model and device UI represent platform capabilities on Ubuntu, choose OpenVINO CPU by default, explain unavailable Windows-only engines, and recover a shared settings file whose selected backend cannot run—without changing its meaning for Windows?

## Answer

The backend is the sole source of a canonical capability snapshot. Each backend or feature has one **capability state**—**ready**, **setup required**, **machine unavailable**, or **platform unsupported**—plus a separate operational model state such as unloaded, loading, ready, or error.

- A fresh Ubuntu profile uses OpenVINO CPU with the 0.6B model. The 1.7B model remains an explicit user choice.
- Ready choices are selectable normally. Setup-required choices are selectable with an explicit download/setup action. Machine-unavailable choices are visible but disabled with the missing prerequisite and remedy. Platform-unsupported choices do not appear in selectors.
- Windows-only integrations may appear only in a collapsed informational system-check section labelled **Not supported on Ubuntu**. They do not count toward health or errors and can never trigger Windows binary downloads on Ubuntu.
- The persisted **backend preference** is durable user intent; the **effective backend** is selected for the current local app session after capability evaluation. Ubuntu derives OpenVINO CPU without overwriting an unsupported Windows preference.
- The model page shows a stable status such as **Using OpenVINO CPU on Ubuntu · Windows preference preserved**. Recovery banners are reserved for actual events rather than repeated every launch.
- OpenVINO model size is a backend-specific preference shared wherever OpenVINO is used. Selecting 1.7B on Ubuntu does not alter the separate Windows backend preference.
- A missing or failed preferred model never causes a silent model switch. Keep the preferred model selected, explain setup or load failure, and offer an explicit switch.
- Foreign platform paths are unavailable on the current OS and fall back to platform-local discovery/defaults without overwriting their persisted values. Corrupt settings are preserved as a timestamped backup, safe defaults are used, and recovery is reported visibly.
- Main health reflects only blockers for the effective backend and core workflows; optional integrations are reported separately.
- After app readiness, navigate to model/setup for missing prerequisites, the normal workspace while loading or ready, and the model page with recovery actions after load failure.
- Every browser client renders backend-provided platform support, installation, machine availability, effective backend, persisted preference, model state, reasons, and remedies. The frontend never infers capability from labels, filenames, or its own OS checks.

The versioned settings structure, platform path namespaces, migration rules, unknown or corrupt key handling, downgrade behaviour, and the existing cross-interface `ui_scale` collision are delegated to **Define the versioned cross-platform settings schema**.
