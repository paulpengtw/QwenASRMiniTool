"""
Capability code registry for bilingual (English + Chinese) preflight messages.

Each entry has:
  en: English template with optional {param} placeholders
  zh: Chinese template with matching {param} placeholders
  severity: "fatal" | "degraded" | "info"
"""

import json
import re

CODES: dict[str, dict] = {
    "PY_VERSION_TOO_OLD": {
        "en": "Python {required} or newer is required; found {found}.",
        "zh": "需要 Python {required} 或更新版本；目前版本為 {found}。",
        "severity": "fatal",
    },
    "BASE_DIR_NOT_WRITABLE": {
        "en": "Base directory is not writable: {path}",
        "zh": "基礎目錄無法寫入：{path}",
        "severity": "fatal",
    },
    "LOOPBACK_PORT_UNAVAILABLE": {
        "en": "Loopback port {port} is unavailable.",
        "zh": "迴路埠 {port} 無法使用。",
        "severity": "fatal",
    },
    "DEP_IMPORT_FAILED": {
        "en": "Required module '{module}' could not be imported.",
        "zh": "必要模組「{module}」無法匯入。",
        "severity": "fatal",
    },
    "FFMPEG_MISSING": {
        "en": "FFmpeg is not on PATH. Video and recording features are unavailable. Remedy: sudo apt install ffmpeg",
        "zh": "FFmpeg 不在 PATH 中，視訊和錄音功能無法使用。修復方式：sudo apt install ffmpeg",
        "severity": "degraded",
    },
    "BROWSER_OPEN_FAILED": {
        "en": "Could not open a browser. The app is available at {url}",
        "zh": "無法開啟瀏覽器。應用程式位址：{url}",
        "severity": "degraded",
    },
    "VAD_MISSING": {
        "en": "Voice activity detection model is missing. Transcription may not start.",
        "zh": "語音活動偵測模型缺失，轉錄可能無法啟動。",
        "severity": "degraded",
    },
    "MODEL_MISSING": {
        "en": "ASR model '{model}' is missing. Download it before transcribing.",
        "zh": "ASR 模型「{model}」缺失，請在轉錄前下載。",
        "severity": "degraded",
    },
    "CA_CERTS_MISSING": {
        "en": "CA certificates not found. TLS connections may fail. Remedy: sudo apt install ca-certificates",
        "zh": "找不到 CA 憑證，TLS 連線可能失敗。修復方式：sudo apt install ca-certificates",
        "severity": "degraded",
    },
    "CLOUDFLARED_MISSING": {
        "en": "cloudflared is not on PATH. Tunnel features are unavailable. Install via package manager (e.g. apt, brew) or download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/",
        "zh": "cloudflared 不在 PATH 中，通道功能無法使用。請透過套件管理員安裝（如 apt、brew）或從 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ 下載。",
        "severity": "degraded",
    },
    "VIDEO_NEEDS_FFMPEG": {
        "en": "This video file requires FFmpeg to extract audio. Remedy: {remedy}",
        "zh": "此影片需要 FFmpeg 提取音軌。修復方式：{remedy}",
        "severity": "degraded",
    },
    "RECORDING_NEEDS_FFMPEG": {
        "en": "Microphone recording (WebM/Opus) requires FFmpeg to process. Remedy: {remedy}",
        "zh": "麥克風錄音（WebM/Opus）需要 FFmpeg 才能處理。修復方式：{remedy}",
        "severity": "degraded",
    },
    "ENDPOINT_LAN_EXPOSED": {
        "en": "The endpoint is now accessible from other machines on this local network at: {urls}",
        "zh": "端點現在可從區域網路上的其他電腦存取，網址：{urls}",
        "severity": "info",
    },
    "ALIGN_WINDOWS_ONLY": {
        "en": "Forced alignment is only supported on Windows.",
        "zh": "強制對齊功能僅在 Windows 上支援。",
        "severity": "info",
    },
    "BACKEND_PLATFORM_UNSUPPORTED": {
        "en": "Backend '{backend}' is not supported on this platform.",
        "zh": "後端「{backend}」在此平台上不受支援。",
        "severity": "degraded",
    },
    "USING_OPENVINO_CPU_UBUNTU_PREF_PRESERVED": {
        "en": "Using OpenVINO CPU on Ubuntu. Your Windows backend preference is preserved.",
        "zh": "在 Ubuntu 上使用 OpenVINO CPU，您的 Windows 後端偏好已保留。",
        "severity": "info",
    },
    "SETTINGS_RECOVERED": {
        "en": "Settings were corrupt and have been recovered. Backup saved to: {backup_path}",
        "zh": "設定檔已損毀並已復原，備份儲存於：{backup_path}",
        "severity": "info",
    },
    "UV_ENV_OUT_OF_DATE": {
        "en": "The uv virtual environment is out of date. Run: uv sync",
        "zh": "uv 虛擬環境已過期，請執行：uv sync",
        "severity": "degraded",
    },
}

_PARAM_RE = re.compile(r"\{(\w+)\}")


def render(code: str, params: dict | None = None, lang: str = "en") -> str:
    """Render a capability code message in the requested language.

    Unknown codes render as the code string itself (never raises).
    """
    if params is None:
        params = {}
    entry = CODES.get(code)
    if entry is None:
        return code
    template = entry.get(lang) or entry.get("en") or code
    try:
        return template.format_map(params)
    except KeyError:
        # Missing params: leave placeholders as-is
        return template


def as_json() -> str:
    """Return the full CODES registry as a JSON string."""
    return json.dumps(CODES, ensure_ascii=False, indent=2)
