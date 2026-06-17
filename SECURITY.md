# Security Policy

## Supported versions

Hebrew Live Dictation is in beta. Security fixes are applied to the latest
released version on the `main` branch. Older builds are not maintained.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for an
unfixed vulnerability.

- Preferred: open a GitHub **Security Advisory** ("Report a vulnerability") on
  the repository, which keeps the report private until a fix is available.
- Alternatively, contact the maintainer directly through the email associated
  with the GitHub account that owns the repository.

When reporting, please include:

- affected version / commit,
- a description of the issue and its impact,
- reproduction steps or a proof of concept,
- any suggested remediation.

We aim to acknowledge reports within a few business days and to coordinate a
fix and disclosure timeline with you.

## Handling of credentials and user data

- **API keys / provider secrets** are stored in the operating system credential
  store via the `keyring` library (Windows Credential Manager), never in
  `settings.json`. See `src/hebrew_live_dictation/secrets_store.py`.
- **Google credentials** use either a Service Account JSON file referenced by
  path, or Application Default Credentials (ADC). The app does not transmit
  credentials anywhere except to the configured speech provider.
- **Logs** redact filesystem paths via a privacy formatter, and transcript text
  is **not** logged unless `dictation.debug_log_transcripts` is explicitly
  enabled. Logs are written under `%APPDATA%\VoiceType`.
- **Audio** is streamed only to the configured speech provider for the duration
  of dictation; it is not persisted by the app.
- **No telemetry / analytics** are collected.

## Release integrity (in progress)

Update manifests are verified against a signed manifest (embedded public key)
before any installer is trusted; installer SHA-256 is used as a corruption
check. Authenticode signing of the installer is planned. See the project's
architecture and updater documentation for details.
