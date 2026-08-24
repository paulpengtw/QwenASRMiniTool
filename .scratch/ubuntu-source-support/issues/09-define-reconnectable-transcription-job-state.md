# Define reconnectable transcription job state

Type: prototype
Status: open
Assignee: claude (session e1c183a8)
Blocked by: 02

## Question

Which server-owned state machine and data contract should represent single-file, batch, and recording transcription jobs so every trusted browser client can recover progress, editable results, errors, and session-lifetime history—while respecting that live microphone capture ends with its capturing client and only durable files survive process restart?
