"""Logging configuration with loguru.

Log Levels:
- INFO: Zusammenfassungen, wichtige Events (Connection, Stop Triggered, etc.)
- DEBUG: Detail-Logs pro Tick (für Entwicklung)
"""
from loguru import logger

from .paths import LOGS_DIR

# Remove default handler (no console output!)
logger.remove()

# Single file handler - DEBUG level (all logs)
logger.add(
    LOGS_DIR / "trailing_stop_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="00:00",
    retention="7 days",
    compression="gz",
)

# Export logger
__all__ = ["logger"]
