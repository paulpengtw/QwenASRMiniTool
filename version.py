"""version.py — 應用程式版本與更新來源設定（單一事實來源）

此檔同時被 app.py / app-gpu.py / setting.py / updater.py 引用。
打包時務必以 --add-data 一併納入 EXE，讓自動更新能正確比對版本。

版本規則：
    語意化版本 MAJOR.MINOR.PATCH。
    每次發佈新編譯版時，先把 __version__ 往上加（例如 1.0.6 → 1.0.7），
    再到 GitHub 建立同名 tag 的 Release，並上傳整包 ZIP 資產。
"""
from __future__ import annotations

# 本次編譯版本（dist2）。1.0.9：新增 Whisper/Breeze-ASR-26 推理核心
# (CrispASR / Vulkan，-nf -bo1 達 ~35x，繁中/台語特化)、qwen3 ForcedAligner
# GGUF 字級時間軸對齊、核心切換 Vulkan context 防當機修正、字幕分行全引擎統一
# (subtitle_lines，標點/空白邊界切 + MAX_CHARS 保護 + 孤兒行合併)。
# 最新已發佈 Release 為 1.0.8。
__version__ = "1.0.9"

# WebView 版獨立版本字串（與 CTk 桌面版的語意化 __version__ 分流）。
# WebView 介面為全新重構，從 0.1 重新起算；顯示於 WebView 設定頁的版本徽章。
# （CTk 桌面版仍沿用上面的 __version__ 做語意化更新比對，互不干擾。）
#
# ── WebView 0.1 更新彙整（本版所有變更集中於此）────────────────────────────
#   介面：全新淺色 teal WebView 介面（本機 stdlib HTTP server + 原生 WebView2 窗），
#         python / 端點 / 獨立 EXE 三版共用同一前端。標題「聲音辨識小工具」+ 貓耳耳機圖示。
#   核心：CrispASR(Vulkan) 為主，預設「Qwen3-ASR-1.7B Q4」；OpenVINO(CPU) 共存；
#         chatllm 保留向下相容（有檔才現身、不隨包附帶）。裝置偵測改走 crispasr --diagnostics。
#   流程：開機若選擇的模型未下載 → 停模型頁不自動抓，待使用者按「下載並載入」（可改 Whisper），
#         首次免重啟就地下載載入；已下載則自動載入並進語音轉文字。
#   功能：音檔 / 批次 / 錄製（麥克風選擇＋即時存檔）/ 端點（QR＋Cloudflare）/ 模型自檢。
#   外觀：i18n（繁中／简体／English）、深淺色主題（視窗標題列同步）、介面縮放，全部實裝。
#   打包：crispasr 核心隨包、VAD onnx 隨包；ffmpeg / chatllm 按需下載或外帶（不入安裝包）。
#
# ── WebView 0.2 更新彙整（在 0.1 基礎上）──────────────────────────────────────
#   核心：CrispASR 核心升級 v0.7.1→v0.8.8（GPU 偵測/日語 qwen3 後端驗證）。
#   日語：新增 Qwen3-ASR-1.7B 日語動漫特化模型（cstr/ja-anime，Q4/Q8），日文歌詞/
#         台詞辨識明顯較佳；語言選日語時跳過 OpenCC 繁化，保留日文原生漢字。
#   體驗：卡拉OK逐字模式（字級時間軸貫通、播放逐字高亮）、真實波形+播放頭+分段標註、
#         設定頁「每段最長秒數」滑桿（減少長段字級段尾漂移）。
#
# ── WebView 0.2.1 更新彙整（hotfix）──────────────────────────────────────────
#   修復：1.7B INT8 (CPU/OpenVINO) 無法載入——ce1f8b0 重構誤刪 KV-cache 實作，
#         導致選 1.7B 實際讀取 0.6B 目錄（只裝 1.7B 直接報錯、兩者皆裝則默默
#         跑 0.6B）。復原 prefill+decode KV-cache 推理並改掛勾式覆寫，1.7B 同步
#         取得 cpu_threads／FA 字級對齊等後續功能。
#   改善：說話者分離聚類改版——長段落切 3 秒子窗逐窗提聲紋、自動人數改
#         silhouette 選擇＋雙重單人防護，修「同人被拆／異人被併」；短段落
#         不再丟棄（修 OpenVINO 路徑短句漏字）。
WEBVIEW_VERSION = "webview 0.2.1"

# 自動更新來源：GitHub repo（owner/name）
GITHUB_REPO = "dseditor/QwenASRMiniTool"

# GitHub Releases API（latest 端點，回傳最新「非預發佈」版本）
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# 發行頁（供「前往下載頁」按鈕使用）
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
