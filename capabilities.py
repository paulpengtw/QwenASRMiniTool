"""capabilities.py — Backend capability snapshot.

build_snapshot(platform, settings_store, probes) -> dict

Snapshot structure
------------------
{
  "backend_preference": str,           # persisted intent (never overwritten)
  "effective_backend": str,            # backend in use this session
  "effective_model": str,              # model in use this session
  "status_line": {"code": str, "params": dict} | null,
  "model_state": {"state": str, "message": str | null},
  "backends": {
    "openvino_cpu":    capability_entry,
    "crispasr":        capability_entry,
    "chatllm_vulkan":  capability_entry,
    "cuda_pytorch":    capability_entry,
  },
  "features": {
    "ffmpeg":           capability_entry,
    "cloudflared":      capability_entry,
    "forced_alignment": capability_entry,
    "diarization":      capability_entry,
    "endpoint":         capability_entry,
  },
  "health": {"blockers": [...], "optional": [...]},
  "recovery_events": [...],
  "navigation_hint": {"target": "model" | "workspace"},
}

capability_entry: {
  "state":  "ready" | "setup_required" | "machine_unavailable" | "platform_unsupported",
  "reason": {"code": str, "params": dict} | null,
  "remedy": {"code": str, "params": dict} | null,
  "action": "download" | "install" | null,
}

Probes dict (passed in by the caller; no network/disk IO here)
--------------------------------------------------------------
{
  "ffmpeg":            bool,           # ffmpeg found on PATH/extra_dirs
  "cloudflared":       bool,           # cloudflared found
  "model_present":     bool,           # effective model files on disk
  "model_state":       str,            # "unloaded"|"loading"|"ready"|"error"
  "model_error":       str | None,     # error message when model_state=="error"
  "diarization":       bool,           # diarization model files present
}
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from settings_store import SettingsStore

# ---------------------------------------------------------------------------
# Platform → supported backends
# ---------------------------------------------------------------------------

_LINUX_BACKENDS: frozenset[str] = frozenset({"openvino"})
_WIN32_BACKENDS: frozenset[str] = frozenset({"openvino", "crispasr", "chatllm"})

# Internal backend key → snapshot key
_BACKEND_KEYS: dict[str, str] = {
    "openvino":   "openvino_cpu",
    "crispasr":   "crispasr",
    "chatllm":    "chatllm_vulkan",
    "cuda":       "cuda_pytorch",
}
_SNAPSHOT_TO_INTERNAL: dict[str, str] = {v: k for k, v in _BACKEND_KEYS.items()}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(state: str, reason=None, remedy=None, action=None) -> dict:
    return {"state": state, "reason": reason, "remedy": remedy, "action": action}


def _code(code: str, params: dict | None = None) -> dict:
    return {"code": code, "params": params or {}}


# ---------------------------------------------------------------------------
# Platform-supported backend set
# ---------------------------------------------------------------------------

def _supported_backends(platform: str) -> frozenset[str]:
    if platform == "win32":
        return _WIN32_BACKENDS
    return _LINUX_BACKENDS  # linux and everything else: OpenVINO CPU only


# ---------------------------------------------------------------------------
# Effective backend resolution
# ---------------------------------------------------------------------------

def _resolve_effective_backend(platform: str, pref_internal: str) -> str:
    """Return the internal backend key to use this session (never persisted)."""
    supported = _supported_backends(platform)
    if pref_internal in supported:
        return pref_internal
    # Fall back to openvino on Linux when preference is a Windows-only backend.
    return "openvino"


def _resolve_effective_model(platform: str, settings_store: "SettingsStore",
                              effective_internal: str) -> str:
    """Return the effective model label for the session."""
    if effective_internal == "openvino":
        size = settings_store.get("cpu_model_size") or "0.6B"
        return size
    if effective_internal == "crispasr":
        return settings_store.get("crisp_model") or "breeze"
    if effective_internal == "chatllm":
        return "qwen3-asr-1.7b"
    return "default"


# ---------------------------------------------------------------------------
# Backend capability entries
# ---------------------------------------------------------------------------

def _backend_entries(platform: str) -> dict[str, dict]:
    """Build capability entries for every known backend."""
    supported = _supported_backends(platform)
    entries: dict[str, dict] = {}

    # openvino_cpu — always available on linux (and win32)
    if "openvino" in supported:
        entries["openvino_cpu"] = _entry("ready")
    else:
        entries["openvino_cpu"] = _entry(
            "platform_unsupported",
            reason=_code("BACKEND_PLATFORM_UNSUPPORTED", {"backend": "openvino_cpu"}),
        )

    # crispasr
    if "crispasr" in supported:
        entries["crispasr"] = _entry("ready")
    else:
        entries["crispasr"] = _entry(
            "platform_unsupported",
            reason=_code("BACKEND_PLATFORM_UNSUPPORTED", {"backend": "crispasr"}),
        )

    # chatllm_vulkan
    if "chatllm" in supported:
        entries["chatllm_vulkan"] = _entry("ready")
    else:
        entries["chatllm_vulkan"] = _entry(
            "platform_unsupported",
            reason=_code("BACKEND_PLATFORM_UNSUPPORTED", {"backend": "chatllm_vulkan"}),
        )

    # cuda_pytorch — never supported in this codebase (future placeholder)
    entries["cuda_pytorch"] = _entry(
        "platform_unsupported",
        reason=_code("BACKEND_PLATFORM_UNSUPPORTED", {"backend": "cuda_pytorch"}),
    )

    return entries


# ---------------------------------------------------------------------------
# Feature capability entries
# ---------------------------------------------------------------------------

def _feature_entries(platform: str, probes: dict) -> dict[str, dict]:
    """Build capability entries for optional features."""
    features: dict[str, dict] = {}

    # ffmpeg (video conversion + recording)
    if probes.get("ffmpeg"):
        features["ffmpeg"] = _entry("ready")
    else:
        features["ffmpeg"] = _entry(
            "setup_required",
            reason=_code("FFMPEG_MISSING"),
            remedy=_code("FFMPEG_MISSING"),
            action="install",
        )

    # cloudflared (tunnel)
    if probes.get("cloudflared"):
        features["cloudflared"] = _entry("ready")
    else:
        if platform == "win32":
            features["cloudflared"] = _entry(
                "setup_required",
                reason=_code("CLOUDFLARED_MISSING"),
                action="download",
            )
        else:
            features["cloudflared"] = _entry(
                "setup_required",
                reason=_code("CLOUDFLARED_MISSING"),
                remedy=_code("CLOUDFLARED_MISSING"),
                action="install",
            )

    # forced_alignment
    from alignment_policy import alignment_capability
    align = alignment_capability(platform=platform)
    if align["state"] == "platform_unsupported":
        features["forced_alignment"] = _entry(
            "platform_unsupported",
            reason=align.get("reason"),
        )
    elif align["state"] == "ready":
        features["forced_alignment"] = _entry("ready")
    else:
        features["forced_alignment"] = _entry(
            "setup_required",
            reason=align.get("reason"),
            action="download",
        )

    # diarization
    if probes.get("diarization"):
        features["diarization"] = _entry("ready")
    else:
        features["diarization"] = _entry(
            "setup_required",
            reason=_code("MODEL_MISSING", {"model": "diarization"}),
            action="download",
        )

    # endpoint — always available (binding is in api_server.py, no special dep)
    features["endpoint"] = _entry("ready")

    return features


# ---------------------------------------------------------------------------
# Status line
# ---------------------------------------------------------------------------

def _build_status_line(platform: str, pref_internal: str,
                        effective_internal: str) -> dict | None:
    if platform != "win32" and pref_internal != effective_internal:
        # Preference was a Windows-only backend; using OpenVINO instead
        return _code("USING_OPENVINO_CPU_UBUNTU_PREF_PRESERVED")
    return None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def _build_health(effective_internal: str, backend_entries: dict,
                  feature_entries: dict, probes: dict) -> dict:
    """Health blockers include only effective backend + core workflow issues.

    Optional features (ffmpeg, cloudflared, diarization, forced_alignment)
    are never blockers — they degrade gracefully.
    """
    blockers: list[dict] = []
    optional: list[dict] = []

    eff_snapshot_key = _BACKEND_KEYS.get(effective_internal, "openvino_cpu")
    eff_entry = backend_entries.get(eff_snapshot_key, {})
    if eff_entry.get("state") not in ("ready", None):
        blockers.append({
            "key": eff_snapshot_key,
            "state": eff_entry["state"],
            "reason": eff_entry.get("reason"),
        })

    # Model availability is a core blocker when model_state == "error"
    if probes.get("model_state") == "error":
        blockers.append({
            "key": "model",
            "state": "error",
            "reason": _code("MODEL_MISSING", {"model": probes.get("model_error", "")}),
        })

    # Optional: ffmpeg, cloudflared, forced_alignment, diarization
    for feat_key in ("ffmpeg", "cloudflared", "forced_alignment", "diarization"):
        entry = feature_entries.get(feat_key, {})
        if entry.get("state") not in ("ready",):
            optional.append({
                "key": feat_key,
                "state": entry["state"],
                "reason": entry.get("reason"),
                "remedy": entry.get("remedy"),
            })

    return {"blockers": blockers, "optional": optional}


# ---------------------------------------------------------------------------
# Recovery events
# ---------------------------------------------------------------------------

def _build_recovery_events(settings_store: "SettingsStore") -> list[dict]:
    events: list[dict] = []
    if getattr(settings_store, "recovered", None):
        events.append({
            "code": "SETTINGS_RECOVERED",
            "params": {"backup_path": settings_store.recovered},
        })
    for key, reason_code in getattr(settings_store, "session_ignored", []):
        events.append({
            "code": reason_code,
            "params": {"key": key},
        })
    return events


# ---------------------------------------------------------------------------
# Navigation hint
# ---------------------------------------------------------------------------

def _navigation_hint(probes: dict, model_entry: dict | None) -> dict:
    """Determine where the frontend should navigate the user.

    Rules (from decision doc 03):
    - Missing prerequisites -> model page
    - loading / ready -> workspace
    - load failure -> model page (with recovery actions)
    """
    model_state = probes.get("model_state", "unloaded")
    if model_state == "ready":
        return {"target": "workspace"}
    if model_state == "loading":
        return {"target": "workspace"}
    if model_state == "error":
        return {"target": "model"}
    # unloaded — check if model is present
    if probes.get("model_present"):
        return {"target": "workspace"}
    return {"target": "model"}


# ---------------------------------------------------------------------------
# Model capability entry
# ---------------------------------------------------------------------------

def _model_entry(probes: dict, effective_internal: str, effective_model: str) -> dict:
    """Return a capability entry for the effective model."""
    if probes.get("model_present"):
        return _entry("ready")
    return _entry(
        "setup_required",
        reason=_code("MODEL_MISSING", {"model": effective_model}),
        action="download",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_snapshot(
    platform: str,
    settings_store: "SettingsStore",
    probes: dict,
) -> dict:
    """Build and return the capability snapshot dict.

    Parameters
    ----------
    platform:
        sys.platform string, e.g. "linux" or "win32".
    settings_store:
        A loaded SettingsStore instance.
    probes:
        A dict of discovered probe results:
          ffmpeg (bool), cloudflared (bool), model_present (bool),
          model_state (str), model_error (str|None), diarization (bool).
    """
    # Resolve preference and effective backend
    pref_raw = settings_store.get("backend")
    pref_internal = pref_raw or ("openvino" if platform != "win32" else "crispasr")
    effective_internal = _resolve_effective_backend(platform, pref_internal)
    effective_model = _resolve_effective_model(platform, settings_store, effective_internal)

    # Backend + feature capability entries
    backend_entries = _backend_entries(platform)
    feature_entries = _feature_entries(platform, probes)

    # Model state
    model_state_str = probes.get("model_state", "unloaded")
    model_error = probes.get("model_error")
    model_state = {"state": model_state_str, "message": model_error}

    # Status line
    status_line = _build_status_line(platform, pref_internal, effective_internal)

    # Health
    health = _build_health(effective_internal, backend_entries, feature_entries, probes)

    # Recovery events
    recovery_events = _build_recovery_events(settings_store)

    # Navigation hint
    nav_hint = _navigation_hint(probes, None)

    return {
        "backend_preference": pref_internal,
        "effective_backend": effective_internal,
        "effective_model": effective_model,
        "status_line": status_line,
        "model_state": model_state,
        "backends": backend_entries,
        "features": feature_entries,
        "health": health,
        "recovery_events": recovery_events,
        "navigation_hint": nav_hint,
    }
