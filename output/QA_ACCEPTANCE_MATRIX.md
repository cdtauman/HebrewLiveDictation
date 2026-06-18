# QA & ACCEPTANCE MATRIX — parity release gate

This matrix defines the exact tests required **before declaring parity**. It extends the existing `docs/qa.md` and the `release_audit.py` gate; it does not replace them.

**Test types:** `U` unit · `I` integration · `M` manual · `S` security · `P` packaging.
**Pass bar:** every row marked **Gate** must pass before a parity release. Existing 10 unittest files must remain green throughout.

---

## 1. Engine — providers & abstraction

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| EN-1 | `SpeechClientBase` contract | U | ✓ | start/stop/cancel/timeout + event shape verified |
| EN-2 | Registry dispatch | U | ✓ | `stt.provider` selects correct class; unknown → clear error |
| EN-3 | Google parity (post-move) | I | ✓ | recorded Hebrew audio → identical interim/final sequence vs pre-move baseline |
| EN-4 | Local Whisper offline | I | ✓ | transcribe Hebrew fixture with **network disabled** and **no Google creds** |
| EN-5 | Deepgram streaming | I | ✓ | interim+final Hebrew via WS; invalid key → error event, no crash |
| EN-6 | Groq batch | I | ✓ | final Hebrew via REST; HTTP timeout handled |
| EN-7 | AutoFallback | I | ✓ | simulated primary outage → output continues via local; buffer bounded; UI shows "offline" |
| EN-8 | Provider switch is config-only | I | ✓ | switch Google↔local↔Deepgram↔Groq with no code change |
| EN-9 | Cancellation/timeout uniform | U | ✓ | each provider stops promptly on `cancel()`; per-op timeout fires |
| EN-10 | Hebrew quality (WER) | M/I | — | benchmark suite WER per provider/model recorded; default guidance set |

## 2. Local model management

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| MD-1 | SHA256 verify | U | ✓ | corrupt/altered download rejected |
| MD-2 | RAM preflight | U | ✓ | low-RAM → clear refusal/warning, not crash |
| MD-3 | Per-chunk timeout | U | ✓ | stuck decode aborts within timeout |
| MD-4 | Model mgmt UI | M | — | download/delete/status reflect real state; selector switches config only |

## 3. Credentials & security

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| SE-1 | Keyring round-trip | U | ✓ | set→get→delete per provider |
| SE-2 | JSON→keyring migration | U | ✓ | secret imported; JSON entry cleared **only after verified read-back** |
| SE-3 | Keyring-unavailable fallback | U | ✓ | falls back to JSON read; no crash |
| SE-4 | UI never shows secret | M | ✓ | only booleans + Test buttons; no key text in UI/state/logs |
| SE-5 | release_audit secret scan | S | ✓ | planted fake Deepgram/Groq/Google key → audit fails; clean tree passes |
| SE-6 | Log redaction | S | ✓ | transcripts not logged unless `debug_log_transcripts=true`; no credentials in logs |
| SE-7 | SCA | S | — | bandit + pip-audit/safety run; no unaddressed high severity |

## 4. Updater

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| UP-1 | Valid signed manifest | U | ✓ | accepted; version compared correctly |
| UP-2 | Tampered manifest | S | ✓ | signature mismatch → **rejected** |
| UP-3 | Unsigned / missing signature | S | ✓ | rejected |
| UP-4 | Wrong-key signature | S | ✓ | rejected |
| UP-5 | SHA256 corruption | U | ✓ | installer hash mismatch → aborts download |
| UP-6 | Kill-switch / min-version | I | ✓ | `disabled`/min-version halts update |
| UP-7 | End-to-end upgrade | M | ✓ | manual upgrade installs + relaunches; manual download fallback works |

## 5. Windows app compatibility matrix (manual)

Run each at **100% and 150% DPI**, light & dark theme, Hebrew + mixed Hebrew/English/numbers, with punctuation, delete, undo, replace — verifying **no duplication, no focus theft, correct RTL**.

| ID | Target | Type | Gate | Acceptance |
|---|---|---|---|---|
| WM-1 | Notepad | M | ✓ | text inserts correctly; SendInput path |
| WM-2 | Microsoft Word | M | ✓ | Word COM path; RTL correct; replace/undo work |
| WM-3 | Chrome / Gmail | M | ✓ | browser field insertion; no dup |
| WM-4 | WhatsApp Web | M | ✓ | message field; send command works |
| WM-5 | Telegram (Web/Desktop) | M | ✓ | insertion + send |
| WM-6 | VS Code (Electron) | M | ✓ | editor insertion; UIA/SendInput fallback |
| WM-7 | Generic Electron app | M | — | insertion via fallback chain |
| WM-8 | Search fields / address bars | M | — | short-field insertion + next-field (Tab) |
| WM-9 | Focus loss mid-session | M | ✓ | session detaches to preview-only (no stray injection) |
| WM-10 | DPI 150% overlay/toolbar | M | ✓ | overlay + floating toolbar render correctly; no focus steal |

## 6. Dictation behavior & Hebrew text

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| HB-1 | RTL stability | U/M | ✓ | Hebrew final text correct; no reversed/garbled runs (`test_hebrew_text.py`) |
| HB-2 | Mixed RTL/Latin/numbers | M | ✓ | bidi correct in target apps |
| HB-3 | Unicode integrity | U | ✓ | emoji/punctuation insert (`test_unicode_integrity.py`) |
| HB-4 | Command packs (he/en/ar/ru/fr/es) | U | ✓ `preserve` | parser matches direct + regex patterns (`test_config_and_language.py`) |
| HB-5 | Session editing | U/M | ✓ `preserve` | delete word/sentence, undo(20), clear, replace/delete phrase, send, next field, stop |
| HB-6 | Interim → final transition | I | ✓ | overlay preview then final commit; no duplication |

## 7. Hotkeys & focus

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| HK-1 | Global hotkey toggle/push-to-talk | U/M | ✓ | starts/stops from any app (`test_hotkeys.py`) |
| HK-2 | Pause/resume + pause hotkey | U/M | ✓ | pause holds capture; resume same session |
| HK-3 | Copilot key | M | — | maps as configured |
| HK-4 | Hotkey conflict handling | M | — | conflict surfaced, graceful |

## 8. Clipboard & injection backends (preserve)

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| CB-1 | Clipboard fallback path | U/M | ✓ | paste works when SendInput unsuitable (`test_text_injector.py`) |
| CB-2 | Clipboard history bypass | M | ✓ | dictated text excluded from clipboard history |
| CB-3 | Clipboard restore | M | ✓ | previous clipboard restored within delay/size limits |
| CB-4 | Backend selection per target | U | ✓ `preserve` | Word→COM, generic→SendInput, fallback chain intact |

## 9. Packaging & build

| ID | Test | Type | Gate | Acceptance |
|---|---|---|---|---|
| PK-1 | PyInstaller build | P | ✓ | `build_app.ps1` produces `dist\HebrewLiveDictation` |
| PK-2 | Installer | P | ✓ | Inno Setup installs to `%LOCALAPPDATA%`, no admin |
| PK-3 | Size budget | P | — | installer size delta from new deps measured & acceptable; models not bundled |
| PK-4 | Fresh-machine smoke | M | ✓ | launches on clean Windows; creates `%APPDATA%\VoiceType`; no missing-DLL |
| PK-5 | release_audit clean | S | ✓ | no artifacts/secrets; passes |
| PK-6 | CI test gate | P | ✓ | unittest job green; release blocked on failure |
| PK-7 | Checksums/signature | S | — | SHA256SUMS + signed manifest published; (Phase G) Authenticode |

## 10. Regression guard (Repo-2 strengths must not regress)

| ID | Test | Gate | Acceptance |
|---|---|---|---|
| RG-1 | Windows integration intact | ✓ | Word COM/UIA/target-tracking/Z-order/freshness unchanged (WM-2, CB-4) |
| RG-2 | Command packs intact | ✓ | HB-4 passes for all 6 languages |
| RG-3 | Session editing intact | ✓ | HB-5 passes |
| RG-4 | CI + release audit intact | ✓ | PK-5, PK-6 pass |
| RG-5 | Privacy logging intact | ✓ | SE-6 passes |
| RG-6 | TSF still gated | ✓ | `experimental_transport_enabled=false`; v1 fallback on handshake failure (`test_tsf_ipc.py`, `test_tsf_protocol.py`) |

---

## Parity sign-off checklist
- [ ] All **Gate ✓** rows pass.
- [ ] App runs offline with local provider (EN-4).
- [ ] Provider switching is config-only (EN-8).
- [ ] No plaintext secrets; migration verified (SE-1..SE-5).
- [ ] Updater rejects tampered/unsigned/wrong-key manifests (UP-2..UP-4).
- [ ] Windows compatibility matrix passes (WM-1..WM-10).
- [ ] No Repo-2 strength regressed (RG-1..RG-6).
- [ ] Re-run Repo-1 ↔ Repo-2 comparison: **no Repo-1 advantage missing**.
