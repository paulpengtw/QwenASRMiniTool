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
    return stub


if "app" not in sys.modules:
    sys.modules["app"] = _make_app_stub()

# Stub other problematic imports that webview_backend may pull in
for _mod in ("customtkinter", "tkinter", "tkinter.filedialog",
             "pywebview", "webview"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
