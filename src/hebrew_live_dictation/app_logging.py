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


def redact_sensitive(value: str) -> str:
    text = str(value or "")
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub("<redacted-path>", text)
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
