# v2 TSF Risk Plan

This document records the engineering guardrails for the v2 TSF/IME spike. It is intentionally conservative: v1 `final_only` remains the stable product path until every TSF behavior below is proven safe.

## Summary

- TSF is optional. It must never be the only path for dictation.
- Python remains the source of truth for audio, Google STT, settings, privacy, and fallback.
- The TSF/native layer may provide composition-string behavior only after a fast compatibility handshake succeeds.
- Any IPC, focus, composition, target, or edit-scope uncertainty must fail closed into the v1 final-only path.

## Protected Apps and IPC

Named pipes created by the Python process cannot be assumed to work from every target process. Low integrity processes and AppContainer/UWP apps can block access even when a discretionary ACL appears permissive.

Required v2 behavior:

- At dictation start, Python creates a `session_id`, a per-session nonce, and a target snapshot.
- The TSF component attempts a short handshake with Python. The timeout budget is 50-150 ms.
- Handshake failure cases include `AccessDenied`, timeout, AppContainer restriction, protocol mismatch, missing nonce, or unknown target.
- On any handshake failure, mark the target `tsf_unavailable` and use overlay plus final-only text insertion.
- Do not retry aggressively inside sandboxed targets. One fast attempt per target/session is enough.
- The named pipe must use a security descriptor scoped to the current user/logon session, reject remote clients, and use a unique per-user/per-session name with a nonce.
- A low-integrity mandatory label can be tested during the spike, but it is not a compatibility guarantee. AppContainer targets remain fallback-first until proven otherwise.
- The current Python spike includes a real one-shot Named Pipe handshake server and `scripts/tsf_ipc_probe.py`; it remains disabled by default until a native TSF peer is available.

Implementation constraints:

- No `Everyone`-writable pipe for production.
- No elevated helper as a workaround for sandboxed apps.
- No blocking IPC call on a UI/TSF callback thread.
- No TSF activation by default for UWP/Store/AppContainer targets in the initial spike.
- Native `Activate` must only enqueue `StartAsync` and return. Pipe open, write, and read run on a worker thread.
- Native `Deactivate` must signal cancellation and call `CancelIoEx` where possible. It must not wait on the worker from a TSF callback.
- Native worker lifetime is tracked independently so future COM `DllCanUnloadNow` can refuse unload while workers are active.
- Native failures are silent status results. No exception may cross a TSF/COM boundary and no UI may be shown from the target process.
- Pipe messages are length-prefixed UTF-8 JSON frames with a 64 KB limit.
- Native code validates UTF-8 strictly before converting any text to UTF-16 for Windows/TSF.
- Malformed, truncated, oversized, or partial JSON frames are rejected silently.
- Composition messages must include monotonic `generation` and `seq`; stale or duplicate messages are dropped before they can update TSF state.

## Focus Loss and Composition Lifecycle

TSF composition text is temporary. Focus loss, `OnKillFocus`, target changes, and `EndComposition` must not cause text to be committed into the wrong window.

Required v2 session identity:

- `session_id`: dictation session.
- `target_id`: target process/thread/window/context snapshot.
- `composition_id`: active TSF composition.
- `generation`: monotonically increasing target/composition generation.

Required v2 behavior:

- Every STT event is processed against the current `session_id`, `target_id`, and `generation`.
- If focus is lost or composition ends, Python enters `detached_preview`.
- Interim text in `detached_preview` is displayed in the app/overlay only. It is not committed.
- Google streaming may continue. The stream is not stopped solely because focus changed.
- Late final events from an old generation are never written to the current target.
- If the user returns to the same target and generation can be re-established safely, TSF may reopen composition.
- If the user moves to a different target, the old pending text must not follow automatically.

Fail-closed rules:

- Unknown target means preview-only.
- Unknown generation means drop or preview-only.
- Ended composition means no further writes through that composition object.
- Target mismatch means no commit, no selection, and no replacement.

## Advanced Editing Scope

Advanced editing commands are limited to text the app can prove it owns. They must not search or mutate arbitrary historical text in third-party applications.

Editable scope is limited to:

- Active TSF composition text.
- Text inserted by this app in the current dictation session.
- The same verified target.
- A valid TSF range, Word range, or exact focused suffix match.

Command rules:

- `replace X with Y` is allowed only when `X` appears exactly once inside editable scope.
- `delete phrase` follows the same single-match rule.
- `select word/phrase` is available only when the backend can select a verified range inside editable scope.
- After send, a meaningful Enter, focus loss, target change, or session end, the editable scope closes.
- If a command cannot prove scope, it must be a no-op with a status message.

Prohibited behavior:

- No global document/chat search.
- No `Ctrl+A` as an editing primitive.
- No broad deletion.
- No editing of text sent in chat apps.
- No mutation after target mismatch or stale range.

## Registration and Focus Isolation

TSF/COM registration is system-visible state. A bad registration path can leave a broken text service in the Windows language bar, change the user's default input method, or inject the component into apps when VoiceType is not actively dictating.

Required v2 registration behavior:

- Normal app startup must never register, unregister, enable, activate, or set VoiceType as a default language profile.
- Registration is a separate explicit maintenance action, not part of dictation startup.
- The registration tool is dry-run by default. It may change system state only with an explicit experimental consent flag.
- The first native spike may register/unregister only the text service CLSID. Language profile registration remains blocked until uninstall/rollback is proven.
- Unregister must be symmetrical and documented next to register.
- No hidden registry writes from Python.
- No automatic `ActivateLanguageProfile`, `EnableLanguageProfileByDefault`, or `SetDefaultLanguageProfile` in v2 spike code.

Required v2 focus behavior:

- `ITfThreadMgr::Activate` is paired with `Deactivate` on the same thread.
- Any temporary `AssociateFocus` call must store the previous document manager and restore it before the scope exits.
- Native composition commands require an active session handshake and a focus snapshot:
  - `hwnd`
  - process id
  - thread id
  - target generation
- If any part of the focus snapshot changes, TSF writes stop immediately and Python falls back to preview/final-only behavior.
- The native component never assumes an old `ITfContext`, `ITfDocumentMgr`, `ITfRange`, or composition object is still valid after focus loss, deactivation, or generation change.
- Context failures are silent no-ops inside the host process. Python receives only coarse fallback status.

Implementation constraints:

- No registration during installer-less development runs.
- No language bar takeover during beta.
- No focus association that outlives the dictation session.
- No edit session request after target mismatch.
- No COM exception or UI prompt from inside the target process.

## Spike Acceptance Criteria

The first v2 implementation phase is a spike, not full TSF live typing.

The spike must prove:

- TSF/native component can load without destabilizing v1.
- IPC handshake succeeds or fails quickly.
- Fallback to v1 final-only works after handshake failure.
- Compatibility matrix is recorded for Notepad, Word, Chrome/Gmail, WhatsApp Web or Telegram Web, VS Code/Electron, and at least one UWP/Store target.
- Focus loss does not commit text to the wrong target.
- Late final events after focus loss do not duplicate committed text.
- Advanced edit commands remain limited to verified session scope.
- Register/unregister dry runs do not change Windows input settings.
- Explicit register/unregister actions are symmetrical and leave no active thread manager or focus association counters.

Promotion beyond spike requires:

- Automated protocol/session tests.
- Manual QA across the compatibility matrix.
- No regressions in v1 final-only behavior.
- No text duplication, stale composition, focus theft, or unintended deletion.

## References

- Microsoft Learn: Named Pipe Security and Access Rights.
- Microsoft Learn: CreateNamedPipeW.
- Microsoft Learn: Mandatory Integrity Control.
- Microsoft Learn: AppContainer isolation.
- Microsoft Learn: Text Services Framework.
- Microsoft Learn: TSF Compositions.
