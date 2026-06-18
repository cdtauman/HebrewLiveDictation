# PLAN_AUDIT.md — a brutal self-attack on this plan

Purpose: attack the plan before it spends budget. Each finding has a **severity** (Critical / High / Medium / Low) and a **required change or mitigation**. Cross-refs use `R-*` (RISK_REGISTER) and `E*` (EPICS).

---

## 1. Unsupported assumptions

| # | Assumption | Why it's risky | Required change |
|---|---|---|---|
| A-1 | "`SpeechClient` Protocol means the abstraction is basically free." | The Protocol only covers `start/stop/restart_stream`. It says nothing about **interim vs final**, **cancellation**, **timeout**, or **error taxonomy** — exactly where batch/streaming providers diverge. (High) | `SpeechClientBase` must define cancellation, timeout, and an error taxonomy (terminal vs retryable) explicitly; EN-9. Don't treat E1 as trivial. |
| A-2 | "Google move is zero-regression." | `google_stt_v2_stream.py` has location/model fallback, restart-on-error, 285s cap, phrase boost, interim merging — subtle behavior easy to break in a move. (High) | EN-3 must use a **recorded-audio behavioral fixture**, not just unit mocks. Keep legacy path until parity proven (R-A2). |
| A-3 | "faster-whisper gives good Hebrew." | Unverified. Hebrew quality is model- and accent-dependent; large-v3 may underperform on noisy mic input vs Chirp 3. (High) | Treat as **hypothesis**; gate any "local parity" claim on E10.1 WER results (R-F3). Do not advertise local Hebrew quality until measured. |
| A-4 | "Deepgram/Groq Hebrew quality ≈ Repo 1's claims." | Repo 1's superiority claim is anecdotal; Groq turbo Hebrew may be weak. (Medium) | Benchmark before defaulting; keep Google default (ADR-002). |
| A-5 | "Audio-feedback tones are missing in Repo 2." | Marked 'confirm at impl' — not verified by reading audio code. (Low) | Confirm during E8.3; if present, downgrade gap #8 to "verify/expose volume". |
| A-6 | "Repo 1 has no CI" is a permanent Repo-2 lead. | Repo 1 could add CI any time; parity is a moving target. (Low) | Frame Repo-2 CI as a lead to **maintain**, not bank. |
| A-7 | "keyring works on all target machines." | Enterprise/locked-down Windows may block Credential Manager. (Medium) | Mandatory JSON-read fallback (SE-3, R-S4); never hard-fail. |

## 2. Missing or insufficient tests

| # | Gap | Severity | Required change |
|---|---|---|---|
| T-1 | No **behavioral-parity fixture** for the Google move. | High | Add recorded-audio → event-sequence golden test (EN-3). |
| T-2 | No test that **provider switch is truly config-only** (no hidden code coupling). | High | EN-8 integration test across all four providers. |
| T-3 | AutoFallback **buffer-bound** and **drop-policy** untested. | Medium | EN-7 asserts max buffer + correct utterance replay. |
| T-4 | Updater negative tests (tampered/unsigned/wrong-key/kill-switch) not in current suite. | High | UP-2..UP-6 as security unit tests. |
| T-5 | No **automated** Windows-injection regression — matrix is fully manual. | High | E9.3 pyautogui/uiautomation smoke for at least Notepad+Chrome+DPI; rest manual. |
| T-6 | RTL DOCX export correctness untested. | Medium | Assert bidi/RTL run direction in exported docx (E8.2). |
| T-7 | No coverage measurement → unknown blind spots across 22 modules. | Medium | Add coverage (E9.3); set a floor for new modules. |
| T-8 | Migration **idempotency** + partial-failure untested. | Medium | SE-2 must cover re-run and interrupted migration. |

## 3. Over-compressed timelines

| # | Issue | Severity | Required change |
|---|---|---|---|
| TL-1 | "Full engine parity in ~90 days" assumes one stream of work with no integration drag. Local Whisper packaging + 3 new providers + fallback is realistically more. (High) | High | Treat day-windows as **nominal**; gate by phase completion, not calendar. P0/P1 first; UX (Phase F) is explicitly deferrable. (R-I1) |
| TL-2 | Phase 0 (keyring + updater + SCA + crash handling + smoke matrix) is a lot to call "parallel" with single maintainer. | Medium | Allow Phase 0 to overlap A but accept it may extend; updater can split (foundation now, polish in F). |
| TL-3 | Code-signing cert acquisition (E9.1) has external lead time (vendor validation). | Medium | Start procurement early (during Phase 0) even though work lands in G. |

## 4. Packaging risks

| # | Issue | Severity | Required change |
|---|---|---|---|
| PK-A | CTranslate2 + grpc + PySide6 in one PyInstaller bundle → size + hidden-import fragility. | High | Download-on-demand models (never bundle); measure delta (PK-3); update `.spec` hiddenimports; fresh-machine smoke (PK-4). (R-P1/R-P2) |
| PK-B | Onedir vs onefile + antivirus false positives on unsigned bundle. | Medium | Keep onedir; pursue signing (E9.1); document AV exceptions. |
| PK-C | Optional native TSF build makes release artifacts non-deterministic. | Low | TSF off/gated; CI hard-stop on real failures; document. (R-P5) |
| PK-D | New transitive deps may pull GPL/incompatible licenses. | Medium | License scan in SCA; verify faster-whisper/CTranslate2/provider SDK licenses. |

## 5. Windows-specific risks

| # | Issue | Severity | Required change |
|---|---|---|---|
| W-A | Floating toolbar focus theft would **break the product**. | Critical | `WA_ShowWithoutActivating`; explicit focus-retention assertion (WM-10/E8.1). (R-U1) |
| W-B | UAC-elevated targets can't receive injected input. | Medium | Document; graceful failure; do not request elevation. (R-W1) |
| W-C | COM STA + Word COM under new threading (provider threads) could deadlock. | Medium | Keep STA init; providers in their own daemon threads; no COM calls off the injection path. (R-W3) |
| W-D | DPI 150% regressions in new widgets. | Medium | Test new toolbar/model/history UI at 150% (WM-10). |

## 6. Provider-abstraction flaws

| # | Issue | Severity | Required change |
|---|---|---|---|
| AB-1 | Streaming vs batch vs interim mismatch could force ugly special-casing in the controller. | High | Capability flags + base normalization; controller branches on `capabilities.interim`, not provider name. |
| AB-2 | Error taxonomy: what counts as "terminal" (trigger fallback) vs "retryable" is undefined. | High | Define an error enum in `base.py`; map each provider's failures to it; drives E5. |
| AB-3 | Audio format assumptions (16kHz LINEAR16) may not suit every provider/SDK. | Medium | Centralize format negotiation in base; resample once (already in `audio_stream.py`). |
| AB-4 | Hidden Google-specific assumptions in `dictation_controller.py` (e.g., interim merge, restart). | High | Audit controller for Google-isms during E2; move provider-specific logic into providers. |

## 7. Security & credential risks

| # | Issue | Severity | Required change |
|---|---|---|---|
| S-A | Signing-key leak = malicious-update vector. | Critical | Key offline/CI-secret, least access, rotation plan, kill-switch; later Authenticode as second factor. (R-S1/R-S2) |
| S-B | Migration could strand a user's only credential. | High | Non-destructive; delete only after verified read-back (SE-2). (R-S3) |
| S-C | New providers' keys could leak in error messages/logs. | Medium | Redact in all error paths; extend release_audit patterns (SE-5). (R-S5) |
| S-D | Google SA-JSON in keyring is large/awkward; some keyring backends limit value size. | Medium | Prefer ADC where possible; if storing JSON, test backend size limits; document. |

## 8. Update-mechanism risks

| # | Issue | Severity | Required change |
|---|---|---|---|
| U-A | Manifest + installer co-hosted → integrity must come from signature, not hash. | Critical | Embedded-pubkey signature mandatory (ADR-006); SHA256 is corruption-only. |
| U-B | Kill-switch could be abused to block updates or force downgrade. | Medium | Monotonic min-version; signed-only; no auto-downgrade. (R-S6) |
| U-C | Updater that auto-runs installer could be hijacked to run arbitrary exe. | High | Only launch the verified, signed installer from the verified URL; never an arbitrary path. |
| U-D | Public-key rotation has no story. | Medium | Support 2 valid keys during rotation; document procedure. |

## 9. Places a Repo-2 strength could regress (highest stakes)

| # | Strength at risk | How it could regress | Guard |
|---|---|---|---|
| RG-A | Windows integration (Word COM/UIA/target-tracking) | Refactor decouples engine but accidentally reroutes injection or changes threading/STA | RG-1; keep `text_injector.py`/`editing_backend.py` untouched in engine phases; WM-2/CB-4 |
| RG-B | Command packs (6 languages) | Provider/UI changes touch `language_packs.py` or controller parsing order | RG-2; HB-4 across all languages |
| RG-C | Session editing (undo-20, replace/delete) | New history/export or fallback alters session text state | RG-3; HB-5 |
| RG-D | CI test gate + release_audit | Adding signing/SCA breaks or weakens the existing gate | RG-4; PK-5/PK-6 stay required |
| RG-E | Privacy-by-default logging | New providers/updater log payloads or keys | RG-5; SE-6 |
| RG-F | TSF stays gated | A provider/config refactor flips the experimental flag or changes fail-closed behavior | RG-6; ADR-008; `test_tsf_ipc.py` |

## 10. Strategic critiques

- **SC-1 (Medium):** "Parity with Repo 1" is a moving target; Repo 1 could ship the freemium proxy or add CI. Frame success as *the documented current Repo-1 advantages*, re-checked at sign-off, not a perpetual guarantee.
- **SC-2 (Medium):** Chasing full multi-provider parity expands maintenance for a single maintainer. Mitigate with strict module boundaries, agent-executable prompts, and the option to ship local+Google first (P1) and defer Deepgram/Groq if capacity is tight — without abandoning the parity goal.
- **SC-3 (Low):** The plan adds breadth (4 engines) that may dilute the product's identity (Windows-integrated Hebrew dictation). Keep Google default + Windows depth as the headline; treat extra engines as resilience/choice, not the pitch.

---

## Net assessment
The plan is **sound and the sequencing is correct** (engine before UX, non-destructive migrations, signed manifest, gated TSF). The **highest-risk items are not features but correctness/security**: the zero-regression Google move (A-2/T-1), the abstraction's error/capability contract (AB-1/AB-2), updater key custody (S-A/U-A/U-C), and not regressing Repo-2's Windows/editing lead (RG-A..RG-F). Every one of these has a concrete guard above and a corresponding gate in `QA_ACCEPTANCE_MATRIX.md`. **Timelines should be treated as nominal and gated by phase completion, not calendar.**
