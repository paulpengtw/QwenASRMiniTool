from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub heavy GUI / platform dependencies so webview_backend can be imported
# in the CI/Linux test environment that has no tkinter, pywebview, etc.
# ---------------------------------------------------------------------------

def _make_app_stub():
    """Return a minimal stub of the 'app' module that webview_backend needs."""
    stub = types.ModuleType("app")
    stub.BASE_DIR = ROOT
    stub.SETTINGS_FILE = str(ROOT / "settings.json")
    stub.SRT_DIR = str(ROOT / "subtitles")
    stub._DEFAULT_MODEL_DIR = ROOT / "ov_models"
    stub._CHATLLM_DIR = ROOT / "chatllm"
    stub._BIN_PATH = ROOT / "ov_models" / "qwen3-asr-1.7b.bin"
    stub._MEIPASS = None
    stub._g_output_simplified = False
    stub._g_vocab_convert = True

    class _FakeEngine:
        ready = False
        use_aligner = False
        _fa_bin = None
        diar_engine = None
        def transcribe(self, *a, **kw): return []
        def _load_aligner(self, cb=None): pass

    stub.ASREngine = _FakeEngine
    stub.ASREngine1p7B = _FakeEngine
    stub.probe_vulkan_devices = lambda *a, **kw: []

    # Ticket 15: backend-reader audit — include the derived-fallback helpers
    # so tests that import `app` and call these pure functions get real behaviour.
    def _ui_core_model(settings: dict):
        """settings → (core_label, model_label); derived fallback: openvino."""
        backend = settings.get("backend", "openvino")
        if backend == "crispasr":
            q = settings.get("crisp_quant", "q5")
            label = {"q4": "Breeze Q4 (輕量)", "q5": "Breeze Q5 (標準)",
                     "q8": "Breeze Q8 (精確)"}.get(q, "Breeze Q5 (標準)")
            return "Whisper (Breeze)", label
        if backend == "chatllm":
            return "Qwen", "Qwen3-ASR-1.7B Q8 (Vulkan)"
        sz = settings.get("cpu_model_size", "0.6B")
        return "Qwen", ("Qwen3-ASR-1.7B INT8" if "1.7B" in sz else "Qwen3-ASR-0.6B")

    stub._ui_core_model = _ui_core_model
    return stub


if "app" not in sys.modules:
    sys.modules["app"] = _make_app_stub()

# Stub other problematic imports that webview_backend may pull in.
# customtkinter needs a richer stub so ffmpeg_utils.py can define
# FFmpegDownloadDialog(ctk.CTkToplevel) at import time without AttributeError.
def _make_ctk_stub():
    """Return a customtkinter stub with the ctk widget base classes needed."""
    ctk = types.ModuleType("customtkinter")

    class _Base:
        def __init__(self, *a, **kw): pass
        def pack(self, *a, **kw): pass
        def configure(self, *a, **kw): pass
        def after(self, *a, **kw): pass
        def destroy(self): pass
        def grab_set(self): pass
        def deiconify(self): pass
        def lift(self): pass
        def focus_force(self): pass
        def protocol(self, *a, **kw): pass
        def geometry(self, *a, **kw): pass
        def resizable(self, *a, **kw): pass
        def title(self, *a, **kw): pass
        def set(self, *a, **kw): pass
        def start(self, *a, **kw): pass
        def stop(self, *a, **kw): pass

    ctk.CTkToplevel = _Base
    ctk.CTkLabel = _Base
    ctk.CTkProgressBar = _Base
    ctk.CTkButton = _Base
    ctk.CTkFrame = _Base
    ctk.CTkEntry = _Base
    ctk.CTkTextbox = _Base
    ctk.CTkScrollableFrame = _Base
    return ctk


if "customtkinter" not in sys.modules:
    sys.modules["customtkinter"] = _make_ctk_stub()

for _mod in ("tkinter", "tkinter.filedialog", "pywebview", "webview"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
