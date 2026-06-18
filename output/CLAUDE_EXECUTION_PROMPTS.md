# CLAUDE CODE EXECUTION PROMPTS — phase by phase

A sequence of self-contained prompts to paste into Claude Code, one per phase. Run them **in order**. Each prompt assumes the working directory is the Repo-2 root (`cdtauman/HebrewLiveDictation`) and that the previous phase merged green.

**Shared rules (restated in each prompt):** Python/PySide6 only; never merge the Tauri repo; keep TSF gated and fail-closed; do not regress Repo-2 strengths; no plaintext secrets; ship behind a feature flag; keep `python -m unittest discover -s tests` (PYTHONPATH=src) and CI green; provide a rollback note per PR.

---

## Prompt 0 — Phase 0: maturity foundation (keyring, updater, crash handling, SCA)

```
Implement Phase 0 of the parity plan in output/MASTER_PARITY_PLAN.md. No UI expansion.

1. Add src/hebrew_live_dictation/secrets_store.py over the `keyring` library (service "HebrewLiveDictation"): get/set/delete/has for providers deepgram, groq, and Google (SA-JSON contents or ADC marker). If keyring is unavailable, fall back to reading settings.json. Implement a NON-DESTRUCTIVE migration: on load, import any plaintext secret from settings.json into keyring and delete it from JSON ONLY after a verified keyring read-back. Add a migration toggle.
2. Add src/hebrew_live_dictation/updater.py: fetch GitHub releases latest.json + its signature, VERIFY an Ed25519/minisign signature over the manifest using a public key embedded in the app BEFORE trusting it; SHA256 only checks installer corruption. Compare versions (packaging), download the Inno installer, prompt, relaunch. Honor a signed kill-switch/min-version. Keep manual download possible. Add config keys updater.{enabled,check_on_start,channel} and embed a placeholder public key.
3. Add global crash handling (sys.excepthook + Qt message handler) writing to the existing redacted log; show a non-leaking error dialog.
4. Add SECURITY.md. Add a dependency lockfile. Extend .github/workflows/build-release.yml with bandit -r src/ and pip-audit. Add a CI release step that signs latest.json (private key from a CI secret).
5. Extend scripts/release_audit.py with Deepgram/Groq API-key regex patterns.

Tests: keyring round-trip; migration (import + JSON cleared only after verified read-back + re-run idempotency + interrupted migration); updater rejects tampered/unsigned/wrong-key manifests and honors kill-switch; SHA256 mismatch aborts. Update config.py schema version + migration. Confirm all existing tests + CI pass. Provide rollback notes (disable update-check flag; migration is non-destructive).
```

---

## Prompt A — Phase A: provider abstraction only (no behavior change)

```
Implement Phase A. Create the STT provider abstraction WITHOUT changing behavior.

1. Create package src/hebrew_live_dictation/stt/.
2. stt/base.py: SpeechClientBase implementing interfaces.SpeechClient with uniform start/stop/restart_stream/cancel, a per-operation timeout, a capabilities object {streaming, batch, interim, offline, fallback_target}, and an error taxonomy enum {terminal, retryable}. It emits STTEvent via on_event_callback exactly as today.
3. stt/registry.py: ProviderRegistry mapping name -> (factory, capabilities). Register "google_v2" pointing at the EXISTING google_stt_v2_stream.py class (wrap, do not move yet).
4. Update stt_factory.create_stt_stream to dispatch on config["stt.provider"] (default "google_v2"); keep the legacy import path available. Add config keys stt.provider (default google_v2) and stt.mode (default api) with migration.

Acceptance: with default config the behavior is byte-identical to today; tests/test_google_stt_v2_stream.py and all others stay green; registry returns the Google provider for "google_v2" and raises a clear error for unknown names. Rollback: remove the registry import to restore the direct factory; tag the pre-change commit.
```

---

## Prompt B — Phase B: move Google into the abstraction, prove zero regression

```
Implement Phase B. Relocate Google into the abstraction and PROVE zero regression.

1. Move google_stt_v2_stream.py to stt/google_v2.py and make it subclass SpeechClientBase. Audit dictation_controller.py for any Google-specific assumptions (interim merge, restart-on-error, 285s cap, phrase boost) and move provider-specific logic into the provider, keeping the controller provider-agnostic (branch on capabilities.interim, not provider name).
2. Add a behavioral-parity integration test: feed a recorded Hebrew audio fixture and assert the interim/final event sequence is IDENTICAL to a baseline captured before the move.
3. Only after parity passes, remove the legacy direct-factory path.

Acceptance: behavioral-parity test passes; all existing tests + CI green; provider switch is config-only (add a smoke test instantiating each registered provider). Rollback: git revert the move commit restores the legacy path.
```

---

## Prompt C — Phase C: local offline Whisper + model management

```
Implement Phase C. Add offline local STT via faster-whisper.

1. src/hebrew_live_dictation/models.py: a model registry {name -> url, sha256, approx_ram_mb, size_mb}; download-on-demand (NEVER bundle); SHA256 verification (reject mismatch); RAM preflight via psutil (refuse/warn, never crash); storage under %APPDATA%\VoiceType\models; delete/status APIs.
2. stt/whisper_local.py: a faster-whisper provider. Buffer audio between speech endpoints; per-chunk timeout; emit FINAL ONLY; capabilities {offline:True, interim:False, streaming:False, batch:True, fallback_target:True}. Register as "whisper_local".
3. Add a model-management settings page (download/delete/status, active-model selector, RAM warning).

Acceptance: transcribe a Hebrew fixture with the NETWORK DISABLED and NO Google credentials; corrupt download rejected; low-RAM path gives a clear refusal, not a crash; cancellation stops promptly. Add config providers.whisper.{enabled,model,device}. Rollback: providers.whisper.enabled=false → cloud-only build unaffected; models not bundled so installer size unchanged.
```

---

## Prompt D — Phase D: API→local AutoFallback

```
Implement Phase D. Add resilience fallback.

1. stt/fallback.py: FallbackSpeechClient(primary, local) selected by config stt.mode in {api, local, auto_fallback}. Maintain a BOUNDED audio buffer with a drop policy. On a TERMINAL primary error (use the base error taxonomy: auth/network/timeout/quota), emit status "falling_back" and replay the buffered utterance to the local provider. Surface the offline switch in the overlay/toolbar.

Acceptance: with a simulated primary outage, output continues via local; the buffer stays bounded (assert the cap); UI shows the offline state. Default stt.mode stays conservative until validated. Rollback: stt.mode=api disables fallback.
```

---

## Prompt E — Phase E: Deepgram + Groq + provider UI

```
Implement Phase E. Add cloud multi-provider support.

1. stt/deepgram.py: Deepgram Nova-3 via WebSocket streaming (interim+final) plus REST batch. Map failures to the base error taxonomy (invalid key = terminal). capabilities {streaming:True, interim:True}.
2. stt/groq.py: Groq Whisper Turbo via REST batch, final-only. capabilities {streaming:False, interim:False, batch:True}.
3. Keys come from secrets_store. Add provider-selection UI with cards (Google / Local / Deepgram / Groq) and a "Test key/credentials" button that pings the provider and NEVER displays the secret.

Acceptance: Deepgram streams Hebrew interim+final; invalid key → clean error event (no crash); Groq returns final Hebrew with timeout handling; switching provider is config-only. Add config providers.deepgram.* and providers.groq.*. Rollback: remove a provider from the registry/UI list; Google default untouched.
```

---

## Prompt F — Phase F: UX parity (only after engine is stable)

```
Implement Phase F. Add the UX parity features. Do NOT start until the engine phases are merged and green.

1. Floating toolbar + idle button: a PySide6 frameless, always-on-top widget that MUST NOT steal focus — set Qt.WA_ShowWithoutActivating and flags Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint. Draggable; persist position in config toolbar.position. Two modes: recording bar (level meter, pause, stop) and idle circle (click to start). Keep it mutually exclusive with the main window.
2. history.py + export.py: persist finalized sessions (timestamp, target app, text) under %APPDATA%; export TXT and RTL-correct DOCX via python-docx (set paragraph bidi + RTL run direction). Add a history view with an export button.
3. Audio-feedback tones via QSoundEffect, gated by audio.feedback_enabled + audio.feedback_volume.
4. Pause/resume in the controller state machine (hold capture without finalizing; resume continues the same session) + an optional pause hotkey in hotkeys.py.

Acceptance: dictation continues while the toolbar is visible (focus NOT stolen) — assert this; toolbar position persists; idle click starts; exported DOCX opens RTL-correct in Word; tones play only when enabled; pause holds and resume continues. Verify at 100% and 150% DPI. Rollback: each feature behind its config flag.
```

---

## Prompt G — Phase G: signing, checksums, benchmark, gated R&D

```
Implement Phase G. Hardening + R&D (gated).

1. Add Authenticode code signing in CI (signtool, cert from a secret); the updater additionally verifies the installer's Authenticode signature. Publish SHA256SUMS + the signed manifest.
2. Add a Python WER benchmark harness (mirroring the Tauri repo's benchmark/): compare Google/Deepgram/Groq/whisper models on Hebrew samples; output a table + default-model recommendation.
3. Add automated GUI smoke (pyautogui/uiautomation) for Notepad + Chrome injection at 100%/150% DPI; add coverage reporting with a floor for new modules.
4. R&D (do not ship): execute the docs/qa.md TSF promotion gate while keeping experimental_transport_enabled=false and fail-closed; write the freemium-proxy design doc (no build).

Acceptance: installer signed; updater verifies signature; benchmark produces per-provider WER; GUI smoke runs; coverage published; TSF still gated and v1 fallback intact; freemium remains a design doc. Rollback: signing is CI-side only — unsigned build still functions.
```

---

## After each phase
- Run the full suite + the relevant `QA_ACCEPTANCE_MATRIX.md` gate rows.
- Confirm the regression guards (RG-1..RG-6) still pass.
- If anything risks regressing a Repo-2 strength, stop and report rather than forcing the change.
- At program end, re-run the Repo-1 ↔ Repo-2 comparison and confirm no Repo-1 advantage remains missing.
