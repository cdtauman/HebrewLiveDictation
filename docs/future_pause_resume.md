# Pause/resume implementation note

Phase 10 implements session-preserving pause/resume for the WinUI sidecar path
and keeps the legacy Qt wiring aligned with the shared controller contract.

## What ships now

- Config key: `hotkeys.pause_hotkey` (optional; exposed in the Controls room).
- `DictationController` has a `paused` state between `listening` and `stopping`.
- Pause stops the current `AudioStream` and STT provider stream without returning
  to idle, without flushing history, and without resetting the injector session.
- Resume opens a fresh audio/STT stream under the same dictation session.
- Late events from the pre-pause stream are stamped with their old generation and
  ignored.
- Stop from paused flushes the accumulated final text once and returns to idle.
- HUD, Remote, Home, tray, and shell footer render a distinct paused state.
- The pause hotkey is guarded so it cannot share the same key combo as the main
  start/stop hotkey.

## Proof in this phase

- Controller tests cover pause/resume preserving session id and accumulated text,
  ignoring old stream events, and stopping from paused.
- Sidecar callback tests cover pause not flushing history and keeping the hotkey
  listener in the active-session state.
- Hotkey tests cover the independent pause key and same-combo guard.
- WinUI runtime self-test covers HUD paused-state rendering and word preservation.

## Manual proof still required later

The final app matrix still needs a real Windows manual run across Notepad, Word,
browser fields, and chat apps to confirm target continuity, no duplicate final
insertion, no focus stealing, and no wrong-window insertion across pause/resume.
