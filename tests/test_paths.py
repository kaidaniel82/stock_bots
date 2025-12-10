"""Unit tests for platform-specific paths module."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


class TestGetAppDataDir:
    """Tests for get_app_data_dir function."""

    def test_returns_path_object(self):
        """Should return a Path object."""
        from trailing_stop_web.paths import get_app_data_dir

        result = get_app_data_dir()
        assert isinstance(result, Path)

    def test_directory_exists(self):
        """Should create directory if not exists."""
        from trailing_stop_web.paths import get_app_data_dir

        result = get_app_data_dir()
        assert result.exists()
        assert result.is_dir()

    def test_contains_app_name(self):
        """Path should contain app name."""
        from trailing_stop_web.paths import get_app_data_dir

        result = get_app_data_dir()
        assert "trailing_stop_web" in str(result)


class TestGetDataDir:
    """Tests for get_data_dir function."""

    def test_returns_path_object(self):
        """Should return a Path object."""
        from trailing_stop_web.paths import get_data_dir

        result = get_data_dir()
        assert isinstance(result, Path)

    def test_directory_exists(self):
        """Should create directory if not exists."""
        from trailing_stop_web.paths import get_data_dir

        result = get_data_dir()
        assert result.exists()
        assert result.is_dir()

    def test_is_subdirectory_of_app_data(self):
        """Data dir should be inside app data dir."""
        from trailing_stop_web.paths import get_app_data_dir, get_data_dir

        app_dir = get_app_data_dir()
        data_dir = get_data_dir()
        assert str(data_dir).startswith(str(app_dir))

    def test_ends_with_data(self):
        """Data dir should end with 'data'."""
        from trailing_stop_web.paths import get_data_dir

        result = get_data_dir()
        assert result.name == "data"


class TestGetLogsDir:
    """Tests for get_logs_dir function."""

    def test_returns_path_object(self):
        """Should return a Path object."""
        from trailing_stop_web.paths import get_logs_dir

        result = get_logs_dir()
        assert isinstance(result, Path)

    def test_directory_exists(self):
        """Should create directory if not exists."""
        from trailing_stop_web.paths import get_logs_dir

        result = get_logs_dir()
        assert result.exists()
        assert result.is_dir()

    def test_contains_app_name(self):
        """Path should contain app name."""
        from trailing_stop_web.paths import get_logs_dir

        result = get_logs_dir()
        assert "trailing_stop_web" in str(result)


class TestPrecomputedPaths:
    """Tests for pre-computed path constants."""

    def test_data_dir_constant(self):
        """DATA_DIR constant should match get_data_dir()."""
        from trailing_stop_web.paths import DATA_DIR, get_data_dir

        assert DATA_DIR == get_data_dir()

    def test_logs_dir_constant(self):
        """LOGS_DIR constant should match get_logs_dir()."""
        from trailing_stop_web.paths import LOGS_DIR, get_logs_dir

        assert LOGS_DIR == get_logs_dir()


class TestPlatformPaths:
    """Platform-specific path tests."""

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_macos_app_data_path(self):
        """macOS should use ~/Library/Application Support/."""
        from trailing_stop_web.paths import get_app_data_dir

        result = get_app_data_dir()
        assert "Library/Application Support" in str(result)

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_macos_logs_path(self):
        """macOS should use ~/Library/Logs/."""
        from trailing_stop_web.paths import get_logs_dir

        result = get_logs_dir()
        assert "Library/Logs" in str(result)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_windows_app_data_path(self):
        """Windows should use LOCALAPPDATA."""
        from trailing_stop_web.paths import get_app_data_dir

        result = get_app_data_dir()
        # Windows path contains AppData\Local or similar
        assert "AppData" in str(result) or "Local" in str(result).lower()

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
    def test_linux_app_data_path(self):
        """Linux should use ~/.local/share/."""
        from trailing_stop_web.paths import get_app_data_dir

        result = get_app_data_dir()
        assert ".local/share" in str(result)
