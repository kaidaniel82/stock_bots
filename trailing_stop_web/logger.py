"""Logging configuration with loguru.

Log Levels:
- INFO: Zusammenfassungen, wichtige Events (Connection, Stop Triggered, etc.)
- DEBUG: Detail-Logs pro Tick (für Entwicklung) - nur mit TSM_DEBUG=1

Environment Variables:
- TSM_DEBUG=1: Enable DEBUG level logging (default: INFO)
- TSM_LOG_RETENTION: Log retention period (default: "7 days")
"""
import os

from loguru import logger

from .paths import LOGS_DIR

# Remove default handler (no console output!)
logger.remove()

# Determine log level from environment
# DEBUG generates ~60MB/day, INFO is ~1-5MB/day
LOG_LEVEL = "DEBUG" if os.environ.get("TSM_DEBUG") == "1" else "INFO"
LOG_RETENTION = os.environ.get("TSM_LOG_RETENTION", "7 days")

# Single file handler
logger.add(
    LOGS_DIR / "trailing_stop_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level=LOG_LEVEL,
    rotation="00:00",
    retention=LOG_RETENTION,
    compression="gz",
)

# Log startup info
logger.info(f"Logging initialized: level={LOG_LEVEL}, retention={LOG_RETENTION}")

# Export logger
__all__ = ["logger"]
