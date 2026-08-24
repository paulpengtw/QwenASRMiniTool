# Choose the Ubuntu browser lifecycle contract

Type: prototype
Status: resolved
Prototype branch: `prototype/ubuntu-browser-lifecycle`
Prototype asset: `webview/ubuntu-browser-lifecycle.prototype.html`
Prototype commit: `5815c95`

## Question

What should Ubuntu users experience from launch through shutdown when the browser UI is the official application surface, including readiness, browser opening, server lifetime, explicit exit, browser-close behaviour, relaunch, and startup or shutdown failures?

## Answer

The **local app session** is owned by one local process and its loopback server; browser tabs are disposable **browser clients**. **App readiness** begins when the local UI/API responds and is independent from **model readiness**.

- Launch waits for app readiness before opening a browser. If automatic opening fails, keep serving, print the local URL, and show `Ctrl+C` instructions.
- Closing the last browser client does not stop the local app session or non-recording transcription jobs. Relaunch reuses a healthy session; stale ownership is safely replaced and starts a fresh session.
- Reconnecting clients recover the local app session's canonical model, job, result, endpoint, and tunnel snapshot. That snapshot lasts for the app session; only durable settings, model assets, and saved outputs survive process restart.
- Live microphone capture is the exception: closing its browser client stops capture, warns where possible, and retains already-transcribed segments for reconnection.
- Any loopback browser client may cancel work or choose **Quit local app**. Destructive actions identify affected work and require confirmation, defaulting to continued work.
- Startup failure opens no browser, reports an actionable terminal error, and exits non-zero. Model or download failure stays inside the ready UI. Unexpected server loss shows a disconnected state, retries health checks, and eventually gives relaunch instructions; it never silently enters mock mode.
- Shutdown stops new work, notifies clients, cancels authorized work, stops tunnel and LAN services, completes durable writes, stops the loopback server, and exits within ten seconds. A second `Ctrl+C` forces termination.
- UI quit exits `0`; `Ctrl+C` exits `130`; `SIGTERM` exits `143`; startup and runtime failures exit non-zero. Before intentional disconnect, clients show **Local app stopped** and instructions to close or relaunch from the terminal.

The accepted state-machine prototype is captured on `prototype/ubuntu-browser-lifecycle` at commit `5815c95` in `webview/ubuntu-browser-lifecycle.prototype.html`.
