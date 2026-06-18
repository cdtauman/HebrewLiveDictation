# RISK REGISTER — parity program

Scoring: **Likelihood** (L/M/H) × **Impact** (L/M/H). **Severity** = combined priority. Owner = role responsible.
IDs are stable for cross-reference from `EPICS_AND_ISSUES.md` and `PLAN_AUDIT.md`.

---

## A. Technical / architecture

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-A1 | Provider abstraction leaks (interim/streaming assumptions baked into controller) breaking final-only providers | M | H | High | `SpeechClientBase` declares `capabilities`; controller already supports `final_only`; EN-9 tests; batch providers validated in E3/E4 | Eng lead |
| R-A2 | Moving Google into the abstraction introduces a subtle regression | M | H | High | Phase B behavioral-parity test (EN-3) vs recorded baseline; keep legacy path until parity proven; `git revert` rollback | Eng lead |
| R-A3 | Threading model conflict (new providers use asyncio/WS vs existing QThread/queue model) | M | M | Med | providers run in daemon threads emitting via QueuedConnection like Google does; no asyncio in UI thread | Eng |
| R-A4 | Cancellation/timeout not uniform → hangs on stop | M | M | Med | base enforces cancel()+timeout; EN-9; per-provider stop tests | Eng |
| R-A5 | AutoFallback buffer grows unbounded on long utterances | M | M | Med | bounded buffer + drop policy; EN-7 asserts bound | Eng |

## B. UX

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-U1 | Floating toolbar steals focus → breaks dictation target | M | H | High | `WA_ShowWithoutActivating` + `Qt.Tool`; WM-10/E8.1 acceptance asserts focus retained | UX/Eng |
| R-U2 | UI expansion destabilizes engine if sequenced too early | L | H | Med | hard rule: UX is Phase F, after engine proven | PM |
| R-U3 | Provider choice confuses users (which to pick?) | M | M | Med | onboarding guidance + sensible default (Google); "Test" buttons | UX |
| R-U4 | "Offline switched" not obvious during AutoFallback | M | M | Med | explicit status in overlay/toolbar (EN-7) | UX |

## C. Security & credentials

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-S1 | **Updater key custody** — leaked signing key lets attacker push malicious updates | L | H | High | private key offline/CI secret with restricted access; rotation plan; kill-switch; (later) Authenticode as second factor | Sec/Release |
| R-S2 | Co-hosted manifest+installer (SHA256-only would be bypassable) | M | H | High | **signed manifest with embedded pubkey** (ADR-006); UP-2..UP-4 reject tampering | Sec |
| R-S3 | Migration deletes JSON secret before keyring write verified → user locked out | L | H | Med | non-destructive migration; delete only after verified read-back (SE-2) | Eng |
| R-S4 | Keyring unavailable in locked-down/enterprise environments | M | M | Med | fall back to JSON read; document; SE-3 | Eng |
| R-S5 | New providers' API keys leak via logs/telemetry | L | H | Med | redaction by default; SE-5/SE-6; release_audit patterns extended | Sec |
| R-S6 | Kill-switch abuse (attacker forces "disabled" to block updates / forces downgrade) | L | M | Med | min-version monotonic; signed only; no auto-downgrade | Sec |
| R-S7 | Supply-chain (new heavy deps: faster-whisper, grpc, PySide6) | M | M | Med | lockfile + SCA (E0.3/E0.4); Dependabot | Sec |

## D. Packaging / build / maintainability

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-P1 | PyInstaller size explosion from CTranslate2/Whisper | H | M | Med | **download-on-demand models**; CPU-default; measure delta (PK-3) | Release |
| R-P2 | Hidden-import / packaging breakage from new deps | M | M | Med | update `.spec` hiddenimports; PK-4 fresh-machine smoke | Release |
| R-P3 | Surface-area growth hurts maintainability (Python+PySide6+Google+Deepgram+Groq+Whisper+UIA+Word COM+TSF) | M | M | Med | clear module boundaries; feature flags; provider isolation; docs (E10.2) | Eng lead |
| R-P4 | No code-signing cert → SmartScreen friction persists | M | M | Med | acquire cert (E9.1); interim: documented warning + signed manifest | Release |
| R-P5 | Native TSF build optional in CI → inconsistent artifacts | L | M | Low | TSF stays gated/off; CI hard-stops on real failures; document optional path | Release |

## E. Cloud dependency / cost

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-C1 | Google Cloud credential friction blocks new users | H | M | Med | offline local mode (E3) removes hard dependency; better onboarding (E4.3) | PM |
| R-C2 | API cost surprises (Deepgram/Groq/Google usage) | M | M | Med | user supplies own keys; document costs; (R&D) freemium proxy later | PM |
| R-C3 | Provider outage degrades service | M | M | Med | AutoFallback to local (E5) | Eng |

## F. Local model / runtime

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-F1 | Insufficient RAM → crash on model load | M | H | Med | RAM preflight refusal/warning (MD-2) | Eng |
| R-F2 | Slow CPU inference → poor UX, perceived hang | H | M | Med | per-chunk timeout; UI "processing" state; recommend cloud default | Eng |
| R-F3 | Hebrew quality of local model below expectation | M | M | Med | benchmark/WER (E10.1) before advertising; ivrit-ai turbo option | Eng/QA |
| R-F4 | Model download fails / corrupts | M | M | Med | SHA256 verify + retry (MD-1) | Eng |

## G. Windows permissions / integration

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-W1 | UAC / elevated-target apps block injection | M | M | Med | document limitation; manifest stays standard-user; surface failure gracefully | Eng |
| R-W2 | DPI 150% layout/overlay bugs | M | M | Med | PerMonitorV2 (app.manifest); WM-10 | Eng |
| R-W3 | COM STA / Word COM instability | M | M | Med | preserve current STA init; fallback chain to SendInput; WM-2 | Eng |
| R-W4 | Focus race on injection / window switch | M | H | Med | target tracking + 30s freshness + detach-to-preview (WM-9) | Eng |

## H. TSF / IME (gated R&D)

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-T1 | TSF registration alters system input state | L | H | High | gated off by default; dry-run; symmetric register/unregister; no startup registration (`v2_tsf_risk_plan.md`) | Eng/Sec |
| R-T2 | TSF promoted prematurely → focus theft/duplication/deletion | L | H | High | promotion only via QA gate (`docs/qa.md`); fail-closed to v1 (RG-6) | QA |
| R-T3 | Silent breakage if experimental transport enabled without native peer | L | M | Low | handshake timeout → fall back to v1; ADR-008 | Eng |

## I. Process / schedule

| ID | Risk | L | I | Sev | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-I1 | Timeline optimism (full engine parity in ~90d) | H | M | Med | phase gating; P0/P1 first; UX deferrable; see PLAN_AUDIT timeline critique | PM |
| R-I2 | Single-maintainer bus factor on a broad stack | M | M | Med | docs/ADRs; agent-executable prompts; modular boundaries | PM |
| R-I3 | Regression of Repo-2 strengths during refactor | M | H | High | regression guard suite (RG-1..RG-6) on every PR | QA |

---

## Top risks to watch (heatmap)
1. **R-S1 / R-S2** updater key custody + manifest integrity — security-critical.
2. **R-A1 / R-A2** abstraction correctness + zero-regression Google move — blocks everything.
3. **R-U1** toolbar focus theft — would break the core value prop.
4. **R-I3** regressing Repo-2's Windows/editing lead — defeats the "superset" goal.
5. **R-P1 / R-F2** local-model size + CPU latency — manage expectations via download-on-demand + cloud default.
