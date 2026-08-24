# Qwen ASR Mini Tool

Qwen ASR Mini Tool is a local speech-recognition application that turns audio, video, and microphone input into subtitles without sending the media off the user's machine.

## Language

**Ubuntu source support**:
A supported source-install experience on Ubuntu 24.04 x86-64 that covers the application's CPU-compatible workflows.
_Avoid_: Linux support, Ubuntu parity

**Local app session**:
The lifetime of one running local application process and its loopback server, independent of any browser clients.
_Avoid_: Browser session, app window

**Browser client**:
A browser tab connected to a local app session.
_Avoid_: App, application window

**App readiness**:
The state in which a local app session can serve its browser UI and local API, regardless of whether an ASR model is ready.
_Avoid_: Model readiness, transcription readiness

**Model readiness**:
The state in which the selected ASR model is loaded and can accept transcription work.
_Avoid_: App readiness

**Transcription job**:
A unit of transcription work owned by the local app session and observable from any connected browser client.
_Avoid_: Browser request, tab task
