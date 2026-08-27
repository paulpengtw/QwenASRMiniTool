#!/usr/bin/env bash
# run.sh — Ubuntu launch gate for Qwen ASR Mini Tool.
# Ubuntu 的啟動檢查腳本。
#
# Requirements: uv installed and the Python environment in sync.
# 需求：已安裝 uv，且 Python 環境與 pyproject.toml 同步。
set -euo pipefail

# ---------------------------------------------------------------------------
# 1. Verify uv is available
# 驗證 uv 是否已安裝
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is not installed. Install it with:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "  See: https://docs.astral.sh/uv/"
  echo ""
  echo "錯誤：未安裝 uv。請執行以下指令安裝："
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "  說明：https://docs.astral.sh/uv/"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Verify the environment is up to date (local, no network)
# 驗證環境是否與 pyproject.toml 同步（僅本機檢查，無需網路）
# ---------------------------------------------------------------------------

# Use "uv sync --check" if supported; fall back to "uv lock --check".
# Both are local no-network assertions.
if uv sync --help 2>&1 | grep -q -- '--check'; then
  CHECK_CMD="uv sync --check"
else
  CHECK_CMD="uv lock --check"
fi

if ! ${CHECK_CMD} >/dev/null 2>&1; then
  echo "ERROR: The Python environment is out of date. Fix it with:"
  echo "  uv sync"
  echo ""
  echo "錯誤：Python 環境與 pyproject.toml 不同步。請執行以下指令更新："
  echo "  uv sync"
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. Run preflight check if it exists (ticket 02 will add preflight.py)
# 若存在 preflight.py，執行預檢（preflight.py 將由 ticket 02 加入）
# set -e causes the script to exit non-zero if preflight.py fails.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/preflight.py" ]; then
  uv run python "${SCRIPT_DIR}/preflight.py"
fi

# ---------------------------------------------------------------------------
# 4. Launch the application (exec replaces this shell — no zombie parent)
# 啟動應用程式（exec 取代本 shell，避免殭屍程序）
#
# On Linux: ubuntu_launcher.py handles browser lifecycle (ticket 13).
# On Windows: app_webview.py handles the WebView2/Edge path (unchanged).
# Linux 上：由 ubuntu_launcher.py 處理瀏覽器生命週期（ticket 13）。
# Windows 上：由 app_webview.py 處理 WebView2/Edge 路徑（不變）。
# ---------------------------------------------------------------------------
exec uv run python "${SCRIPT_DIR}/ubuntu_launcher.py"
