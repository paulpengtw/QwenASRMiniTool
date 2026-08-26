# Define the workflow compatibility contract

Type: grilling
Status: resolved
Blocked by: 02, 03, 04, 08, 09, 11

## Question

For single-file transcription, batch transcription, microphone recording, subtitle editing and saving, video conversion, LAN/OpenAI-compatible endpoints, and optional Cloudflare tunnelling, what exact Ubuntu behaviour, prerequisite handling, degraded mode, and error state counts as supported?

## Answer

**Supported means: works on a machine meeting the documented prerequisite matrix.** A missing optional prerequisite does not withdraw the support claim — it produces ticket 03's defined degraded state, visible and disabled with a remedy, which is itself part of what is being supported. Video conversion and microphone recording are therefore supported workflows that degrade cleanly when FFmpeg is absent, rather than unsupported ones.

Against that definition, the Ubuntu contract is:

- **Single-file transcription** — supported. OpenVINO CPU, 0.6B by default, 1.7B by explicit choice.
- **Batch transcription** — supported; one registry job with per-item states (ticket 09).
- **Microphone recording** — supported. `getUserMedia` is available because the Secure Contexts specification treats `127.0.0.1` as potentially trustworthy; WebM/Opus segments need FFmpeg, so recording degrades without it.
- **Subtitle editing and saving** — supported; edits are server-owned and saving writes a durable file (ticket 09).
- **Video conversion** — supported; degrades without FFmpeg.
- **LAN / OpenAI-compatible endpoint** — supported, on the terms below.
- **Cloudflare tunnelling** — supported-optional. `cloudflared` is discovered on `PATH`; when absent the control is disabled with install instructions and never triggers the Windows binary download. Cloudflare ships Linux amd64 packages, so the auto-download was the only genuinely non-portable part.
- **Exact forced word alignment** — unsupported; proportional timing is shown honestly (ticket 08).

**The LAN endpoint keeps binding `0.0.0.0`** as it does today (`api_server.py:134`), identically on both platforms. It is already doubly opt-in: the user starts it explicitly, and every request carries the auto-generated Bearer token. What Ubuntu lacks is the Windows firewall prompt, whose real function is telling the user that something just became reachable from the network. The UI takes over that role: starting the endpoint displays the reachable LAN URL and states plainly that other machines on the network can reach it. Consent by disclosure, since Ubuntu will not show a dialog.

Every degraded state in this contract renders from the backend capability snapshot (ticket 03) as a code plus parameters rather than prose (ticket 04).
