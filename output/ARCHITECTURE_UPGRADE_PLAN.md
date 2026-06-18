# ARCHITECTURE UPGRADE PLAN — Repo 2 (`cdtauman/HebrewLiveDictation`)

**Principle:** evolve the existing Python/PySide6 architecture in place. Reuse the seams that already exist (`interfaces.py` Protocols, `config.py` schema migration, `text_injector.py` backend selection). **Do not** introduce a second runtime or port Rust.

---

## 1. Current architecture (as built)

```
main.py
  → DPI/COM init → %APPDATA%\VoiceType → QtDictationApp (qt_app.py)

qt_app.py (PySide6 UI, tray, overlay, settings, signals/slots)
  ├── hotkeys.py (low-level Windows hook)
  ├── dictation_controller.py (orchestration, state machine, Qt signals)
  │     ├── audio_stream.py (sounddevice) + vad.py
  │     ├── stt_factory.py → google_stt_v2_stream.py   ← HARDCODED PROVIDER
  │     ├── language_packs.py (command packs + parser)
  │     └── text_injector.py (commit) ── editing_backend.py (Word COM/UIA/target)
  │             └── tsf_bridge.py → tsf_ipc.py/tsf_protocol.py → native/tsf_hello_peer (gated)
  ├── config.py (schema-versioned settings, %APPDATA%)
  ├── i18n.py / hebrew_text.py / text_diff.py
  └── app_logging.py (redacted)

interfaces.py: SpeechClient, AudioSource, TextCommitter, CompositionCommitter, CommandParser (Protocols)
```

**Key insight:** the `SpeechClient` Protocol in [interfaces.py](../src/hebrew_live_dictation/interfaces.py) (`start(audio_queue)`, `stop()`, `restart_stream()`) is the seam for multi-provider work. `GoogleSTTV2Stream` already satisfies it; we add siblings.

---

## 2. Target architecture (after upgrade)

```
stt/                          ← NEW package
  ├── base.py                 SpeechClientBase: uniform start/stop/cancel/timeout, event emit, queue contract
  ├── google_v2.py            (moved from google_stt_v2_stream.py) DEFAULT
  ├── whisper_local.py        faster-whisper provider (offline; batch/near-RT)
  ├── deepgram.py             Deepgram Nova-3 (WebSocket streaming + REST batch)
  ├── groq.py                 Groq Whisper Turbo (REST batch)
  ├── fallback.py             FallbackSpeechClient (primary → local) for stt.mode=auto_fallback
  └── registry.py             ProviderRegistry: name → factory; capability metadata

stt_factory.py                dispatch on config["stt.provider"]; wrap with fallback if stt.mode=auto_fallback

secrets_store.py              ← NEW keyring wrapper (per-provider entries) + JSON→keyring migration
models.py                     ← NEW local-model download/SHA256/RAM-preflight/registry
updater.py                    ← NEW signed-manifest GitHub-releases updater
history.py                    ← NEW transcription history store (%APPDATA%)
export.py                     ← NEW TXT/DOCX export (python-docx, RTL)

qt_app.py                     + provider selection UI, model-mgmt page, history view, toolbar/idle widgets,
                              pause/resume controls, audio-feedback, key/credential test buttons
config.py                     + schema bump + migration for new keys
```

Engine and injection remain **decoupled**: providers produce `STTEvent`s; `text_injector.py`/`editing_backend.py` consume final/interim text exactly as today. No provider knows about Word COM/UIA/TSF.

---

## 3. Provider abstraction (gap #1)

### 3.1 `SpeechClientBase` contract
A shared base that normalizes the differences in the capability matrix:

```python
class SpeechClientBase:
    capabilities: ProviderCapabilities  # streaming, batch, interim, offline, ...
    def start(self, audio_queue) -> None: ...
    def stop(self) -> None: ...
    def restart_stream(self) -> None: ...
    def cancel(self) -> None: ...            # uniform cancellation
    # emits STTEvent via on_event_callback: interim/final/speech_start/speech_end/error/status
```

- **Streaming providers** (Google, Deepgram): consume the audio queue continuously, emit interim+final.
- **Batch/final-only providers** (Groq, faster-whisper): buffer audio between speech_start/speech_end (or endpointing), emit **final only**; `capabilities.interim=False`. The controller already tolerates final-only (it is the default `live_typing_mode=final_only`).
- **Uniform timeout/cancel:** base enforces a per-operation timeout and a `cancel()` that the controller calls on stop/hotkey.

### 3.2 `ProviderRegistry`
```python
REGISTRY = {
  "google_v2": (GoogleV2Stream, CAP_GOOGLE),
  "whisper_local": (WhisperLocalStream, CAP_WHISPER),
  "deepgram": (DeepgramStream, CAP_DEEPGRAM),
  "groq": (GroqStream, CAP_GROQ),
}
```
`stt_factory.create_stt_stream(config, cb)` reads `config["stt.provider"]` (default `google_v2`), constructs the provider, and — if `config["stt.mode"]=="auto_fallback"` — wraps it in `FallbackSpeechClient(primary, WhisperLocalStream)`.

### 3.3 Phasing (critical)
- **Phase A:** create `stt/`, `base.py`, `registry.py`; **wrap the existing Google class unchanged** as `google_v2`. Behavior identical; new code path feature-flagged (`stt.provider` defaults to google; old `stt_factory` import kept).
- **Phase B:** move `google_stt_v2_stream.py` into `stt/google_v2.py`, make it subclass `SpeechClientBase`. **Behavioral-parity tests** (same audio → same events) must pass; existing `tests/test_google_stt_v2_stream.py` must stay green. Only then delete the legacy path.

---

## 4. Local Whisper provider (gaps #2, #10)

- **Library:** `faster-whisper` (CTranslate2). ADR-003.
- **Models:** large-v3 / ivrit-ai turbo (Hebrew-tuned). **Download-on-demand**, never bundled (keeps installer small; rollback-safe).
- **`models.py`:**
  - registry of `{name → url, sha256, approx_ram_mb, size_mb}`;
  - download with progress + **SHA256 verification** (reject on mismatch);
  - **RAM preflight** via `psutil.virtual_memory()` before load; refuse/warn if insufficient;
  - storage `%APPDATA%\VoiceType\models\`; delete/status APIs.
- **`stt/whisper_local.py`:** buffers audio between endpoints, runs transcription with a per-chunk timeout, emits final events. `capabilities = {offline:True, interim:False, streaming:False, fallback_target:True}`.
- **UI:** model-management settings page (download/delete/status, RAM warning, active-model selector).
- **Packaging note:** CTranslate2 wheels add weight; measure PyInstaller delta; CPU build default, optional CUDA documented but not bundled.

---

## 5. AutoFallback (gap #3)

- **`stt/fallback.py` `FallbackSpeechClient(primary, fallback)`:**
  - routes audio to `primary`; on a terminal error event (auth/network/timeout/quota) emits `status: falling_back` and replays the buffered utterance to `fallback` (local Whisper);
  - bounded buffer with a drop policy (avoid unbounded memory); telemetry counters (local only).
- **Config:** `stt.mode = api | local | auto_fallback`. Default stays conservative (`api` with current provider) until validated, then `auto_fallback` can become default.
- **Mirrors** Repo 1's `lib.rs` `TranscriptionMode::AutoFallback` (try API, fall back to local, concatenate error context).

---

## 6. Credentials & keyring (gap #4)

- **`secrets_store.py`** over Python `keyring` (service `"HebrewLiveDictation"`):
  - entries: `deepgram`, `groq` (API keys); Google: store **service-account JSON contents** in keyring **or** keep ADC (no secret stored). Owner picks per-install.
  - API: `get(provider)`, `set(provider, secret)`, `delete(provider)`, `has(provider)`.
- **Migration (non-destructive):** on load, if `google.credentials_path` or any inline secret is found in `settings.json`, offer to import into keyring; **do not delete the JSON entry until a verified keyring read-back succeeds**; expose a migration toggle + banner. Fall back to JSON read if keyring is unavailable (locked-down environments).
- **UI:** settings show **booleans + "Test" buttons** only (never the secret). "Test key" calls a lightweight provider ping; "Test credentials" validates Google ADC/SA.
- **Audit:** extend [scripts/release_audit.py](../scripts/release_audit.py) to assert no plaintext API keys/SA-JSON in tree and (optionally) warn if `settings.json` in `%APPDATA%` still holds secrets post-migration.

---

## 7. Settings & migration

- Bump schema version in [config.py](../src/hebrew_live_dictation/config.py); add a migration step (reuse existing v2→v4 pattern).
- **New keys:**
  - `stt.provider` (default `google_v2`), `stt.mode` (default `api`);
  - `providers.deepgram.*`, `providers.groq.*`, `providers.whisper.{enabled,model,device}`;
  - `models.*` (active model, storage path);
  - `updater.{enabled,check_on_start,channel}`;
  - `audio.feedback_{enabled,volume}`;
  - `toolbar.{enabled,position,idle_button}`;
  - `history.{enabled,retention,path}`.
- Keep all existing keys and defaults intact (no regression to `dictation.*`, `tsf.*`, `speech.*`).

---

## 8. Signed-manifest updater (gap #5, ADR-006)

**Threat model:** `latest.json` *and* the installer live in the same GitHub release. An attacker who tampers with the release controls both the file and any hash inside it. SHA256-in-manifest is therefore **not** an integrity root — it only catches accidental corruption.

**Design:**
1. CI generates `latest.json` `{version, notes, url, sha256}` and **signs it** with an Ed25519/minisign private key (CI secret / offline). Publishes `latest.json` + `latest.json.sig`.
2. The app **embeds the public key** at build time.
3. `updater.py` flow: fetch manifest + signature → **verify signature with embedded pubkey** (reject if invalid/missing/wrong-key) → compare versions (`packaging.version`) → download installer → SHA256 corruption check → prompt user → launch Inno installer → relaunch.
4. **Kill-switch:** a `disabled: true` / minimum-version field in the signed manifest lets us halt a bad rollout.
5. **Authenticode (Phase G):** when an OV/EV cert exists, sign the installer; updater additionally verifies the Authenticode signature. Independent of manifest signing.
6. Manual download from GitHub remains a permanent fallback.

---

## 9. UX parity (Phase F)

- **Floating toolbar + idle button (gap #6):** PySide6 frameless, `Qt.WindowStaysOnTopHint | Qt.Tool | Qt.FramelessWindowHint`, `WA_ShowWithoutActivating` (no focus steal — critical for dictation). Draggable; position persisted in `toolbar.position`. Two modes: recording bar (level meter, pause, stop) and idle circle (click to start). Invariant: main window and idle circle not both visible (mirror Repo 1).
- **History + export (gap #7):** `history.py` appends finalized sessions (timestamp, target app, text) to a store under `%APPDATA%`; `export.py` writes TXT and **RTL DOCX** via `python-docx` (set paragraph `bidi`, RTL run direction). History view in UI with export button.
- **Audio feedback (gap #8):** `QSoundEffect` start/stop tones gated by `audio.feedback_enabled` + `audio.feedback_volume`.
- **Pause/resume (gap #9):** add `pause()`/`resume()` to the controller state machine; keep audio capture alive but gate STT feed; optional pause hotkey alongside the existing toggle/push-to-talk in [hotkeys.py](../src/hebrew_live_dictation/hotkeys.py).
- **Onboarding provider selection + key test (gap #11):** extend the onboarding dialog with provider cards (Google / Local / Deepgram / Groq) and inline "Test" — engine config only.

---

## 10. Injection backends — preserve & document

No behavioral change. Add a short `InjectionBackend` doc (in `docs/`) describing the selection order and the contract so future providers never couple to injection. The current chain (Word COM → UIA → Unicode SendInput → clipboard, with target tracking and Z-order/30s freshness) is a **Repo-2 lead** and stays exactly as in [text_injector.py](../src/hebrew_live_dictation/text_injector.py) / [editing_backend.py](../src/hebrew_live_dictation/editing_backend.py).

---

## 11. Packaging & QA gates

- **Dependencies:** pin + lockfile (pip-tools or `uv`); add `faster-whisper`, `keyring`, `python-docx`, `psutil`, `requests`/`httpx`, `packaging`, provider clients. Measure PyInstaller size delta (expect CTranslate2 to dominate).
- **CI extensions** (`.github/workflows/build-release.yml`): add `bandit -r src/`, `safety`/`pip-audit`, coverage; generate + publish **SHA256SUMS** and the **signed manifest**; (Phase G) `signtool` Authenticode.
- **release_audit.py:** extend secret scanning (already covers dev paths, GOOGLE_APPLICATION_CREDENTIALS, private-key headers, `AIza…`); add Deepgram/Groq key patterns; assert manifest/pubkey present in release builds.
- **Automated GUI smoke (Phase G):** pyautogui/uiautomation harness for Notepad/Chrome inject + DPI; gate where feasible, manual matrix otherwise.

---

## 12. New dependencies & tradeoffs

| Dep | Purpose | Tradeoff / mitigation |
|---|---|---|
| `faster-whisper` (CTranslate2) | offline STT | large binaries; **download-on-demand models**, measure installer size |
| `keyring` | secret storage | backend availability varies; **fall back to JSON read** if unavailable |
| `python-docx` | RTL DOCX export | small; RTL needs explicit bidi flags |
| `psutil` | RAM preflight | small |
| `requests`/`httpx` + WS client | Deepgram/Groq | network error handling feeds AutoFallback |
| `packaging` | version compare in updater | tiny |
| minisign/PyNaCl | manifest signature verify | key custody is the real risk (see RISK_REGISTER) |

---

## 13. Per-phase rollback plans (authoritative)

| Phase | Change | Rollback |
|---|---|---|
| 0 | keyring migration | non-destructive; read keyring then JSON; never delete JSON pre-verify; re-enable JSON read |
| 0/F | updater | opt-in + signed-manifest kill-switch; disable update-check flag; manual download always available |
| A | provider abstraction | default `stt.provider=google_v2`; remove registry import to restore direct factory; pre-change commit tagged |
| B | move Google into base | parity tests gate merge; `git revert` move commit restores legacy path; CI green required both sides |
| C | local Whisper packaging | download-on-demand; behind `providers.whisper.enabled`; disable flag → cloud-only build unaffected |
| D | AutoFallback | behind `stt.mode`; set `stt.mode=api` |
| E | Deepgram/Groq | additive in registry+UI; remove from list/disable; Google default untouched |
| G | signing/Authenticode | CI-side only; unsigned build still functions; manifest signing independent |

---

## 14. Module-by-module change map

| File | Change |
|---|---|
| `stt/` (new) | `base.py`, `google_v2.py`, `whisper_local.py`, `deepgram.py`, `groq.py`, `fallback.py`, `registry.py` |
| [stt_factory.py](../src/hebrew_live_dictation/stt_factory.py) | dispatch on `stt.provider`; wrap with fallback on `auto_fallback` |
| [google_stt_v2_stream.py](../src/hebrew_live_dictation/google_stt_v2_stream.py) | relocated to `stt/google_v2.py`, subclass `SpeechClientBase` (Phase B) |
| `secrets_store.py` (new) | keyring wrapper + migration |
| `models.py` (new) | model download/hash/RAM/registry |
| `updater.py` (new) | signed-manifest GitHub updater |
| `history.py`, `export.py` (new) | history store + TXT/DOCX |
| [config.py](../src/hebrew_live_dictation/config.py) | schema bump + migration for new keys |
| [qt_app.py](../src/hebrew_live_dictation/qt_app.py) | provider UI, model page, history view, toolbar/idle widgets, pause/resume, audio feedback, test buttons |
| [hotkeys.py](../src/hebrew_live_dictation/hotkeys.py) | optional pause hotkey |
| [scripts/release_audit.py](../scripts/release_audit.py) | extended secret patterns + manifest/pubkey checks |
| `.github/workflows/build-release.yml` | SCA, coverage, checksums, signed manifest, (G) Authenticode |
| `HebrewLiveDictation.spec` | new hiddenimports/datas as needed; keep onedir |
| `requirements.txt`/`pyproject.toml` + lockfile | new pinned deps |
| `docs/` | InjectionBackend contract, updated architecture/QA, ADRs reference |
| `native/` + `tsf_*` | **unchanged**; stays gated |
