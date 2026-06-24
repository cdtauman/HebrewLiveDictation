# VoiceType WinUI — Manual Beta Test Checklist (R3/R4)

One-page tester script for the **fresh CI artifact only** (not a local `dist/` build). Record each
result honestly: **PASS / FAIL / SKIP** — a blank or a guess is not a result. On any FAIL, capture the
logs (see *Sending logs* at the bottom) and note the exact step + what you saw.

- **Gate level:** **G** = gates public beta (must PASS). **I** = informative (record, not blocking).
- **Supported dictation paths** (the only ones that gate): focus the target app → start/stop with **F8**
  or the **floating Remote** → final transcript inserted once. Home/Tray start are secondary (record only).
- **Artifact under test:** `VoiceType-winui-beta-unsigned` from GitHub Actions run ____________ (sha ________).
- **Release status:** this artifact is an unsigned manual-test artifact. It is **not** release approval,
  public-beta approval, or proof that Google R3 passed on this machine.
- **Google status terms:** **connection verified** means credentials/project/recognizer checked. **Dictation
  proven** means the exact runtime model/location/language/recognizer produced non-empty text in a real
  streaming session. Do not mark one as the other.

---

## 0. Setup
- [ ] Download + unzip the CI artifact to a clean folder; run `VoiceType.exe`.
- [ ] First run: complete (or Skip) onboarding. Confirm Skip leaves the **Offline (Whisper)** engine
      **selected** (not an unconfigured cloud engine). On a clean machine the offline model is **not**
      installed yet, so the app must say **"download a model"** and report **not ready** — it must
      **not** claim offline is already working. Install the model (Engine room) to make offline ready.
- [ ] Engine room shows the engine choice; Offline model status is honest (installed ✓ / needs download).

## 1. Core offline — **G**
- [ ] Install/confirm the **small** offline model (Engine room → model status "מותקן ✓").
- [ ] **Notepad + F8:** focus Notepad → F8 → speak Hebrew → F8 → final text lands **once**, correct, RTL.
- [ ] **Notepad + Remote:** repeat using the floating Remote start/stop. Same result.
- [ ] **Medium model:** Engine room → select **medium** → download → ready → dictate into Notepad.
      Quality/accuracy is acceptable; final lands once.
- [ ] History room shows each dictation, text matches what landed.
- [ ] Nothing was ever typed into VoiceType itself / File Explorer / the wrong window.

## 1b. Pause / resume — **G**
- [ ] Controls room: set a pause/resume hotkey different from the main start/stop hotkey.
- [ ] Focus Notepad → start dictation → speak Hebrew → pause → confirm target stays empty and HUD/Remote show Paused.
- [ ] Resume → continue speaking → Stop → final text lands **once** as one session.
- [ ] History shows one matching entry, not one entry before pause and another after resume.
- [ ] Press the main start/stop hotkey while paused → session ends safely with no duplicate insertion.

## 2. Google / STT V2 — **G only after probe PASS; otherwise experimental**
- [ ] Engine room → choose **Google (ענן)** → enter Project ID → pick **Service Account (JSON)** → Browse the key.
- [ ] **Test connection passes** → status says **connection verified**. Do **not** mark dictation verified from this alone.
- [ ] **Probe PASS:** run `tools/google_stt_probe.py` with a known Hebrew WAV. At least one exact
      model/location/language/recognizer combo returns a non-empty transcript.
- [ ] **Known protected combo:** if testing the current R3-proven path, use
      `latest_long / eu / iw-IL / _`. Any different combo is a new proof target, not inherited proof.
- [ ] **Runtime truth:** Engine active-config line and engine log show the same model/location/language/recognizer
      that passed the probe.
- [ ] **Real Google dictation:** focus Notepad → F8 → speak Hebrew → final text lands once (cloud quality).
- [ ] **Custom recognizer valid:** set a real `recognizer_id` → Test connection passes.
- [ ] **Custom recognizer invalid:** set a bogus `recognizer_id` → Test connection **fails with a clear message**.
- [ ] **Change after verify:** after a passing test, change the **model/language** (or swap the JSON) → status returns to
      **"לא נבדק"** / not-verified (R1), and dictation routes to **Offline** until re-tested.
- [ ] **ADC path** (if you use gcloud ADC): select ADC → Test connection → dictate.
- [ ] **Runtime failure:** (e.g. revoke network) dictation routes to Offline with a clear status, no crash.

## 2a. Deepgram live streaming cloud — **I unless user key + transcript proof are supplied**
- [ ] Engine room → **ספק ענן אחר** → **Deepgram** → select a model (e.g. `nova-3`).
- [ ] **Key saved:** paste a Deepgram API key → Save. The UI never displays the saved value; it
      confirms the key is stored (Windows Credential Manager), not the secret itself.
- [ ] **Connection verified:** Test connection passes → status says **connection verified** for the
      selected model/language. This is **not** transcript proof.
- [ ] **Invalid key fails clearly:** save a bogus key → Test connection **fails with a clear message**
      (no raw key/token shown anywhere).
- [ ] **Real transcript proof (only with a real user key):** focus Notepad → start → speak Hebrew →
      final text lands once. Do **not** mark Deepgram PASS without this real-key transcript.
- [ ] **Live/interim words:** during a Deepgram session interim words appear in the **HUD** and the
      **Remote** as you speak (Deepgram is streaming). Interim words are **never typed into the target** —
      only the final is inserted, once.
- [ ] **No live target typing:** interim/live words are display-only; nothing is typed into the target
      unless the (locked) Labs live-typing mode is explicitly enabled.
- [ ] **Change after verify:** change the Deepgram model/language/key → verification returns to
      needs-test and dictation routes to Offline until re-tested.

## 2b. Groq final-only cloud — **I unless user key + transcript proof are supplied**
- [ ] Engine room → choose **Provider / Groq** → select `whisper-large-v3` or `whisper-large-v3-turbo`.
- [ ] Save the Groq API key; the UI never displays the saved value.
- [ ] **Test connection passes** → status says connection verified for the selected model/language. This is not transcript proof.
- [ ] Focus Notepad → start/stop dictation → final text lands once after stop or segment flush.
- [ ] HUD/Remote live words are **SKIP** for Groq because Groq is final-only in this app.
- [ ] Change Groq model/language/key → verification returns to needs-test and dictation routes to Offline until re-tested.

## 2c. Smart Auto / offline backup — **I until full provider proof**
- [ ] Engine room → choose **Smart Auto**. Routing text shows the effective provider, start gate, and backup readiness.
- [ ] With an installed Offline model, Smart Auto reports backup ready when it selects a cloud provider.
- [ ] Without an installed Offline model, AutoFallback/Smart Auto says backup is not ready; it must not imply offline rescue is available.
- [ ] If Smart Auto selects an unverified cloud provider, status says it will route to Offline rather than pretending cloud is ready.

## 3. Full P5 app matrix — **G**  (each via F8 **and** Remote)
- [ ] **Word** (COM): Hebrew lands correctly, RTL, once.
- [ ] **Chrome / Gmail** (UIA): lands in the compose box, correct.
- [ ] **WhatsApp / Telegram desktop:** lands in the message box, correct.
- [ ] **VS Code:** lands at the cursor, correct.
- [ ] **Target changed mid-dictation:** switch apps while listening → text does **not** land in the wrong app
      (or is handled with a clear "target changed" state).
- [ ] **No self-target:** dictation never types into VoiceType's own windows/HUD/Remote.
- [ ] **No double insert:** the final appears exactly once.
- [ ] **No focus steal:** starting/stopping never pulls focus away from the target app.
- [ ] **RTL + punctuation:** Hebrew punctuation, "נקודה"/"פסיק", new line / new paragraph behave correctly.
- [ ] **Idle Remote:** enable the minimized quick-start button -> hide VoiceType to tray -> start from the Remote.
      Focus remains in the target app and the Remote hides/shows according to its settings.

## 4. Model manager — **I**
- [ ] Select medium → download → ready → dictate → delete → status returns to "not installed".
- [ ] Cancel/interrupt a download (close mid-download) → next launch shows missing/incomplete, offers retry, and never claims ready.
- [ ] Click download again while a model is already downloading → no duplicate download is queued; the UI stays in the active download state.

## 5. Live / interim words (Gboard pillar) — **G only for a probe-proven live-capable model**
- [ ] During a **Google** session with a live-capable model, interim words appear in the **HUD** and the **Remote** as you speak.
- [ ] If the selected/proven model is final-only, the UI says final-only and this interim-words step is **SKIP**, not PASS.
- [ ] Interim words are **never typed into the target app** — only the final is inserted, once.

## 6. DOCX export — **G**
- [ ] History room → Export → **.docx** → save → **open in Word** → Hebrew RTL + content acceptable.
- [ ] Export → **.txt** → opens as UTF-8 Hebrew.

## 7. Diagnostics — **I**
- [ ] Settings → Diagnostics shows engine state, config path, **engine log** + **shell log** paths.
- [ ] "Copy diagnostics" produces a redacted block (home dir shown as `~`, no secrets).

## Audio / VAD advanced — **I**
- [ ] Controls room -> change frame length -> start a new dictation session -> engine log shows matching `target_block_size`.
- [ ] Toggle cloud speech events / auto-stop -> Google sessions still require manual proof; no silent stop is counted as pass unless intended.
- [ ] Enable local VAD -> adjust threshold/padding/silence -> Offline dictation still starts, no crash, no hidden sample-rate change.
- [ ] Disable local VAD -> dependent VAD controls become inactive and dictation returns to full-audio streaming.
- [ ] Enable start/stop sounds -> set volume -> start/stop dictation -> hear one start tone and one stop tone; pause/resume does not add extra tones.

---

## Sending logs (on any FAIL)
1. Settings → Diagnostics → **Copy diagnostics** (gives the log paths).
2. Collect: the **engine log** (`hebrew_live_dictation.log` in the config dir) and the **shell log**
   (path shown in Diagnostics).
3. Note: the exact step number above, what you expected, what actually happened, the target app + its version.
4. If the app crashed: include any crash dump from the config dir.

> Reminder: this is an **unsigned** beta — Windows SmartScreen may warn on first launch ("More info → Run anyway").
> Record only what you actually observed. No result is better faked than honest.
