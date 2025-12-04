"""Logging configuration with loguru.

Log Levels:
- INFO: Zusammenfassungen, wichtige Events (Connection, Stop Triggered, etc.)
- DEBUG: Detail-Logs pro Tick (nur in Datei, für Entwicklung)
"""
from pathlib import Path
from loguru import logger

# Log directory
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Remove default handler (no console output!)
logger.remove()

# File handler - DEBUG level (all details for development)
logger.add(
    LOG_DIR / "trailing_stop_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="00:00",
    retention="7 days",
    compression="gz",
)

# Separate INFO-only log for summaries (smaller, easier to read)
logger.add(
    LOG_DIR / "trailing_stop_summary_{time:YYYY-MM-DD}.log",
    format="{time:HH:mm:ss} | {level: <8} | {message}",
    level="INFO",
    filter=lambda record: record["level"].name == "INFO",
    rotation="00:00",
    retention="7 days",
)

# Export logger
__all__ = ["logger"]
