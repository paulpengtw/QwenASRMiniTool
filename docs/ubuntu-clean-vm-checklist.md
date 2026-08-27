# Ubuntu Clean-VM Manual Checklist

**Platform:** Ubuntu 24.04 LTS x86-64 (fresh VM, no prior install)

**Purpose:** Walk the full documented install from scratch and verify every
workflow in the Ubuntu source-support contract (decision 07).  Run this
checklist whenever the prerequisite matrix changes (new system package,
Python version, or uv requirement).

---

## Before you start

- Start from a **fresh** Ubuntu 24.04 VM (no pre-installed Python venvs,
  no previous clone of this repo).
- You need two machines (or two terminals on a LAN) for the endpoint step.
- Record any step that diverges from the expected output.

---

## Step 1 — Install system prerequisites

```bash
sudo apt update
sudo apt install -y ca-certificates ffmpeg xdg-utils python3-tk
```

**Expected:** no errors; `ffmpeg -version` and `python3 --version` print versions.

---

## Step 2 — Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

**Expected:** `uv` prints a version string (e.g. `uv 0.x.y`).

---

## Step 3 — Clone and sync the environment

```bash
git clone https://github.com/paulpengtw/QwenASRMiniTool.git
cd QwenASRMiniTool
uv sync
```

**Expected:** `uv sync` completes without errors; `.venv/` is created.

---

## Step 4 — First launch with no models

```bash
./run.sh
```

**Expected:**
- `run.sh` passes all three gates (uv present, env in sync, preflight).
- The server starts and prints `http://127.0.0.1:<port>/`.
- The default browser opens the UI.
- The **Model** tab shows that no model is loaded.
- No transcription is possible yet (Model tab prompts download).

Press **Ctrl+C** to stop before proceeding.

---

## Step 5 — Download the 0.6B model

```bash
./run.sh
```

In the browser UI:

1. Open the **Model** tab.
2. Select **Qwen3-ASR-0.6B (OpenVINO INT8)**.
3. Click **Download and load model**.
4. Wait for the progress bar to complete and the model status to show **Loaded**.

**Expected:** model files appear in `ov_models/`; no `.part` suffix remains.

---

## Step 6 — Transcribe an audio file

In the browser UI:

1. Open the **Transcribe** tab.
2. Upload a short WAV or MP3 file.
3. Click **Transcribe**.

**Expected:** subtitle segments appear in the results area within a reasonable
time; an SRT file is saved to `subtitles/`.

---

## Step 7 — Convert a video file

In the browser UI:

1. Open the **Transcribe** tab.
2. Upload an MP4 or MKV file.
3. Click **Transcribe**.

**Expected:** FFmpeg extracts the audio track; transcription proceeds and
produces subtitle segments as in Step 6.

---

## Step 8 — Record from microphone

In the browser UI:

1. Open the **Microphone** tab.
2. Select your microphone device.
3. Click **Start recording** and speak for a few seconds.
4. Click **Stop**.

**Expected:** transcribed segments appear in real time (or near real time);
stopping preserves already-transcribed segments.

---

## Step 9 — Start the endpoint and call it from a second machine

In the browser UI:

1. Open the **Endpoint** tab.
2. Click **Start endpoint**.
3. Note the LAN IP, port, and API key shown.

From the **second machine** (same LAN):

```bash
curl -X POST http://<LAN-IP>:<port>/v1/audio/transcriptions \
     -H "Authorization: Bearer <key>" \
     -F "file=@audio.wav" \
     -F "model=whisper-1"
```

**Expected:** JSON response with transcription segments.

---

## Step 10 — Quit and confirm no orphaned processes

Press **Ctrl+C** in the terminal running `run.sh` (or click **Quit local app** in the UI).

**Expected:** the server stops cleanly within 10 seconds and exits.

Then confirm no orphaned ffmpeg or cloudflared processes remain:

```bash
pgrep -a ffmpeg
pgrep -a cloudflared
```

**Expected:** both commands return nothing (exit 1 with no output), confirming
that `PR_SET_PDEATHSIG` and `killpg` cleanup worked correctly (decision 07).

---

## Re-run when

- The `apt` prerequisite list changes (new package added or removed).
- The minimum Python version changes.
- The minimum `uv` version changes.
- A new workflow is added to the Ubuntu source-support contract.
- A significant change is made to `run.sh`, `ubuntu_launcher.py`,
  `platform_seams.py`, or `proc_guard.py`.

---

## See also

- [Ubuntu Install Guide](ubuntu.md)
- [`capability_codes.py`](../capability_codes.py) — error code registry
