# VoiceType TSF Hello Peer

This is the native v2 spike component for the TSF/IME path. It is not a full text service yet. Its only job is to prove that a native component can perform a safe hello handshake with the Python Named Pipe server.

## Safety Contract

- No blocking pipe work runs on a TSF/UI callback thread.
- `StartAsync` copies the handshake data and returns immediately after starting a worker thread.
- `Deactivate` only signals cancellation and cancels pending I/O. It does not wait for the worker to finish.
- Worker state is owned by `shared_ptr`, so the worker can finish safely after the owner object is destroyed.
- All Win32 failures are converted into internal status codes. No exception crosses the API boundary.
- The host app must remain unaffected. Failure means Python falls back to v1 final-only.
- Pipe payloads are length-prefixed UTF-8 JSON frames. Native code validates UTF-8 before converting text to UTF-16.
- Broken, oversized, malformed, or partial frames are rejected silently.
- Future composition messages must carry monotonic `generation` and `seq`; stale messages are dropped before they can touch TSF state.
- TSF text changes are single-flight: only one `RequestEditSession` may be active at a time, interim updates are coalesced to the latest message, and commit/cancel messages take priority.
- Interim text display attributes are applied only to the active composition range through `GUID_PROP_ATTRIBUTE`; hosts that reject or ignore the attribute fall back to their default rendering.
- Caret movement is performed only inside the granted edit cookie, and only against a verified TSF range owned by the active composition.
- TSF registration is never performed by normal app startup. Registration is a separate explicit tool action, dry-run by default, and unregister is symmetrical.
- Thread manager activation and focus association are scoped RAII objects. Every successful `Activate` is paired with `Deactivate`, and every `AssociateFocus` restores the previous document manager.

## Wire Protocol

Each pipe message is:

```text
uint32 little-endian payload_length
UTF-8 JSON payload
```

The current maximum payload is 64 KB. Text fields are decoded from UTF-8 to UTF-16 with strict Windows conversion flags. Invalid bytes are treated as protocol failure, never as replacement characters.

Future composition messages may include:

```json
{
  "type": "update_composition",
  "session_id": "...",
  "generation": 3,
  "seq": 42,
  "text": "שלום עולם",
  "selection_start_utf16": 9,
  "selection_end_utf16": 9
}
```

The native peer treats `selection_*_utf16` as UTF-16 code-unit offsets after strict decoding. Invalid ranges are a no-op.

## Build

Use a Visual Studio Developer PowerShell:

```powershell
cmake -S native\tsf_hello_peer -B native\tsf_hello_peer\build -G "Visual Studio 17 2022" -A x64
cmake --build native\tsf_hello_peer\build --config Release
```

Or use the local helper:

```powershell
powershell -ExecutionPolicy Bypass -File native\tsf_hello_peer\build_local.ps1 -Configuration Release -RunRegistrationDryRun
```

## Manual Probe

First run the Python probe in native-peer mode once the executable exists:

```powershell
python scripts\tsf_ipc_probe.py --native-peer native\tsf_hello_peer\build\Release\VoiceTypeTsfHelloPeer.exe
```

The executable also accepts explicit arguments:

```powershell
VoiceTypeTsfHelloPeer.exe --pipe \\.\pipe\VoiceType-Probe-123 --session 123 --nonce abc --timeout-ms 150
```

## Experimental Registration Guard

Registration is intentionally isolated from the normal application path. The command below is a dry run and must not change Windows language settings:

```powershell
VoiceTypeTsfHelloPeer.exe --register-tsf
VoiceTypeTsfHelloPeer.exe --unregister-tsf
```

The only command allowed to change TSF registration state requires both explicit switches:

```powershell
VoiceTypeTsfHelloPeer.exe --register-tsf --commit-registration --i-understand-experimental-tsf-registration
VoiceTypeTsfHelloPeer.exe --unregister-tsf --commit-registration --i-understand-experimental-tsf-registration
```

The same explicit action is available from the build helper:

```powershell
powershell -ExecutionPolicy Bypass -File native\tsf_hello_peer\build_local.ps1 -CommitExperimentalRegistration
powershell -ExecutionPolicy Bypass -File native\tsf_hello_peer\build_local.ps1 -CommitExperimentalRegistration -Unregister
```

The spike currently registers/unregisters only the TSF text service CLSID. Language profile registration is deliberately not implemented yet, so this tool cannot silently make VoiceType the default keyboard or take over the Windows language bar.

## TSF Integration Note

The future COM/TSF text service should call `StartAsync` from `Activate` and `Deactivate` from `Deactivate`. It must not perform direct pipe I/O on TSF callbacks.

Composition work must be scheduled with `ITfContext::RequestEditSession(TF_ES_ASYNC | TF_ES_READWRITE)`. The helper classes in `voice_type_tsf_composition.*` are intentionally conservative:

- `CompositionCommandQueue` drops stale generations/sequences, coalesces rapid interim updates, and serializes edit sessions.
- `CallbackEditSession` contains only a small callback bridge so real text work stays inside `DoEditSession`.
- `ApplyInterimDisplayAttribute` and `SetSelectionToRangeEnd` require a valid `TfEditCookie`; they should never be called from the pipe worker directly.
- `ScopedThreadMgrActivation`, `ScopedFocusAssociation`, and `FocusIsolationGate` prevent context work after focus, window, process, thread, or generation mismatch.
