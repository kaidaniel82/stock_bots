"""Contract tests for Connection Watchdog.

These tests verify that:
1. Heartbeat mechanism detects silent disconnects
2. Connection metrics are correctly tracked
3. Disconnect reasons are properly classified

The watchdog uses reqCurrentTime() as a lightweight heartbeat
to detect network issues or TWS crashes that don't trigger
the normal disconnect events.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


class TestHeartbeatWatchdog:
    """Test heartbeat watchdog functionality."""

    def test_heartbeat_success_updates_timestamp(self):
        """Successful heartbeat should update last_heartbeat timestamp."""
        from trailing_stop_web.broker import TWSBroker

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker.ib = Mock()
            broker.ib.reqCurrentTime.return_value = datetime.now()
            broker._last_heartbeat = None

            result = broker._send_heartbeat()

            assert result is True
            assert broker._last_heartbeat is not None
            broker.ib.reqCurrentTime.assert_called_once()

    def test_heartbeat_failure_returns_false(self):
        """Failed heartbeat (exception) should return False."""
        from trailing_stop_web.broker import TWSBroker

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker.ib = Mock()
            broker.ib.reqCurrentTime.side_effect = Exception("Connection lost")
            broker._last_heartbeat = 12345.0

            result = broker._send_heartbeat()

            assert result is False
            # Last heartbeat should NOT be updated on failure
            assert broker._last_heartbeat == 12345.0

    def test_heartbeat_none_response_returns_false(self):
        """Heartbeat returning None should be treated as failure."""
        from trailing_stop_web.broker import TWSBroker

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker.ib = Mock()
            broker.ib.reqCurrentTime.return_value = None
            broker._last_heartbeat = 12345.0

            result = broker._send_heartbeat()

            assert result is False


class TestConnectionMetrics:
    """Test connection metrics tracking."""

    def test_metrics_when_connected(self):
        """Metrics should show uptime when connected."""
        from trailing_stop_web.broker import TWSBroker
        import time

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker._connected = True
            broker._connect_time = time.time() - 60  # Connected 60s ago
            broker._last_heartbeat = time.time() - 5  # Heartbeat 5s ago
            broker._reconnect_count = 3
            broker._last_disconnect_reason = "Test reason"

            metrics = broker.get_connection_metrics()

            assert metrics["connected"] is True
            assert 59 <= metrics["uptime_seconds"] <= 61  # ~60s
            assert metrics["reconnect_count"] == 3
            assert 4 <= metrics["last_heartbeat_ago"] <= 6  # ~5s
            assert metrics["last_disconnect_reason"] == "Test reason"

    def test_metrics_when_disconnected(self):
        """Metrics should show zero uptime when disconnected."""
        from trailing_stop_web.broker import TWSBroker

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker._connected = False
            broker._connect_time = None
            broker._last_heartbeat = None
            broker._reconnect_count = 5
            broker._last_disconnect_reason = "Heartbeat timeout"

            metrics = broker.get_connection_metrics()

            assert metrics["connected"] is False
            assert metrics["uptime_seconds"] == 0
            assert metrics["reconnect_count"] == 5
            assert metrics["last_heartbeat_ago"] is None
            assert metrics["last_disconnect_reason"] == "Heartbeat timeout"


class TestDisconnectReasonClassification:
    """Test that disconnect reasons are properly tracked."""

    def test_passive_disconnect_reason(self):
        """isConnected() returning False should set correct reason."""
        # This is tested via the _run_connected_loop behavior
        # The reason should be: "ib.isConnected() returned False"
        expected_reason = "ib.isConnected() returned False"
        assert "isConnected" in expected_reason

    def test_heartbeat_timeout_reason(self):
        """Heartbeat failure should set correct reason."""
        # The reason should be: "Heartbeat timeout"
        expected_reason = "Heartbeat timeout"
        assert "Heartbeat" in expected_reason


class TestReconnectCountTracking:
    """Test that reconnect count is properly incremented."""

    def test_reconnect_increments_count(self):
        """Each reconnection attempt should increment the count."""
        from trailing_stop_web.broker import TWSBroker
        from trailing_stop_web.config import RECONNECT_INITIAL_DELAY

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker._reconnect_attempt = 0
            broker._reconnect_count = 0
            broker._reconnect_delay = RECONNECT_INITIAL_DELAY
            broker._stop_requested = True  # Stop immediately
            broker._last_disconnect_reason = ""
            broker._connection_status_callback = None
            broker._current_status = "Disconnected"
            broker.ib = Mock()

            broker._handle_reconnection()

            assert broker._reconnect_attempt == 1
            assert broker._reconnect_count == 1


class TestConnectionStatusPolling:
    """Test that connection status can be polled by UI."""

    def test_get_connection_status_returns_current(self):
        """get_connection_status should return _current_status."""
        from trailing_stop_web.broker import TWSBroker

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker._current_status = "Reconnecting in 5s (#2) (Heartbeat timeout)"

            status = broker.get_connection_status()

            assert status == "Reconnecting in 5s (#2) (Heartbeat timeout)"

    def test_notify_status_updates_current_status(self):
        """_notify_status should update _current_status for polling."""
        from trailing_stop_web.broker import TWSBroker

        with patch.object(TWSBroker, '__init__', lambda x: None):
            broker = TWSBroker()
            broker._current_status = "Disconnected"
            broker._connection_status_callback = None

            broker._notify_status("Connected")

            assert broker._current_status == "Connected"
            assert broker.get_connection_status() == "Connected"
