"""settings_store.py — Versioned cross-platform settings store (schema v2).

Schema v2 layout
----------------
{
  "schema_version": 2,
  "shared": { ... },           # portable prefs, path keys relative to base_dir
  "platforms": {
    "win32": { ... },          # Windows-local prefs (machine-bound)
    "linux": { ... },          # Linux-local prefs  (machine-bound)
  },
  "backends": { ... },         # backend-specific blobs (future use)
  # Legacy flat keys — Windows-authored, preserved untouched:
  "backend": "...",
  ...
}

Key portability
---------------
PORTABLE_KEYS:
    output_format, hf_mirror, ui_lang, vad_threshold, chunk_secs,
    appearance, vocab_convert, output_simplified, cpu_model_size,
    ui_scale_percent
    → on Linux, written to "shared".

MACHINE_BOUND_KEYS:
    backend, device, endpoint_port, endpoint_key,
    crisp_model, crisp_quant, crisp_qwen_quant
    → on Linux, written to "platforms.linux".

PATH_KEYS:
    model_dir, gpu_model_dir, model_path, gguf_path,
    chatllm_dir, crispasr_dir, ffmpeg_path
    → on Linux: if value is under base_dir → stored RELATIVE (forward slashes)
      in "shared"; outside base_dir → stored absolute in "platforms.linux".

Windows (win32) writes the flat block exclusively (legacy Windows ownership).
Ubuntu (linux) never touches the flat block; it reads flat keys as fallback.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Key classification
# ---------------------------------------------------------------------------

PATH_KEYS: frozenset[str] = frozenset({
    "model_dir", "gpu_model_dir", "model_path",
    "gguf_path", "chatllm_dir", "crispasr_dir", "ffmpeg_path",
})

# Semantically platform-agnostic user preferences — live in "shared" on Linux.
PORTABLE_KEYS: frozenset[str] = frozenset({
    "output_format", "hf_mirror", "ui_lang", "vad_threshold", "chunk_secs",
    "appearance", "vocab_convert", "output_simplified", "cpu_model_size",
    "ui_scale_percent",
})

# Per-machine choices — live in "platforms.<os>" on Linux.
MACHINE_BOUND_KEYS: frozenset[str] = frozenset({
    "backend", "device", "endpoint_port", "endpoint_key",
    "crisp_model", "crisp_quant", "crisp_qwen_quant",
})

# ---------------------------------------------------------------------------
# Platform support tables
# ---------------------------------------------------------------------------

_SUPPORTED_BACKENDS: dict[str, set[str]] = {
    "win32":  {"openvino", "chatllm", "crispasr"},
    "linux":  {"openvino"},
}

_VALID_CPU_MODEL_SIZES: frozenset[str] = frozenset({"0.6B", "1.7B"})

# ---------------------------------------------------------------------------
# Derived defaults (never persisted — derived at runtime per platform)
# ---------------------------------------------------------------------------

def _win32_derived_defaults() -> dict:
    """Replicate webview_backend._seed_defaults derivation for win32."""
    return {
        "backend":          "crispasr",
        "crisp_model":      "qwen3",
        "crisp_qwen_quant": "q4",
    }


def _linux_derived_defaults() -> dict:
    return {
        "backend":        "openvino",
        "cpu_model_size": "0.6B",
    }


_DERIVED_DEFAULT_FACTORIES: dict[str, "Callable[[], dict]"] = {
    "win32": _win32_derived_defaults,
    "linux": _linux_derived_defaults,
}

# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def _validate_backend(value, *, platform: str, devices=None) -> bool:
    supported = _SUPPORTED_BACKENDS.get(platform, {"openvino"})
    return value in supported


def _validate_cpu_model_size(value, *, platform: str, devices=None) -> bool:
    return value in _VALID_CPU_MODEL_SIZES


def _validate_scale(value, *, platform: str, devices=None) -> bool:
    try:
        n = float(value)
        return 25.0 <= n <= 400.0
    except (TypeError, ValueError):
        return False


def _validate_device(value, *, platform: str, devices=None) -> bool:
    if devices is None:
        return True   # no list supplied → cannot validate
    return value in devices


_VALIDATOR_TABLE: dict[str, "Callable"] = {
    "backend":        _validate_backend,
    "cpu_model_size": _validate_cpu_model_size,
    "ui_scale_percent": _validate_scale,
    "device":         _validate_device,
}

# ---------------------------------------------------------------------------
# Helper: legacy ui_scale disambiguation
# ---------------------------------------------------------------------------

def _legacy_scale_to_percent(value) -> int:
    """Convert a legacy ui_scale value to an integer percent.

    < 10  → treated as a float multiplier  (×100 → int)
    >= 10 → already a percent              (→ int)
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 100
    if f < 10:
        return int(round(f * 100))
    return int(f)


# ---------------------------------------------------------------------------
# SettingsStore
# ---------------------------------------------------------------------------

class SettingsStore:
    """Thread-safe, atomic-write, versioned cross-platform settings store.

    Parameters
    ----------
    path:
        Path to settings.json (may not yet exist).
    platform:
        Current platform identifier (default: sys.platform).
    base_dir:
        Application base directory.  Path keys whose value falls under this
        directory are stored relative (shared); outside → machine-bound.
    """

    SCHEMA_VERSION: int = 2

    def __init__(
        self,
        path,
        platform: str | None = None,
        base_dir=None,
    ) -> None:
        self._path = Path(path)
        self._platform: str = platform if platform is not None else sys.platform
        self._base_dir: Path | None = Path(base_dir) if base_dir else None
        self._lock = threading.RLock()
        self._doc: dict = {}
        self.session_ignored: list[tuple[str, str]] = []
        self.recovered: str | None = None

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    def load(self) -> dict:
        """Load (and if necessary migrate) the document; return a shallow copy."""
        with self._lock:
            raw = self._read_raw()
            self._doc = self._migrate(raw)
            return dict(self._doc)

    def _read_raw(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            # Corrupt file — create a timestamped backup, start from empty.
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self._path.with_name(
                self._path.stem + f".json.corrupt-{ts}"
            )
            try:
                self._path.rename(backup)
                self.recovered = str(backup)
            except Exception:
                self.recovered = None
            return {}

    def _migrate(self, raw: dict) -> dict:
        """Migrate a v1 flat document to the v2 shape in memory.

        Rules:
        - Never delete or overwrite existing flat keys.
        - Never lower schema_version.
        - Copy unknown keys and namespaces through untouched.
        - Add missing top-level namespaces as empty dicts.
        - Stamp schema_version = max(existing, 2).
        """
        doc = dict(raw)
        doc.setdefault("shared", {})
        doc.setdefault("platforms", {})
        doc.setdefault("backends", {})
        existing_version = doc.get("schema_version", 0)
        doc["schema_version"] = max(existing_version, self.SCHEMA_VERSION)
        return doc

    # -----------------------------------------------------------------------
    # Save (atomic)
    # -----------------------------------------------------------------------

    def save(self) -> None:
        """Persist the in-memory document atomically.

        Writes to a temp file in the same directory, fsyncs, then calls
        os.replace so the operation is atomic on both NTFS and ext4.
        The in-progress write is serialised behind the RLock, so concurrent
        calls from multiple threads are safe.
        """
        with self._lock:
            doc = dict(self._doc)
            # Stamp schema_version — never lower it.
            doc["schema_version"] = max(
                doc.get("schema_version", 0), self.SCHEMA_VERSION
            )
            tmp = self._path.with_suffix(".json.tmp")
            text = json.dumps(doc, ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(str(tmp), str(self._path))

    # -----------------------------------------------------------------------
    # get
    # -----------------------------------------------------------------------

    def get(self, key: str, default=None):
        """Return the effective value for *key*.

        Resolution order:
          1. platforms.<current_os>  (machine-bound override)
          2. shared                  (portable preference)
          3. legacy flat             (Windows-authored value; read on all platforms)
          4. derived default         (platform-specific runtime derivation)
          5. *default* parameter
        """
        with self._lock:
            doc = self._doc

            # 1. platforms.<os>
            plat_ns: dict = doc.get("platforms", {}).get(self._platform, {})
            if key in plat_ns:
                value = plat_ns[key]
                resolved = self._resolve_path(key, value)
                # None means path exists in namespace but cannot resolve on this OS.
                if resolved is not None or key not in PATH_KEYS:
                    return resolved

            # 2. shared
            shared_ns: dict = doc.get("shared", {})
            if key in shared_ns:
                value = shared_ns[key]
                resolved = self._resolve_path(key, value)
                if resolved is not None or key not in PATH_KEYS:
                    return resolved

            # 3. legacy flat (skip structural namespace keys)
            _structural = {"schema_version", "shared", "platforms", "backends"}
            if key in doc and key not in _structural:
                value = doc[key]
                resolved = self._resolve_path(key, value)
                if resolved is not None or key not in PATH_KEYS:
                    return resolved

            # 4. derived default
            derived = self._derived_defaults()
            if key in derived:
                return derived[key]

            return default

    def _resolve_path(self, key: str, value):
        """Resolve a stored path to an absolute string, or None if unreachable."""
        if key not in PATH_KEYS or not value:
            return value
        p = Path(value)
        if p.is_absolute():
            # Machine-bound path — may belong to another platform.
            if p.exists():
                return str(p)
            return None   # foreign path not found → fall back to discovery
        else:
            # Relative path — resolve against base_dir.
            if self._base_dir:
                resolved = self._base_dir / p
                if resolved.exists():
                    return str(resolved)
                return None   # relative but not present → fall back
            return str(p)   # no base_dir; return as-is

    # -----------------------------------------------------------------------
    # set
    # -----------------------------------------------------------------------

    def set(self, key: str, value, scope: str = "auto") -> None:
        """Write *key* = *value* into the appropriate namespace.

        On **win32**: writes the flat block (legacy Windows ownership) and
        also mirrors into the appropriate new namespace.  Writing
        ``ui_scale_percent`` additionally mirrors the legacy float
        ``ui_scale`` (percent / 100) for older builds.

        On **linux** (and every other non-win32 platform): writes ONLY to
        ``platforms.linux`` (machine-bound) or ``shared`` (portable).  The
        flat block is never touched.

        *scope* may be ``"auto"`` (default), ``"shared"``, or ``"platform"``.
        ``"auto"`` applies the classification rules above.
        """
        with self._lock:
            doc = self._doc
            resolved_scope = self._resolve_scope(key, value, scope)

            if self._platform == "win32":
                # Windows: always write the flat key.
                doc[key] = value
                # Mirror ui_scale_percent → legacy float ui_scale.
                if key == "ui_scale_percent":
                    try:
                        doc["ui_scale"] = round(int(value) / 100, 4)
                    except (TypeError, ValueError):
                        pass
                # Also write into the canonical namespace.
                if resolved_scope == "shared":
                    stored = self._to_storage_path(key, value, "shared")
                    doc.setdefault("shared", {})[key] = stored
                else:
                    doc.setdefault("platforms", {}).setdefault(self._platform, {})[key] = value
            else:
                # Non-Windows: never touch the flat block.
                if resolved_scope == "shared":
                    stored = self._to_storage_path(key, value, "shared")
                    doc.setdefault("shared", {})[key] = stored
                else:
                    (doc
                     .setdefault("platforms", {})
                     .setdefault(self._platform, {}))[key] = value

    def _resolve_scope(self, key: str, value, scope: str) -> str:
        """Return ``"shared"`` or ``"platform"`` for this key/value."""
        if scope in ("shared", "platform"):
            return scope
        # scope == "auto"
        if key in PATH_KEYS:
            if value and self._base_dir:
                try:
                    Path(value).relative_to(self._base_dir)
                    return "shared"   # under base_dir → portable relative path
                except ValueError:
                    return "platform"  # outside base_dir → machine-bound
            return "platform"
        if key in PORTABLE_KEYS:
            return "shared"
        # machine-bound or unknown → platform
        return "platform"

    def _to_storage_path(self, key: str, value, target_scope: str):
        """Convert an absolute path to its storage form (relative for shared)."""
        if key not in PATH_KEYS or not value:
            return value
        p = Path(value)
        if target_scope == "shared" and self._base_dir and p.is_absolute():
            try:
                rel = p.relative_to(self._base_dir)
                return rel.as_posix()   # forward slashes, cross-platform
            except ValueError:
                pass
        return value

    # -----------------------------------------------------------------------
    # Validate
    # -----------------------------------------------------------------------

    def validate(self, key: str, value, devices=None) -> tuple[bool, str | None]:
        """Check whether *value* is honourable for *key*.

        An unhonourable value is appended to ``session_ignored`` with a
        reason code but is NOT removed from the document on disk — the
        value is left intact so another platform or machine that can honour
        it still gets it.

        Returns ``(True, None)`` or ``(False, reason_code)``.
        """
        validator = _VALIDATOR_TABLE.get(key)
        if validator is None:
            return True, None
        ok = validator(value, platform=self._platform, devices=devices)
        if not ok:
            reason = f"invalid_{key}"
            self.session_ignored.append((key, reason))
            return False, reason
        return True, None

    # -----------------------------------------------------------------------
    # ui_scale helpers
    # -----------------------------------------------------------------------

    def ui_scale_percent(self) -> int:
        """Return UI scale as an integer percent (e.g. 125 for 1.25×).

        Resolution:
        1. Canonical key ``ui_scale_percent`` (from any namespace via get()).
        2. Legacy flat key ``ui_scale`` with heuristic disambiguation.
        3. Default: 100.
        """
        val = self.get("ui_scale_percent")
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
        # Legacy key — read directly from the flat doc to bypass get()'s
        # resolution (which would call this again for the canonical key).
        with self._lock:
            legacy = self._doc.get("ui_scale")
        if legacy is not None:
            return _legacy_scale_to_percent(legacy)
        return 100

    def ui_scale_multiplier(self) -> float:
        """Return UI scale as a float multiplier (e.g. 1.25 for 125%)."""
        return self.ui_scale_percent() / 100.0

    # -----------------------------------------------------------------------
    # Derived defaults
    # -----------------------------------------------------------------------

    def _derived_defaults(self) -> dict:
        factory = _DERIVED_DEFAULT_FACTORIES.get(self._platform, lambda: {})
        return factory()

    def derived_default(self, key: str):
        """Return the platform-derived default for *key*, or None."""
        return self._derived_defaults().get(key)


# ---------------------------------------------------------------------------
# Module-level helper: read ui_scale as a multiplier from a settings file path
# ---------------------------------------------------------------------------

def read_ui_scale_multiplier(path) -> float:
    """Read ui_scale from *path* and return a float multiplier (e.g. 1.25 for 125%).

    Resolution:
    1. Canonical key ``ui_scale_percent`` (integer percent) → divide by 100.
    2. Legacy key ``ui_scale``:
       - value < 10 → treat as a float multiplier (return as-is).
       - value >= 10 → treat as an integer percent → divide by 100.
    3. Any error (file absent, corrupt JSON, missing key) → return 1.0.

    This applies the same heuristic as ``_legacy_scale_to_percent`` but
    returns a float multiplier rather than an integer percent, matching
    what ``ctk.set_widget_scaling()`` and ``setting.py`` expect.
    """
    try:
        p = Path(path)
        if not p.exists():
            return 1.0
        doc = json.loads(p.read_text(encoding="utf-8"))
        # Canonical key takes priority
        if "ui_scale_percent" in doc:
            try:
                return int(doc["ui_scale_percent"]) / 100.0
            except (TypeError, ValueError):
                pass
        # Legacy key
        if "ui_scale" in doc:
            return _legacy_scale_to_percent(doc["ui_scale"]) / 100.0
        return 1.0
    except Exception:
        return 1.0
