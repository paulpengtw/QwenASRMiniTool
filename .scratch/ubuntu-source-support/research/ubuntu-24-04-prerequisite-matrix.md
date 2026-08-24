# Ubuntu 24.04 prerequisite matrix

Research date: 2026-08-24
Target: Ubuntu 24.04 LTS, x86-64, source installation, browser UI, OpenVINO CPU. Windows behavior and settings remain compatible. Models/VAD are application-managed; FFmpeg and optional `cloudflared` are discovered through `PATH`.

## Recommendation

Ubuntu 24.04 + its default Python 3.12 is a sound baseline. OpenVINO 2026 supports Ubuntu 24.04 (kernel 6.8+) and Python 3.10–3.14, and ONNX Runtime publishes its CPU package for Linux x64 ([OpenVINO system requirements](https://docs.openvino.ai/2026/about-openvino/release-notes-openvino/system-requirements.html), [ONNX Runtime Python builds](https://onnxruntime.ai/docs/get-started/with-python.html#builds)).

Use two explicit dependency layers:

1. Ubuntu supplies Python/venv, CA roots, FFmpeg, desktop-opening support, and—only while the current import coupling remains—Tk.
2. A locked virtual environment supplies inference and Python audio/model helpers. The application downloads only ASR/VAD/diarization model data. It must not download Windows executables on Linux.

For the first Ubuntu implementation, install:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk ca-certificates ffmpeg xdg-utils
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
```

`python3-tk` is transitional, not architectural: `webview_backend.py` imports `app.py`, which imports Tk/CustomTkinter modules at module load. Remove it from the Ubuntu browser profile once the inference core is separated from the legacy desktop UI. Ubuntu provides the required packages directly ([python3-venv](https://packages.ubuntu.com/noble/python/python3-venv), [python3-tk](https://packages.ubuntu.com/noble/python3-tk), [FFmpeg](https://packages.ubuntu.com/noble/ffmpeg), [xdg-utils](https://packages.ubuntu.com/noble/xdg-utils)).

The browser is also a runtime prerequisite: launch must run in a graphical user session with a runnable default Firefox/Chromium-class browser. Python's `webbrowser` module searches runnable browser executables and may fail when no browser/display exists ([Python `webbrowser`](https://docs.python.org/3/library/webbrowser.html)). Do not make pywebview/GTK/WebKit a baseline dependency for the chosen browser UI.

## Recommended matrix

### Operating-system and executable layer

| Item | Browser/OpenVINO target | Why / evidence | Decision for downstream work |
|---|---|---|---|
| Ubuntu 24.04 LTS x86-64, kernel 6.8+ | Required | Officially supported by OpenVINO; the probe host was Ubuntu 24.04.4 x86-64, kernel 7.0.0-28 | Support exactly this platform first. |
| `python3` + `python3-venv` (3.12) | Required | Noble's default is Python 3.12; OpenVINO supports it | Document `python3 -m venv .venv`; do not require a third-party Python. |
| `ca-certificates` | Required | Model downloads use HTTPS | Keep system trust current and directly declare `certifi` in the venv; never depend on the downloader's certificate-verification-off fallback (`downloader.py:21-43`). |
| Graphical session + default browser | Required | Linux currently bypasses pywebview and calls `webbrowser.open()` (`app_webview.py:236-239, 308-327, 362-374`) | Add a preflight that fails clearly if no browser opens. Firefox or Chromium is sufficient; do not hard-code Edge. |
| `ffmpeg` in `PATH` | Required for the agreed feature set | Video extraction uses it, and browser recording produces WebM/Opus or MP4 that commonly needs the FFmpeg fallback (`audio_io.py:52-75`; `webview/js/app.js:1086-1106`) | Treat FFmpeg as baseline, not a hidden on-demand download. Ubuntu's package provides the transcoder and codec libraries ([Ubuntu package](https://packages.ubuntu.com/noble/ffmpeg)). |
| `xdg-utils` | Required for desktop integration | Provides Ubuntu desktop-opening utilities ([Ubuntu package](https://packages.ubuntu.com/noble/xdg-utils)); current output-folder code incorrectly uses Windows-only `os.startfile` (`webview_backend.py:700-708`) | Use `xdg-open`/portable equivalent for output folders; continue using `webbrowser` for URLs. |
| `python3-tk` | Required by current source; remove from target later | `webview_backend -> app -> customtkinter/tkinter` is an import-time dependency; Ubuntu packages Tk separately ([Ubuntu package](https://packages.ubuntu.com/noble/python3-tk)) | Keep for the first working slice, then decouple browser backend from GUI modules and drop it. |
| `libportaudio2` | Not required by browser recording | Browser recording uses `getUserMedia`/`MediaRecorder`, not `sounddevice`. Linux `sounddevice` needs separately installed PortAudio ([sounddevice installation](https://github.com/spatialaudio/python-sounddevice/blob/master/doc/installation.rst), [Ubuntu `libportaudio2`](https://packages.ubuntu.com/noble/libportaudio2)) | Put `sounddevice` + `libportaudio2` in an optional legacy-CustomTkinter profile only. |
| GTK/WebKit packages | Not required by chosen UI | pywebview on Linux needs an explicit GTK or Qt backend; its Ubuntu GTK recipe is `python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1` ([pywebview install](https://pywebview.flowrl.com/guide/installation)) | Do not install these unless a later decision adopts a native pywebview shell. The current launcher never attempts it on Linux anyway. |
| `cloudflared` in `PATH` | Optional | Cloudflare publishes Linux amd64 binaries and Debian packages ([Cloudflare downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/), [official Debian/Ubuntu instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/)) | Document external installation; disable the tunnel control with a clear explanation when absent. Do not auto-download it. |
| GCC/CMake/build tools | Not required for normal install | The selected dependencies have compatible Python 3.12 x86-64 wheels; OpenVINO says GCC/CMake are for source builds | Require binary wheels in the lock/install path; keep compilers out of end-user prerequisites. |

Browser microphone recording is valid from the loopback HTTP origin: the Secure Contexts specification treats `127.0.0.0/8` as potentially trustworthy, so the current `http://127.0.0.1:<port>` origin can use secure-context-only media APIs ([W3C Secure Contexts](https://www.w3.org/TR/secure-contexts/#is-origin-trustworthy)). User permission and a real audio input remain required; `getUserMedia()` is otherwise unavailable ([MDN `getUserMedia`](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)).

### Python virtual-environment layer

The target requirements should declare what the browser/OpenVINO runtime imports directly, then lock a known-good resolution. A compatible snapshot verified on the probe host is shown below; it is evidence for a lock, not a promise that unbounded `>=` ranges will remain reproducible.

| Distribution | Target status | Known-compatible version | Current declaration | Reason |
|---|---|---:|---|---|
| `openvino` | Required | 2026.3.0 | Direct (`>=2024.0.0`) | CPU ASR IR execution. Local `ov.Core().available_devices == ['CPU']`. |
| `onnxruntime` | Required | 1.29.0 | Direct (`>=1.17.0`) | Silero VAD and optional diarization. Local providers included `CPUExecutionProvider`. |
| `numpy` | Required | 2.5.2 | Direct (`>=1.24.0`) | Audio arrays, mel preprocessing, inference inputs. OpenVINO 2026.3 metadata constrains it to `<2.6`. |
| `opencc-python-reimplemented` | Required | 0.1.7 | Direct | Chinese conversion; the published wheel is platform-independent ([PyPI](https://pypi.org/project/opencc-python-reimplemented/)). |
| `soundfile` | Required | 0.14.0 | **Only transitive via unused `librosa`** | Every file transcription path calls it (`audio_io.py:79-105`). Linux x86-64 wheels bundle libsndfile; source installs instead need `libsndfile1` ([SoundFile install](https://pypi.org/project/soundfile/#installation)). Declare it directly. |
| `soxr` | Required/preferred | 1.1.0 | **Only transitive via unused `librosa`** | First-choice resampler (`audio_io.py:31-48`). Direct declaration avoids silently falling to lower-fidelity NumPy interpolation. |
| `scipy` | Required when diarization is supported | 1.18.1 | **Only transitive via unused `librosa`** | Hierarchical clustering in `diarize.py:350-388`; also the second-choice audio resampler. Declare directly. |
| `kaldi-native-fbank` | Required when diarization is supported | 1.22.3 | **Missing** | WeSpeaker features in `diarize.py:209-235`. PyPI supplies a CPython 3.12 manylinux x86-64 wheel ([PyPI](https://pypi.org/project/kaldi-native-fbank/)). |
| `tokenizers` | Required for recognition hints/context | 0.23.1 | **Missing** | `LightProcessor.encode_text()` imports it lazily (`processor_numpy.py:252-282`). PyPI supplies an abi3 manylinux x86-64 wheel for Python 3.10+ ([PyPI](https://pypi.org/project/tokenizers/)). |
| `certifi` | Required for reliable application-managed downloads | 2026.7.22 | **Only accidental/transitive** | All download helpers try it before system trust. Declare it directly if `librosa`/`requests` are removed. |
| `segno` | Optional, required for tunnel QR | 1.6.6 | **Missing** | `/api/qr` returns 404 without it (`cf_tunnel.py:78-86`; `webview_server.py:233-245`). Put in a tunnel extra or declare directly if QR is part of the shipped UI. |
| `customtkinter` | Transitional only | 6.0.0 | Direct | Needed solely because browser backend currently imports the legacy GUI graph. Remove from the target browser profile after decoupling. |
| `pywebview` | Not needed for chosen browser UI | 6.2.1 | Direct | Current Linux branch never calls it. Remove from the browser profile; use `pywebview[gtk]` plus GTK/WebKit only for a future native-shell profile. |
| `librosa` | Remove from browser runtime | 1.0.0 | Direct | No Python source imports it; comments explicitly say `audio_io` replaced it. Its large transitive tree currently masks missing direct declarations for `soundfile`, `soxr`, and `scipy`. |
| `sounddevice` | Legacy optional only | 0.5.6 | Direct | Used by the CustomTkinter realtime/playback code, not browser recording. On the probe host it could not import without `libportaudio2`. |
| `Pillow` | Not needed by browser UI | — | Missing | Only legacy `endpoint_tab.py` uses it to display QR PNGs. Browser QR returns bytes directly. |
| `transformers`, `soynlp` | Not target runtime requirements | — | Missing | `transformers` is an optional logging import/developer template dependency; `soynlp` is an optional Korean alignment helper. Linux forced alignment is unavailable for a separate binary reason below. |

A downstream requirements split should therefore be equivalent to:

```text
# Ubuntu browser/OpenVINO direct runtime (then lock transitives)
openvino
onnxruntime
numpy
opencc-python-reimplemented
soundfile
soxr
scipy
kaldi-native-fbank
tokenizers
certifi

# Optional tunnel/QR extra
segno

# Transitional current import coupling only
customtkinter
```

Do not copy the exact versions above into an untested permanent pin blindly. Create a lock/constraints file from this known-compatible snapshot and run the Ubuntu CI/smoke contract whenever it is refreshed.

## Model and non-Python asset reconciliation

### Required tracked application assets

| Asset | Consumer | Status |
|---|---|---|
| `webview/index.html`, `webview/css/app.css`, `webview/js/{bridge,app,i18n}.js`, favicon | Browser UI/server | Tracked and served by `webview_server.resolve_web_dir()` (`webview_server.py:37-50`). Packaging/source install must preserve the whole directory. |
| `ov_models/mel_filters.npy` | `LightProcessor` mel preprocessing | Tracked; searched at model-parent or repo `ov_models` (`processor_numpy.py:47-81`). It is not downloaded by `downloader.py`, so source/package manifests must include it. |
| root `prompt_template.json` | 0.6B processor fallback | Tracked; 0.6B downloader does not list it, but `LightProcessor` falls back to the repo root (`processor_numpy.py:201-209`). It must remain packaged. |

### Application-managed OpenVINO/VAD assets

`downloader.py` uses standard-library HTTPS and stores everything below the selected model directory.

| Feature/model | Files expected by code | Downloader/check result |
|---|---|---|
| 0.6B OpenVINO | `audio_encoder_model.{xml,bin}`, `thinker_embeddings_model.{xml,bin}`, `decoder_model.{xml,bin}`, `config.json`, `preprocessor_config.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt` | `download_all()` downloads/checks all 11 and also VAD (`downloader.py:126-147, 639-647, 749-801`). Only the three `.bin` files get SHA-256 verification; the rest are existence/LFS-pointer checks. |
| 1.7B OpenVINO KV | `audio_encoder_model.{xml,bin}`, `thinker_embeddings_model.{xml,bin}`, `decoder_prefill_kv_model.{xml,bin}`, `decoder_kv_model.{xml,bin}`, `prompt_template.json`, `config.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt`, `preprocessor_config.json`, `chat_template.json` | `download_1p7b()` downloads/checks all 15 by existence/LFS-pointer only (`downloader.py:95-117, 261-311`). No SHA-256 values are defined. |
| Silero VAD | `silero_vad_v4.onnx` at model root | Required by both model sizes (`app.py:568-580`). 0.6B `download_all()` fetches it from the Silero v4 repository, but **the 1.7B-only path neither checks nor downloads it**. A fresh user choosing 1.7B can finish the model download and then fail at load. Make VAD a shared prerequisite ensured for every OpenVINO selection. Source: [Silero VAD v4 asset](https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx). |
| Recognition hint/context | Model `vocab.json` + `merges.txt` and Python `tokenizers` | Both model manifests contain the files, but `requirements.txt` omits `tokenizers`; current hint use raises an explicit `ImportError`. |
| Speaker diarization | `diarization/segmentation-community-1.onnx`, `diarization/embedding_model.onnx`; Python `onnxruntime`, `numpy`, `scipy`, `kaldi-native-fbank` | Downloader has both model files (`downloader.py:119-124, 218-258`), but CPU requirements omit `kaldi-native-fbank` and declare `scipy` only indirectly. Download success currently does not prove the feature can run. Source: [model repository](https://huggingface.co/altunenes/speaker-diarization-community-1-onnx). |

The Hugging Face model manifests returned every filename expected by code on the research date: 11/11 in both 0.6B primary and fallback repositories, 15/15 in the 1.7B repository, and 2/2 diarization files ([0.6B primary](https://huggingface.co/dseditor/Qwen3-ASR-0.6B-INT8_ASYM-OpenVINO), [0.6B fallback](https://huggingface.co/Echo9Zulu/Qwen3-ASR-0.6B-INT8_ASYM-OpenVINO), [1.7B](https://huggingface.co/dseditor/Qwen3-ASR-1.7B-INT8_OpenVINO)). This verifies remote presence, not file content; only the 0.6B `.bin` hashes are presently pinned by the repo.

### Executable-dependent features

| Feature | Current behavior on Ubuntu | Required decision |
|---|---|---|
| Browser-recorded audio and video | `find_ffmpeg()` already checks `PATH` first (`ffmpeg_utils.py:40-48`). If missing, browser backend downloads a ZIP containing only `ffmpeg.exe`/`ffprobe.exe` and then cannot find a Linux executable (`downloader.py:383-431`). | Require Ubuntu `ffmpeg`; disable Windows download logic on Linux. This also covers WebM/Opus microphone segments, not only video files. |
| Cloudflare quick tunnel | `find_cloudflared()` checks `PATH` first, but absence triggers download of `cloudflared-windows-amd64.exe` (`cf_tunnel.py:26-75, 102-139`). | Optional external prerequisite only. If absent, show install instructions; never download the Windows asset. |
| Forced word alignment | The model downloader fetches `qwen3-focedaligner-0.6b.bin`, but the runner searches only for `chatllm/main.exe` and invokes it (`fa_aligner.py:43-56, 94-135`). The OpenVINO web path defaults to alignment, can download about 939 MB, and then falls back to proportional timing because the executable is absent (`webview_backend.py:680-694`). | Mark exact forced alignment unsupported on the Ubuntu baseline, hide/disable the option with an explanation, and do not download its model. Proportional subtitle timing remains available. A later ticket may choose a Linux-native aligner. |
| GPU/CrispASR/chatllm | Download and discovery paths are Windows `.exe`/`.dll` specific (`downloader.py:314-380`; `crisp_engine.py`; `chatllm_engine.py`). The first-run WebView settings currently seed `backend=crispasr` (`webview_backend.py:164-183`). | Outside the OpenVINO CPU baseline. Ubuntu first run must seed/select OpenVINO and not expose these backends. Existing Windows settings need a clear Ubuntu fallback without overwriting the saved Windows choice. |
| Open output folder | Uses `os.startfile`, which is Windows-only (`webview_backend.py:700-708`). | Use `xdg-open`/portable abstraction. This is a code portability fix, not a Python-package dependency. |

## Reproducible probes and observed output

All local probes used the existing `.venv`; no source files or model files were changed.

```bash
cat /etc/os-release
uname -m && uname -r
.venv/bin/python --version
```

Observed: Ubuntu 24.04.4 LTS, `x86_64`, kernel `7.0.0-28-generic`, Python `3.12.3`.

```bash
.venv/bin/python -m pip check
```

Observed: `No broken requirements found.` This is not sufficient: undeclared feature imports are invisible to `pip check`.

An import/provider probe observed:

```text
openvino 2026.3.0                         OK; available_devices=['CPU']
onnxruntime 1.29.0                        OK; providers include CPUExecutionProvider
soundfile 0.14.0 / libsndfile 1.2.2      OK; bundled _soundfile_data present
numpy 2.5.2, scipy 1.18.1, soxr 1.1.0    OK
tokenizers                                FAIL ModuleNotFoundError
kaldi_native_fbank                        FAIL ModuleNotFoundError
segno                                     FAIL ModuleNotFoundError
sounddevice                               FAIL OSError: PortAudio library not found
webbrowser.get()                          FAIL: could not locate runnable browser
ffmpeg / ffprobe                          /usr/bin/ffmpeg, /usr/bin/ffprobe
cloudflared                               absent
```

The `webbrowser` result is expected on this headless probe host (`DISPLAY` and `WAYLAND_DISPLAY` unset); it proves launcher failure needs to be surfaced, not that Ubuntu Desktop lacks a browser.

Wheel compatibility was probed without changing `.venv`:

```bash
.venv/bin/python -m pip download --only-binary=:all: --no-deps \
  'tokenizers>=0.15' 'kaldi-native-fbank>=1.19' 'segno>=1.6'
```

Resolved and temporary-imported successfully:

```text
tokenizers-0.23.1-cp310-abi3-manylinux_2_17_x86_64...
kaldi_native_fbank-1.22.3-cp312-cp312-manylinux2014_x86_64...
segno-1.6.6-py3-none-any.whl
```

Browser recording/FFmpeg fallback was probed with a generated WebM/Opus sample:

```text
soundfile-webm=direct-fail LibsndfileError: Format not recognised
audio_io-webm=ok 4000 16000 float32
```

Thus the current `audio_io` path successfully decodes browser-style WebM only because system FFmpeg is present.

Remote manifests were checked with `https://huggingface.co/api/models/<repo>` against the exact arrays in `downloader.py`; all expected filenames were present. A HEAD request to the Silero VAD URL returned HTTP 200 and `Content-Length: 1807522`. `python downloader.py --check` returned exit 1 because this worktree intentionally has no downloaded ASR/VAD model set.

## Verified conclusions vs. remaining proof

### Verified

- Ubuntu 24.04/Python 3.12/OpenVINO CPU/ONNX Runtime CPU are compatible at import/provider level and supported by their official matrices.
- The current browser entry-point imports on Ubuntu when Tk/CustomTkinter are installed, then deliberately skips native pywebview and falls back to `webbrowser`.
- `requirements.txt` is incomplete for hints and diarization and relies on the unused `librosa` dependency tree for core `soundfile`/`soxr`/`scipy` packages.
- Linux pip `sounddevice` does not supply PortAudio; this does not affect browser microphone recording.
- FFmpeg from `PATH` supports the current WebM recording fallback; both automatic executable downloaders are Windows-only.
- The 1.7B downloader does not ensure the shared VAD asset; forced alignment has no Linux runner; the first-run default is a Windows-only CrispASR backend.

### Inferred or not yet proven

- No end-to-end ASR transcription was run because the multi-gigabyte models are not present. Remote manifests—not payload hashes—were checked.
- No graphical browser, microphone permission, real audio device, output-folder opening, or Cloudflare tunnel smoke test was possible in the headless research environment.
- No clean Ubuntu VM installation or CI run was performed. The final implementation still needs the agreed clean-VM smoke suite: launch, app-managed model/VAD setup, single and batch transcription, browser recording, video, endpoint, subtitle save/open, and shutdown.
- The proposed package versions form a locally compatible snapshot, but a downstream lock-file ticket must prove a fresh resolve/install and should fail rather than compile unexpected source distributions.

## Acceptance checks this matrix enables

A downstream Ubuntu support implementation can be considered dependency-complete only when all of these pass on a clean Ubuntu 24.04 x86-64 VM:

1. The documented `apt` command and locked venv install complete without compilers.
2. A dependency probe imports every enabled direct feature package; `pip check` also passes.
3. First launch opens the default browser, selects OpenVINO CPU, and offers no Windows-only backend.
4. Selecting either 0.6B or 1.7B ensures ASR files, shared VAD, tracked mel/template assets, and verifies integrity as defined by the manifest.
5. Hint/context works (`tokenizers`), and diarization works (`scipy` + `kaldi-native-fbank`) if those controls remain enabled.
6. WAV/MP3, WebM browser recording, and a video file transcribe with `/usr/bin/ffmpeg` discovered from `PATH`.
7. Missing browser, FFmpeg, or optional `cloudflared` produces an actionable preflight error; the app never downloads or executes a Windows binary.
8. Output-folder opening uses the Ubuntu desktop mechanism; exact forced alignment is explicitly unavailable unless a Linux runner has separately been chosen and proven.
