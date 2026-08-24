# Establish the Ubuntu 24.04 prerequisite matrix

Type: research
Status: resolved
Research branch: `research/ubuntu-24-04-prerequisites`
Research asset: `.scratch/ubuntu-source-support/research/ubuntu-24-04-prerequisite-matrix.md`

## Question

Which exact Ubuntu 24.04 x86-64 system packages, Python versions and packages, OpenVINO/ONNX/audio runtime requirements, browser assumptions, model/VAD assets, and optional executable versions are required for every in-scope workflow to run from a clean checkout, according to primary sources and a reproducible local probe?

## Answer

Ubuntu 24.04 x86-64 with its Python 3.12 and OpenVINO CPU stack is a viable baseline. The supported source profile needs explicit Ubuntu packages for the virtual environment, CA roots, FFmpeg, desktop opening, and transitional Tk coupling; the browser/OpenVINO environment needs direct declarations for packages currently missing or accidentally transitive, notably `tokenizers`, `kaldi-native-fbank`, `soundfile`, `soxr`, `scipy`, `certifi`, and optional `segno`.

The application must ensure shared VAD for either OpenVINO model, select OpenVINO rather than CrispASR on Ubuntu, and never fall through to Windows FFmpeg or cloudflared downloads. Forced word alignment is not currently portable because its runner requires `main.exe`; browser mode is also still coupled to Tk through `webview_backend -> app`.

Full evidence, source links, probes, the recommended matrix, and remaining proof are captured on `research/ubuntu-24-04-prerequisites` at commit `903da95` in `.scratch/ubuntu-source-support/research/ubuntu-24-04-prerequisite-matrix.md`.
