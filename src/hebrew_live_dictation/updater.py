"""Signed-manifest auto-updater (GitHub releases).

Security model (ADR-006): the manifest (latest.json) and the installer are
co-hosted in the same GitHub release, so a SHA-256 listed in the manifest is NOT
an integrity root. We therefore verify an **Ed25519 signature over the manifest**
using a public key embedded in the app BEFORE trusting any field; SHA-256 is used
only as a download-corruption check. A signed ``disabled`` / ``min_version`` field
acts as a kill-switch.

Network, crypto, and installer-launch are behind seams so the logic is fully
unit-testable. The updater is inert until ``updater.enabled`` and a public key are
configured; the production public key must be baked into ``EMBEDDED_PUBLIC_KEY_B64``
at build time (config override is for staging/testing only).
"""

import base64
import hashlib
import json
import logging
import os


logger = logging.getLogger("Updater")

# Production: base64-encoded raw Ed25519 public key, baked into the build.
EMBEDDED_PUBLIC_KEY_B64 = ""


def app_version():
    try:
        from importlib.metadata import version

        return version("hebrew-live-dictation")
    except Exception:
        return "1.1.0"


def public_key_b64(config):
    # Embedded constant wins; config override exists only for staging/testing.
    if EMBEDDED_PUBLIC_KEY_B64:
        return EMBEDDED_PUBLIC_KEY_B64
    return str(config.get("updater.public_key", "") or "")


def verify_signature(message, signature, public_key_b64_str):
    if not public_key_b64_str or not signature:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64_str))
        try:
            pub.verify(signature, message)
            return True
        except InvalidSignature:
            return False
    except Exception as e:  # malformed key/signature
        logger.warning("Signature verification error: %s", e)
        return False


def parse_manifest(text):
    data = json.loads(text)
    return {
        "version": str(data.get("version", "")),
        "url": str(data.get("url", "")),
        "sha256": str(data.get("sha256", "")).lower(),
        "notes": str(data.get("notes", "")),
        "disabled": bool(data.get("disabled", False)),
        "min_version": str(data.get("min_version", "")),
    }


def should_update(current_version, manifest):
    from packaging.version import InvalidVersion, Version

    if manifest.get("disabled"):
        return False, "Updates are disabled by the server."
    target = manifest.get("version", "")
    if not target:
        return False, "No version in manifest."
    try:
        if Version(target) <= Version(current_version):
            return False, "Already up to date."
    except InvalidVersion:
        return False, "Invalid version in manifest."
    return True, "Update available."


def _http_fetch(url, binary=False):
    import requests

    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.content if binary else resp.text


def check_for_update(config, current_version=None, fetch=None):
    """Returns {status, message, manifest?}. status in: disabled, not_configured,
    error, untrusted, up_to_date, update_available."""
    if not config.get("updater.enabled", False):
        return {"status": "disabled", "message": "Automatic updates are turned off."}
    endpoint = str(config.get("updater.endpoint", "") or "")
    if not endpoint:
        return {"status": "not_configured", "message": "No update endpoint configured."}
    pub = public_key_b64(config)
    if not pub:
        return {"status": "not_configured", "message": "No update signing key configured."}
    if current_version is None:
        current_version = app_version()
    if fetch is None:
        fetch = _http_fetch
    try:
        manifest_text = fetch(endpoint)
        signature = fetch(endpoint + ".sig", binary=True)
    except Exception as e:
        return {"status": "error", "message": f"Update check failed: {e}"}

    text = manifest_text if isinstance(manifest_text, str) else manifest_text.decode("utf-8", "ignore")
    if not verify_signature(text.encode("utf-8"), signature, pub):
        return {"status": "untrusted", "message": "Update manifest signature is invalid; ignored."}
    try:
        manifest = parse_manifest(text)
    except Exception as e:
        return {"status": "error", "message": f"Malformed update manifest: {e}"}
    ok, reason = should_update(current_version, manifest)
    return {"status": "update_available" if ok else "up_to_date", "message": reason, "manifest": manifest}


def verify_installer_sha256(path, expected_hex):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == (expected_hex or "").lower()


def download_and_launch(manifest, dest_dir, fetch=None, runner=None):
    """Download the installer, verify its SHA-256, then launch it. Returns
    (ok, path_or_message). The signature must already have been verified by
    check_for_update before this is called."""
    url = manifest.get("url", "")
    if not url:
        return False, "No installer URL in manifest."
    if fetch is None:
        fetch = _http_fetch
    data = fetch(url, binary=True)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, os.path.basename(url) or "update_installer.exe")
    with open(path, "wb") as f:
        f.write(data)
    if manifest.get("sha256") and not verify_installer_sha256(path, manifest["sha256"]):
        try:
            os.remove(path)
        except OSError:
            pass
        return False, "Downloaded installer failed the SHA-256 check."
    (runner or _launch_installer)(path)
    return True, path


def _launch_installer(path):  # pragma: no cover - Windows shell launch
    os.startfile(path)  # noqa: S606
