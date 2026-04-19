"""
Structured Logging Module — Production-Grade Logger for the OAuth Platform.

Provides:
- File-based rotating log handler for local development (daily rotation, 30-day retention)
- Console handler for runtime output
- Structured log format with timestamps, levels, and module context
- Singleton pattern: prevents duplicate handler attachment
- Environment-aware: DEBUG level in development, INFO in production
- Configurable: LOG_TO_FILE toggles file logging, LOG_DIR controls the log path

Usage:
    from app.core.logger import create_logger
    logger = create_logger("auth")
    logger.info("User authenticated", extra={"user": "john"})
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime


# ── Configuration ─────────────────────────────────────────────────────────────
_DEFAULT_LOG_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "logs",
)

_ENV = os.getenv("ENV", "development").lower()
_LOG_LEVEL = logging.DEBUG if _ENV == "development" else logging.INFO
_LOG_BASE_DIR = os.path.abspath(os.getenv("LOG_DIR", _DEFAULT_LOG_BASE_DIR))


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_LOG_TO_FILE = _env_flag("LOG_TO_FILE", _ENV in {"development", "local"})

# ── Format Strings ────────────────────────────────────────────────────────────
_FILE_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-20s | %(funcName)s:%(lineno)d | %(message)s"
)
_CONSOLE_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── Tracked loggers to prevent duplicate handler attachment ───────────────────
_initialized_loggers: set[str] = set()


def create_logger(name: str) -> logging.Logger:
    """
    Create or retrieve a structured logger with environment-aware handlers.

    Uses a singleton pattern — calling with the same name returns the
    previously configured logger without adding duplicate handlers.

    Args:
        name: Logger name, typically the module/service name.
              Creates a log subdirectory under `logs/{name}/`.

    Returns:
        Configured logging.Logger instance.
    """
    # Return existing logger if already initialized to prevent duplicate handlers
    if name in _initialized_loggers:
        return logging.getLogger(name)

    logger = logging.getLogger(name)
    logger.setLevel(_LOG_LEVEL)

    # Prevent log propagation to root logger (avoids duplicate console output)
    logger.propagate = False

    # ── File Handler: daily rotating log files ────────────────────────────
    if _LOG_TO_FILE:
        log_dir = os.path.join(_LOG_BASE_DIR, name)
        os.makedirs(log_dir, exist_ok=True)

        current_date = datetime.now().strftime("%Y-%m-%d")
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(log_dir, f"{current_date}.log"),
            when="midnight",
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(_LOG_LEVEL)
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
        logger.addHandler(file_handler)

    # ── Console Handler: human-readable output for development ────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(_LOG_LEVEL)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(console_handler)

    _initialized_loggers.add(name)
    return logger


# ── Application-wide startup logger ──────────────────────────────────────────
# Pre-create a "system" logger for startup/shutdown messages
startup_logger = create_logger("system")


__all__ = ["create_logger", "startup_logger"]
