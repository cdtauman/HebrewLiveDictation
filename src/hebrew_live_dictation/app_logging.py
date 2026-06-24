import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler


SENSITIVE_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings).*?\.json", re.IGNORECASE),
    re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[^\s'\"]+", re.IGNORECASE),
    re.compile(r"(?:^|\s)(?:[\w.-]+[\\/]){1,}[^\\/ \t\r\n'\"]+\.json", re.IGNORECASE),
)

# Provider/API secret shapes. Order matters: redact the Authorization header first
# (keeping the label so the line still reads sensibly), then scheme-prefixed tokens,
# then known key prefixes (OpenAI sk-, Groq gsk_, Deepgram dg-), then long opaque
# hex/base64 blobs. These catch raw keys embedded in exception/error strings and in
# any third-party library log line that echoes a request. Over-redaction in logs is
# acceptable; a leaked credential is not.
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer|token)\s+[^\s'\"]+")
_SECRET_TOKEN_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|token)\s+[A-Za-z0-9._~+/\-]{8,}=*"),
    re.compile(r"(?i)\b(?:sk|gsk|dg|pk|rk)[-_][A-Za-z0-9_\-]{12,}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),       # long hex (e.g. 40-hex Deepgram key, sha-*)
    re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"),    # long opaque base64/url-safe token
)


def redact_secrets(value: str) -> str:
    """Redact provider/API-token-shaped secrets from arbitrary text (logs, error
    strings, diagnostics). Safe to call on non-secret text — it only touches
    token-shaped substrings."""
    text = str(value or "")
    text = _AUTH_HEADER_RE.sub(r"\1<redacted-secret>", text)
    for pattern in _SECRET_TOKEN_PATTERNS:
        text = pattern.sub("<redacted-secret>", text)
    return text


def redact_sensitive(value: str) -> str:
    text = str(value or "")
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("<redacted-path>", text)
    # Also strip provider/API tokens so credential-bearing paths AND secrets are
    # scrubbed from the same UI/log strings.
    text = redact_secrets(text)
    return text


class PrivacyFormatter(logging.Formatter):
    def format(self, record):
        return redact_sensitive(super().format(record))

def setup_logging(log_dir: str, debug: bool = False):
    log_file = os.path.join(log_dir, "hebrew_live_dictation.log")
    
    # Configure root logger
    root_logger = logging.getLogger()
    # Set default level to DEBUG so handlers can filter
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        
    formatter = PrivacyFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # File handler
    try:
        file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Failed to setup file logging: {e}", file=sys.stderr)
        
    noisy_libraries = ("comtypes", "comtypes.client", "comtypes.tools", "urllib3")
    for logger_name in noisy_libraries:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Console handler: keep command-line runs usable. Detailed diagnostics stay in the log file.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
    root_logger.addHandler(console_handler)
    
    logging.info("Logging initialized.")

def log_transcript(logger: logging.Logger, level: int, prefix: str, text: str, debug_enabled: bool):
    """
    Utility to log transcripts securely. If debug_enabled is False,
    the text content is redacted to protect user privacy.
    """
    if debug_enabled:
        logger.log(level, f"{prefix}: {text}")
    else:
        logger.log(level, f"{prefix}: [REDACTED (length {len(text)})]")
