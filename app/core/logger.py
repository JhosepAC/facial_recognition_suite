"""Centralized logging configuration (loguru).

Usage:
    from app.core.logger import logger
    logger.info("Person registered: {}", person.uuid)
"""

import sys

from loguru import logger

from app.core.config import settings

_LOGS_DIR = settings.resolve_path(settings.storage.logs_dir)
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()

# Console.
# In a packaged GUI application (PyInstaller), sys.stderr may be None.
if sys.stderr is not None:
    logger.add(
        sys.stderr,
        level=settings.logging.level,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
                "<cyan>{module}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )

# General application log file.
logger.add(
    _LOGS_DIR / "app.log",
    level=settings.logging.level,
    rotation=settings.logging.rotation,
    retention=settings.logging.retention,
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}:{function} - {message}",
)

# Dedicated audit log (sensitive actions: login, recognitions, DB changes).
logger.add(
    _LOGS_DIR / "audit.log",
    level="INFO",
    rotation=settings.logging.rotation,
    retention="365 days",
    filter=lambda record: record["extra"].get("audit") is True,
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | AUDIT | {message}",
)

audit_logger = logger.bind(audit=True)
