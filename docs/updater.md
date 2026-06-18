# Auto-updater — operating guide

The app can check a signed manifest on GitHub releases and offer an update. It is
**off by default** and inert until configured. Security model: an **Ed25519
signature over `latest.json`** is verified with a public key baked into the app
**before** any field is trusted; SHA-256 is only a download-corruption check
(manifest + installer are co-hosted, so the hash alone is not an integrity root).
See `src/hebrew_live_dictation/updater.py` and ADR-006.

## One-time setup

1. **Generate a keypair** (keep the private key offline; `.keys/`, `*.pem` are
   git-ignored):
   ```
   python scripts/sign_release.py keygen --out-dir .keys
   ```
2. **Bake the public key** into the build: set `EMBEDDED_PUBLIC_KEY_B64` in
   `src/hebrew_live_dictation/updater.py` to the printed base64 value.
3. **Configure** the app (settings.json under %APPDATA%\VoiceType):
   ```json
   "updater": {
     "enabled": true,
     "check_on_start": false,
     "endpoint": "https://github.com/<owner>/<repo>/releases/latest/download/latest.json",
     "public_key": ""
   }
   ```
   Leave `public_key` empty in production — the embedded constant is authoritative;
   the config field is for staging/testing only.

## Per release

1. Build the installer (`build_app.ps1`) and compute its SHA-256.
2. Write `latest.json`:
   ```json
   {
     "version": "1.1.0",
     "url": "https://github.com/<owner>/<repo>/releases/download/v1.1.0/HebrewLiveDictation_Setup_1.1.0.exe",
     "sha256": "<installer sha-256>",
     "notes": "What changed",
     "disabled": false,
     "min_version": ""
   }
   ```
3. **Sign it** and upload `latest.json`, `latest.json.sig`, and the installer to
   the GitHub release:
   ```
   python scripts/sign_release.py sign --key .keys/updater_private.pem \
       --manifest latest.json --out latest.json.sig
   ```

`disabled: true` (or a higher `min_version`) is a **kill-switch** for a bad
rollout — the app refuses to offer such a manifest.

## Deferred (not yet automated)
- A **CI step** to sign `latest.json` automatically (needs the private key as a
  GitHub Actions secret) and publish `SHA256SUMS`.
- **Authenticode** signing of the installer (needs an OV/EV code-signing
  certificate) — reduces SmartScreen friction; independent of manifest signing.
- The current UI ("Check for updates" on the Logs/About page) verifies and opens
  the release URL; auto-download+launch (`updater.download_and_launch`) exists and
  is tested but is intentionally not wired to run installers unattended yet.
