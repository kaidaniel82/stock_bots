"""Platform-specific application data paths.

Provides cross-platform paths for application data storage:
- macOS: ~/Library/Application Support/trailing_stop_web/
- Windows: %LOCALAPPDATA%/trailing_stop_web/
- Linux: ~/.local/share/trailing_stop_web/
"""
from pathlib import Path

from platformdirs import user_data_dir, user_log_dir

APP_NAME = "trailing_stop_web"
APP_AUTHOR = "trailing_stop_web"


def get_app_data_dir() -> Path:
    """Get platform-specific application data directory.

    Returns:
        Path to app data directory (created if not exists)
    """
    path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    """Get directory for JSON data files (groups.json, connection_config.json).

    Returns:
        Path to data directory (created if not exists)
    """
    path = get_app_data_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    """Get platform-specific log directory.

    Returns:
        Path to logs directory (created if not exists)

    Platform paths:
    - macOS: ~/Library/Logs/trailing_stop_web/
    - Windows: %LOCALAPPDATA%/trailing_stop_web/Logs/
    - Linux: ~/.local/state/trailing_stop_web/log/
    """
    path = Path(user_log_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


# Pre-computed paths for direct import
DATA_DIR = get_data_dir()
LOGS_DIR = get_logs_dir()
