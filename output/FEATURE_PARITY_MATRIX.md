# FEATURE PARITY MATRIX
## Every Repo-1 advantage and its status in Repo 2

**Legend — Status:** ✅ Have · 🟡 Partial/weaker · ❌ Missing · ➕ Repo-2 lead (Repo 1 lacks it)
**Legend — Class:** `PARITY` (must-have parity with Repo 1) · `BEYOND` (nice-to-have beyond Repo 1) · `R&D` (gated track) · `LEAD` (preserve Repo-2 advantage)
**Pri:** P0 (foundational) · P1 (core parity) · P2 (important) · P3 (polish)
**Evidence:** Repo 1 = `../hebrew-dictation-main`; Repo 2 = repo root. Paths are relative to each repo.

---

## A. Dictation engine, providers, local mode, fallback

| # | Capability | Repo 1 evidence | Repo 2 status | Repo 2 evidence | Class | Python equivalent | Pri | Risk | Cmplx |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Multi-provider abstraction | `src-tauri/src/settings.rs` (`ApiProvider`, `TranscriptionMode`); `lib.rs::transcribe` | 🟡 Google hardcoded, but seam exists | `stt_factory.py` (hardcoded), `interfaces.py` (`SpeechClient` Protocol) | PARITY | `stt/` package + `ProviderRegistry`; dispatch on `stt.provider` | P0 | Med | Med |
| 2 | Offline local STT | `src-tauri/src/whisper.rs` (whisper-rs); `model.rs` (download) | ❌ none | no Whisper/faster-whisper anywhere | PARITY | `faster-whisper` provider behind `SpeechClient` | P1 | Med | High |
| 3 | API→local AutoFallback | `lib.rs` `TranscriptionMode::AutoFallback` | ❌ only Google-internal location/model fallback | `google_stt_v2_stream.py` `_switch_to_fallback` | PARITY | `FallbackSpeechClient` (primary→local on error) | P1 | Med | Med |
| — | Streaming STT | `streaming.rs` (Deepgram WS) | ✅ Google V2 bidi streaming | `google_stt_v2_stream.py` | PARITY (met) | keep + extend to Deepgram | — | — | — |
| — | Interim results / live preview | `lib.rs` `transcription-interim` event | ✅ interim → overlay | `dictation_controller.py`, overlay in `qt_app.py` | PARITY (met) | keep | — | — | — |
| — | Hebrew/RTL transcription | `App.tsx` `dir="rtl"`, lang `he` | ✅ iw-IL, Chirp 3, RTL utils | `hebrew_text.py`, `i18n.py`, `language_packs.py` | LEAD/parity | validate via benchmark | — | — | — |
| 12 | Benchmark / WER suite | `benchmark/run_benchmark.py` | ❌ none | — | PARITY | Python WER harness (provider/model compare) | P3 | Low | Low |

## B. Credentials & security

| # | Capability | Repo 1 evidence | Repo 2 status | Repo 2 evidence | Class | Python equivalent | Pri | Risk | Cmplx |
|---|---|---|---|---|---|---|---|---|---|
| 4 | OS keyring credential storage | `src-tauri/src/secure_keys.rs` (`keyring` crate); keys `#[serde(skip)]` | ❌ plaintext SA-JSON path in settings / ADC | `config.py`, `settings.example.json` `google.credentials_path` | PARITY | Python `keyring` + non-destructive JSON→keyring migration | P0 | Low | Med |
| — | Secret never in frontend/state | `settings.rs` returns booleans only | 🟡 path visible in settings UI | `qt_app.py` Google page | PARITY | expose booleans + "test" buttons only | P1 | Low | Low |
| — | Credential migration | `settings.rs::load_settings` migration | ✅ schema migration exists (config) but not for secrets | `config.py` migrations v2→v4 | PARITY | extend migration to secrets | P1 | Low | Low |
| B1 | SECURITY.md / disclosure policy | ❌ (Repo 1 also lacks) | ❌ none | — | BEYOND | add `SECURITY.md` | P2 | Low | Low |
| B2 | Dependency pinning + lockfile | `package-lock.json`, `Cargo.lock` | ❌ `>=` only | `requirements.txt`, `pyproject.toml` | BEYOND | lockfile (pip-tools/uv) | P2 | Med | Low |
| B3 | SCA in CI (SAST/deps) | ❌ (no CI) | ❌ none | — | BEYOND | bandit + safety + Dependabot | P2 | Low | Low |
| — | Privacy-by-default logging | README privacy section | ➕ transcript redaction default | `app_logging.py`, `docs/architecture.md` | LEAD | preserve | — | — | — |

## C. Updater & packaging

| # | Capability | Repo 1 evidence | Repo 2 status | Repo 2 evidence | Class | Python equivalent | Pri | Risk | Cmplx |
|---|---|---|---|---|---|---|---|---|---|
| 5 | Signed auto-updater | `tauri.conf.json` `plugins.updater` (minisign + `latest.json`); `createUpdaterArtifacts` | ❌ none | installer only | PARITY | `updater.py` + signed manifest (embedded pubkey) | P1 | Med | Med |
| C1 | Installer | NSIS (Hebrew, currentUser, offline WebView) | ✅ Inno Setup (EN+HE, lowest priv, x64) | `setup_script.iss` | PARITY (met) | keep Inno | — | — | — |
| C2 | DPI / manifest hygiene | Tauri default | ✅ PerMonitorV2 | `app.manifest` | LEAD/parity | keep | — | — | — |
| C3 | CI/CD pipeline | ❌ none (manual) | ➕ GitHub Actions, gated tests, release audit | `.github/workflows/build-release.yml`, `scripts/release_audit.py` | LEAD | preserve + extend (signing, checksums) | — | — | — |
| C4 | Code signing (Authenticode) | ❌ (unsigned) | ❌ (unsigned, intentional beta) | `release_notes.md` | BEYOND | acquire cert + `signtool` in CI | P2 | Med | Med |
| C5 | Release checksums/signatures | ❌ | ❌ | — | BEYOND | publish SHA256 + signed manifest | P2 | Low | Low |
| — | Autostart with Windows | `tauri-plugin-autostart` `--minimized` | ✅ `start_with_windows` setting | `qt_app.py`, `config.py` | PARITY (met) | verify `--minimized` behavior | P3 | Low | Low |

## D. UX / UI

| # | Capability | Repo 1 evidence | Repo 2 status | Repo 2 evidence | Class | Python equivalent | Pri | Risk | Cmplx |
|---|---|---|---|---|---|---|---|---|---|
| 6 | Floating toolbar + idle button | `lib.rs` toolbar window (220×76) + idle circle (56×56); `tauri.conf.json` toolbar window | 🟡 non-interactive overlay only; tray | `qt_app.py` `DictationOverlay` | PARITY | PySide6 frameless draggable toolbar + idle circle, no-focus-steal | P2 | Low | Med |
| 7 | History + TXT/DOCX export | `src-tauri/src/export.rs` (`docx-rs`) | ❌ session-only, no persistence | `text_injector.py` session text | PARITY | `history.py` store + `export.py` (`python-docx`) | P2 | Low | Med |
| 8 | Audio-feedback tones + volume | `settings.rs` `audio_feedback_enabled`, `audio_volume` | ❌ none (confirm at impl) | — | PARITY | `QSoundEffect` start/stop + volume setting | P3 | Low | Low |
| 9 | Pause/resume mid-recording | `lib.rs` `pause_recording`/`resume_recording`, pause hotkey | 🟡 toggle / push-to-talk only | `hotkeys.py`, `dictation_controller.py` | PARITY | pause/resume state + optional pause hotkey | P2 | Low | Low |
| 11 | Onboarding: provider selection + key test | `App.tsx` 4-step wizard, inline `test_api_key` | 🟡 Google-centric onboarding dialog | `qt_app.py` onboarding | PARITY | provider cards + "test key/credentials" buttons | P2 | Low | Med |
| — | System tray | `tauri.conf.json` trayIcon | ✅ tray w/ menu | `qt_app.py` `_configure_tray` | PARITY (met) | keep | — | — | — |
| — | Global hotkey (works anywhere) | `tauri-plugin-global-shortcut` (Alt+D) | ✅ low-level hook, Copilot key | `hotkeys.py` | PARITY (met) | keep | — | — | — |
| — | Light/dark theme + RTL UI | `App.css` (light) | ➕ light+dark, RTL/LTR auto | `qt_app.py`, `i18n.py` | LEAD | preserve | — | — | — |

## E. Local model management (tied to #2)

| # | Capability | Repo 1 evidence | Repo 2 status | Class | Python equivalent | Pri | Risk | Cmplx |
|---|---|---|---|---|---|---|---|---|
| 10 | Model download + SHA256 verify | `model.rs` (`sha2`) | ❌ none | PARITY | `models.py` download + hash | P2 | Med | Med |
| 10a | RAM preflight before load | `model.rs` via `sysinfo` | ❌ none | PARITY | `psutil` RAM check + graceful degrade | P2 | Med | Low |
| 10b | Per-transcription timeout | `whisper.rs` `TRANSCRIBE_TIMEOUT_SECS=180` | ❌ n/a | PARITY | per-chunk timeout in local provider | P2 | Low | Low |
| 10c | Model management UI (download/delete/status) | `lib.rs` model commands + `App.tsx` | ❌ none | PARITY | model-management settings page | P2 | Low | Med |

## F. Windows integration (Repo-2 LEAD — preserve)

| # | Capability | Repo 2 evidence | Repo 1 status | Class | Action |
|---|---|---|---|---|---|
| L1 | Word COM editor | `editing_backend.py` `WordCOMEditor` | ❌ (enigo only) | LEAD | preserve; add to QA matrix |
| L2 | UI Automation editor | `editing_backend.py` `UIAutomationEditor` | ❌ | LEAD | preserve |
| L3 | Unicode SendInput + abort-on-keypress | `text_injector.py` `_type_unicode_text` | 🟡 (`enigo.text`) | LEAD | preserve |
| L4 | Clipboard paste + history bypass + restore | `text_injector.py` `copy_without_history` | 🟡 (arboard, unused) | LEAD | preserve |
| L5 | Target tracking (HWND/process/profile/Z-order/30s freshness) | `editing_backend.py` `WindowTarget` | ❌ | LEAD | preserve |
| L6 | Backend selection per target profile | `text_injector.py` profile map | ❌ | LEAD | preserve; keep decoupled from engine |

## G. Editing & commands (Repo-2 LEAD — preserve)

| # | Capability | Repo 2 evidence | Repo 1 status | Class | Action |
|---|---|---|---|---|---|
| L7 | Command packs he/en/ar/ru/fr/es | `language_packs.py` `PACKS` | ❌ | LEAD | preserve |
| L8 | Voice-command parser (direct + regex patterns) | `language_packs.py` `parse_voice_command` | ❌ | LEAD | preserve |
| L9 | Session editing: delete word/sentence, undo(20), clear, replace/delete phrase, send, next field, stop | `text_injector.py`, `dictation_controller.py` | 🟡 (history only) | LEAD | preserve |
| L10 | Punctuation/emoji by voice | `language_packs.py` | ❌ | LEAD | preserve |

## H. R&D track (gated — do not default)

| # | Capability | Repo 2 evidence | Repo 1 status | Class | Action |
|---|---|---|---|---|---|
| R1 | TSF/IME native composition | `native/tsf_hello_peer/`, `tsf_bridge.py`, `tsf_ipc.py`, `tsf_protocol.py` | ❌ | R&D / LEAD | keep gated (`experimental_transport_enabled=false`); promote only via QA gate |
| R2 | Freemium token-broker proxy | — (Repo 1 has undeployed `cloudflare-worker/`) | 🟡 present, not shipped | R&D | design doc only (per decision) |

---

## Summary counts

- **Must-have PARITY gaps:** 12 numbered items (#1–#12) + a handful of sub-items (credential frontend redaction, model sub-features).
- **BEYOND (production maturity):** SECURITY.md, lockfile, SCA, code signing, checksums (5 themes).
- **R&D (gated):** TSF/IME, freemium proxy (2).
- **LEAD (preserve, do not regress):** Windows integration (6), editing/commands (4), CI/audit, privacy logging, theming, schema-versioned config (≈13 distinct strengths).

**Net:** Repo 2 must *gain* the engine/credentials/updater/UX items above, and *keep* its substantial Windows-integration and editing lead. The result is a superset: a system with Repo 1's maturity **and** Repo 2's Windows depth.
