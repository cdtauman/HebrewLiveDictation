"""OS keyring-backed secret storage for provider API keys.

Secrets (e.g. Deepgram/Groq API keys added in later phases) are stored in the
OS credential store via the ``keyring`` library, never in ``settings.json``.

Design notes:
- All operations degrade gracefully: if ``keyring`` is missing or its backend is
  unusable (locked-down/enterprise machines), reads return ``None`` and writes
  return ``False`` so callers can fall back to reading plaintext config.
- ``migrate_plaintext_secrets`` is NON-DESTRUCTIVE: it only clears a plaintext
  value from config after a verified keyring read-back.
- A ``keyring_module`` parameter allows tests to inject a fake backend without
  touching the real OS keyring or requiring the dependency to be installed.
"""

import logging


logger = logging.getLogger("SecretsStore")

SERVICE = "HebrewLiveDictation"

# Config keys that may hold a plaintext secret and should live in the keyring.
# Forward-looking: these provider keys are introduced in later phases. The
# migration is a safe no-op until they exist.
SECRET_CONFIG_KEYS = (
    "providers.deepgram.api_key",
    "providers.groq.api_key",
)


def _entry_name(config_key: str) -> str:
    """Map a dotted config key to a flat keyring entry name."""
    return config_key.replace(".", "_")


def _keyring():
    try:
        import keyring

        return keyring
    except Exception as e:  # pragma: no cover - import availability guard
        logger.warning("keyring library is unavailable: %s", e)
        return None


def keyring_available(*, keyring_module=None) -> bool:
    kr = keyring_module or _keyring()
    if kr is None:
        return False
    try:
        kr.get_password(SERVICE, "__probe__")
        return True
    except Exception as e:
        logger.warning("keyring backend is not usable: %s", e)
        return False


def set_secret(name: str, value: str, *, keyring_module=None) -> bool:
    kr = keyring_module or _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(SERVICE, name, value)
        return True
    except Exception as e:
        logger.error("Failed to store secret %r: %s", name, e)
        return False


def get_secret(name: str, *, keyring_module=None):
    kr = keyring_module or _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE, name)
    except Exception as e:
        logger.warning("Failed to read secret %r: %s", name, e)
        return None


def has_secret(name: str, *, keyring_module=None) -> bool:
    return bool(get_secret(name, keyring_module=keyring_module))


def delete_secret(name: str, *, keyring_module=None) -> bool:
    kr = keyring_module or _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, name)
        return True
    except Exception as e:
        logger.warning("Failed to delete secret %r: %s", name, e)
        return False


def migrate_plaintext_secrets(config, *, keyring_module=None):
    """Move any plaintext secrets from config into the keyring.

    Returns the list of config keys that were migrated. Non-destructive: a value
    is cleared from config only after a verified keyring read-back succeeds.
    """
    migrated = []
    for config_key in SECRET_CONFIG_KEYS:
        value = config.get(config_key, "")
        if not value:
            continue
        name = _entry_name(config_key)
        if not set_secret(name, value, keyring_module=keyring_module):
            logger.warning(
                "Could not migrate %s to keyring; leaving plaintext value in place.",
                config_key,
            )
            continue
        if get_secret(name, keyring_module=keyring_module) != value:
            logger.warning(
                "Keyring read-back mismatch for %s; leaving plaintext value in place.",
                config_key,
            )
            continue
        config.set(config_key, "")  # only after verified write
        migrated.append(config_key)
    if migrated:
        logger.info("Migrated %d secret(s) from settings into the OS keyring.", len(migrated))
    return migrated
