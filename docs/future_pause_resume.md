# Future development note — full pause/resume (session-preserving)

## What ships today (Option 2, implemented)

A **pause/resume hotkey** with simple toggle semantics:
- Config key `hotkeys.pause_hotkey` (optional; set via the Hotkeys settings page).
- When pressed during dictation it **finalizes and stops** the current session;
  when pressed while idle it **starts a fresh session**.
- Implemented additively in `HotkeyListener` (a second guarded key-combo that
  no-ops when unset) wired to `DictationController.toggle_listening` via
  `AppBridge.pause_requested`. No change to the controller's threading/state
  machine. Unit-tested in `tests/test_hotkeys.py`.

This gives users a dedicated key to halt/resume without mid-session continuity.

## Deferred (Option 1) — true pause/resume that keeps the session

Goal: pressing pause **suspends** capture without ending the session, and resume
**continues the same session** (same target, accumulated text, undo history,
injector session scope), matching the most capable repo-1 behavior.

Why it was deferred: it is the highest-risk change in the program because it
touches the controller's **async audio/STT lifecycle** and would need careful
verification that can only be done by running the app.

Sketch of the required work:
1. **Controller state machine** — add a `paused` state between `listening` and
   `stopping` in `DictationController`:
   - `pause()`: stop the `AudioStream` + STT stream **without** the teardown that
     returns to `idle`; keep `self.session_id`, `self.accumulated_final_text`,
     `self.latest_interim_text`, and the `TextInjector` session (do **not** call
     `injector.reset_session()`).
   - `resume()`: re-create the `AudioStream` + STT stream (a new provider stream
     under the **same** session id) and return to `listening`.
   - Guard the existing teardown thread + `stop_completed` signal so a pause does
     not race a stop.
2. **Provider contract** — confirm each provider restarts cleanly mid-session
   (Google/Deepgram open a fresh stream; whisper/groq reset their segmenter).
   The `SpeechClientBase.cancel()` seam already exists for prompt suspension.
3. **Window/target continuity** — on resume, re-validate the tracked target
   (HWND/process, 30 s freshness in `editing_backend.WindowTarget`); if the
   target changed, fall back to preview-only rather than injecting into a new
   window.
4. **Hotkey** — reuse `hotkeys.pause_hotkey`, but route it to `pause()`/`resume()`
   based on controller state instead of `toggle_listening`.
5. **UI** — distinct "Paused" status in the overlay / floating toolbar.
6. **Tests** — controller-level pause→resume keeps session id + accumulated text;
   resume after target change goes preview-only; no duplicate finals across the
   pause boundary.

Acceptance: a manual matrix run (Notepad/Word/Chrome) confirming no text loss,
no duplication, and no focus/target regressions across pause→resume.
