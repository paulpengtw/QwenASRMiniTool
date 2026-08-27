"""alignment_policy.py — Capability classification for forced-aligner (exact word-timing).

ForcedAligner (chatllm main.exe) is a Windows-only binary.  On every other
platform the effective alignment method is proportional estimation, and the
state is platform_unsupported.

Public API
----------
alignment_capability(platform: str = sys.platform) -> dict
    Returns a capability snapshot dict with the keys:
      method  : "exact" | "proportional"
      state   : "ready" | "setup_required" | "platform_unsupported"
      reason  : {"code": str, "params": dict}
"""
from __future__ import annotations

import sys

_REASON_WIN_ONLY = {"code": "ALIGN_WINDOWS_ONLY", "params": {}}


def alignment_capability(platform: str = sys.platform) -> dict:
    """Return the alignment capability snapshot for *platform*.

    On win32 the ForcedAligner binary may be present (exact / ready).
    On every other platform exact alignment is platform_unsupported and
    the method degrades to proportional estimation.
    """
    if platform == "win32":
        return {
            "method": "exact",
            "state": "ready",
            "reason": _REASON_WIN_ONLY,
        }
    return {
        "method": "proportional",
        "state": "platform_unsupported",
        "reason": _REASON_WIN_ONLY,
    }
