"""Structured logging configuration with security sanitization."""

import logging
import re
import sys

# Patterns to mask in logs
SENSITIVE_PATTERNS = [
    re.compile(r'(password["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE),
    re.compile(r'(secret["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE),
    re.compile(r'(token["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE),
    re.compile(r'(authorization["\']?\s*[:=]\s*["\']Bearer\s+)([^"\']+)(["\'])', re.IGNORECASE),
]


class SensitiveDataFilter(logging.Filter):
    """Filter that sanitizes sensitive data from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in SENSITIVE_PATTERNS:
                record.msg = pattern.sub(r"\1***REDACTED***\3", record.msg)
        if record.args:
            sanitized_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pattern in SENSITIVE_PATTERNS:
                        arg = pattern.sub(r"\1***REDACTED***\3", arg)
                sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        return True


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure application-wide logger."""
    logger = logging.getLogger("dynamic_tenant_api")
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveDataFilter())
        logger.addHandler(handler)

    return logger


logger = setup_logging()
