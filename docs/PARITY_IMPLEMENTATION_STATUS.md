# Parity upgrade — implementation status (as-built)

Branch: `feature/parity-upgrade`. Tests: **206 passing** (`PYTHONPATH=src python -m unittest discover -s tests`). Default behavior unchanged (Google STT V2/Chirp 3 remains the default; everything new is behind config flags, off by default).

## Implemented (gap → commit)

| # | Capability | Commit(s) |
|---|---|---|
| 1 | STT provider abstraction (registry + `SpeechClientBase`) | `c9f74f2` |
| 1 | Google unified onto the abstraction (zero-regression) | `c9f74f2` |
| 4 | OS keyring credentials + non-destructive migration | `026c7c2` |
| — | Global crash handling + `SECURITY.md` | `026c7c2` |
| 2,10 | Offline local Whisper (faster-whisper) + model mgmt + RAM preflight | `b17fdda`, `2a7ba78` |
| 3 | API→local AutoFallback + `stt.mode` routing | `2be84a7` |
| 1 | Deepgram + Groq providers + shared silence segmenter | `449870b` |
| — | Smart Auto provider selection (`stt.mode=smart_auto`) | `6145a4f` |
| 12 | WER benchmark harness | `a7629d5` |
| 11 | Engine settings UI (mode/provider/model) + key Test (keyring) | `dc8ad56`, `2a7ba78` |
| 7 | Transcription history + TXT/DOCX (RTL) export | `622b03e` |
| 8 | Audio start/stop feedback tones | `2686007` |
| 6 | Floating toolbar + idle quick-start button (no-focus-steal) | `8406d2a` |
| 9 | Pause/resume hotkey (Option 2; Option 1 documented) | `a80908a` |
| 5 | Signed-manifest auto-updater + release-signing helper + guide | `c454a32`, `8e54f33` |
| — | Packaging: PyInstaller spec collects new deps | (this doc's commit) |

All five product modes are config-selectable: **Smart Auto · Best Hebrew realtime (deepgram) · Offline/private (local) · Cheapest cloud (groq) · AutoFallback**.

## Preserved (verified unbroken)
Windows injection (Word COM / UI Automation / Unicode SendInput / clipboard), target tracking, multi-language command packs, session editing, schema-versioned config + migrations (`schema_version` still 4), privacy-by-default logging, CI test gate + `release_audit.py`. TSF/IME remains **gated** (`tsf.experimental_transport_enabled=false`). No plaintext secrets; no models bundled.

## Remaining — operational (needs your infrastructure; not code)

1. **Verify a real PyInstaller build on Windows.** The spec now uses
   `collect_all` for `faster_whisper`/`ctranslate2`/`av`/`tokenizers`/
   `huggingface_hub`/`onnxruntime` plus hiddenimports for keyring/QtMultimedia/
   cryptography/requests/websockets/docx/psutil. `collect_all` resolves these in
   this environment, but a full `build_app.ps1` run + launch is needed to confirm
   (ctranslate2/onnxruntime/QtMultimedia occasionally need build-iteration).
2. **CI manifest-signing automation** (a CI change): generate a key
   (`python scripts/sign_release.py keygen`), add the private key as a GitHub
   Actions secret, bake the public key into `updater.EMBEDDED_PUBLIC_KEY_B64`,
   and add a release step that signs `latest.json` + publishes `SHA256SUMS`.
   Until then, sign releases manually per `docs/updater.md`.
3. **Authenticode** installer signing — needs an OV/EV code-signing certificate
   (reduces SmartScreen friction; independent of manifest signing).

## Deferred / future (documented)
- Full session-preserving pause/resume — `docs/future_pause_resume.md`.
- TSF/IME promotion gate — `docs/v2_tsf_risk_plan.md` + `docs/qa.md` (stays gated).
- `audioop` is deprecated (used by `audio_stream`/`vad`/`segmenter`); plan a
  replacement before adopting Python 3.13.

## How to operate the new engine (quick)
- Pick a mode/provider on the **Engine** settings page; enter Deepgram/Groq keys
  there (stored in the OS keyring) and use **Test**.
- Offline: enable Whisper, pick a model, click **Download model**. Offline dictation
  requires an explicitly downloaded model; first-use auto-download is not a supported
  readiness path (starting offline without an installed model is refused).
- Updater: see `docs/updater.md` (off by default; sign with `scripts/sign_release.py`).
