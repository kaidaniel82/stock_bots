"""Logging configuration with loguru."""
import sys
from pathlib import Path
from loguru import logger

# Log directory
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Remove default handler
logger.remove()

# Console handler (wie bisher)
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# File handler mit täglicher Rotation
logger.add(
    LOG_DIR / "trailing_stop_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="00:00",      # Neue Datei jeden Tag um Mitternacht
    retention="7 days",    # 7 Tage behalten
    compression="gz",      # Alte Logs komprimieren
)

# Export logger
__all__ = ["logger"]
