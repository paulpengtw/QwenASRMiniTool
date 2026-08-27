# Ubuntu Install Guide — Qwen ASR Mini Tool

Supported platform: **Ubuntu 24.04 LTS x86-64** (source install).

---

## 1. Prerequisites

Install the required system packages once:

```bash
sudo apt update
sudo apt install -y ca-certificates ffmpeg xdg-utils python3-tk
```

| Package | Purpose |
|---------|---------|
| `ca-certificates` | TLS certificate chain for model downloads |
| `ffmpeg` | Video track extraction and microphone recording |
| `xdg-utils` | Browser launching (`xdg-open`) |
| `python3-tk` | Tk runtime (required by the OpenVINO engine graph at import time) |

Then install **uv** (not in the Ubuntu 24.04 archive — install from the official script):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Add uv to your PATH if your shell did not do it automatically:
source "$HOME/.local/bin/env"
```

---

## 2. Get the source and sync the Python environment

```bash
git clone https://github.com/paulpengtw/QwenASRMiniTool.git
cd QwenASRMiniTool
uv sync
```

`uv sync` creates a `.venv` using the system Python 3.12 and installs every
dependency declared in `pyproject.toml` and pinned in `uv.lock`.  It is
idempotent: run it again after any `git pull` to keep the environment current.

---

## 3. First launch

```bash
./run.sh
```

`run.sh` performs three checks before starting the application:

1. **uv present** — if not, prints installation instructions (bilingual) and exits.
2. **Environment in sync** — runs `uv sync --check` locally without network access;
   if the environment is out of date, prints `uv sync` as the fix and exits.
3. **Preflight** — runs `preflight.py` if present; a non-zero exit aborts launch.

On success the server starts, waits until `/health` responds, then opens your
default browser at `http://127.0.0.1:<port>/`.

### First launch with no models

The application opens in the browser UI with a **Model** tab.  No transcription
is possible until a model is downloaded.  Continue to the next step.

---

## 4. Download the 0.6B model (recommended first model)

In the browser UI, open the **Model** tab, select **Qwen3-ASR-0.6B (OpenVINO
INT8)**, and click **Download and load model**.  The download progress is shown
in the UI.

Alternatively, request a download from the terminal after launch:

```
Model tab → select 0.6B OpenVINO INT8 → "Download and load model"
```

The model files land in `ov_models/` inside the repository.  A `.part` suffix
means the download is in progress; `os.replace` atomically renames the file when
complete, so a file at its real name is always complete.

---

## 5. Transcribe audio

After the model is loaded, open the **Transcribe** tab, upload a WAV/MP3/M4A
file, and click **Transcribe**.

---

## 6. Convert video (requires FFmpeg)

Upload an MP4 or MKV file on the **Transcribe** tab.  FFmpeg extracts the audio
track automatically.  If FFmpeg is missing, the app degrades gracefully: audio
transcription still works, video conversion is disabled.

Remedy if FFmpeg is missing:

```bash
sudo apt install ffmpeg
```

---

## 7. Record from microphone

Open the **Microphone** tab.  This requires FFmpeg.  Closing the browser tab
while recording stops capture and retains already-transcribed segments for the
next connection.

---

## 8. Expose the API endpoint (optional)

Open the **Endpoint** tab to start the OpenAI-compatible transcription endpoint
on a LAN port.  The endpoint key and port are shown in the UI.  Call it from
another machine on the same network:

```bash
curl -X POST http://<LAN-IP>:<port>/v1/audio/transcriptions \
     -H "Authorization: Bearer <key>" \
     -F "file=@audio.wav" \
     -F "model=whisper-1"
```

---

## 9. Cloudflared tunnel (optional)

Install `cloudflared` from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
to expose the endpoint over the internet without port-forwarding:

```bash
# Debian/Ubuntu package:
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
```

Then use the **Tunnel** tab in the UI.

---

## 10. Quitting

- Click **Quit local app** in the browser UI, or press **Ctrl+C** in the terminal.
- The server stops within 10 seconds; all durable writes complete before exit.
- A second **Ctrl+C** forces immediate termination.

---

## 11. Troubleshooting

Error codes are printed to the terminal and link to `capability_codes.py` for
full descriptions.

| Code | Meaning | Remedy |
|------|---------|--------|
| `LOOPBACK_PORT_UNAVAILABLE` | The random loopback port could not be bound | Another process occupies the port; retry |
| `DEP_IMPORT_FAILED` | A required Python module failed to import | Run `uv sync`; check Python 3.12 is available |
| `BROWSER_OPEN_FAILED` | Browser could not be opened automatically | Install `xdg-utils` (`sudo apt install xdg-utils`); navigate to the printed URL manually |
| `FFMPEG_MISSING` | FFmpeg not on PATH | `sudo apt install ffmpeg` |
| `CA_CERTS_MISSING` | TLS chain missing | `sudo apt install ca-certificates` |
| `UV_ENV_OUT_OF_DATE` | `.venv` is behind `pyproject.toml` | `uv sync` |

**Browser opens but the page is blank**: ensure `python3-tk` is installed
(`sudo apt install python3-tk`) and restart.

**"Could not open a browser"**: the URL is printed to the terminal.  Open it
manually in any browser.  The server keeps serving until you press Ctrl+C.

**Session file**: a per-user session file is written to the application directory.
If the app crashed and a new launch complains about a stale session, simply
re-run `./run.sh`; stale ownership is detected and replaced automatically.

---

## See also

- [Ubuntu Clean-VM Manual Checklist](ubuntu-clean-vm-checklist.md)
- [`capability_codes.py`](../capability_codes.py) — full error code registry
