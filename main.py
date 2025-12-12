#!/usr/bin/env python3
"""Entry point for Trailing Stop Manager Desktop Application.

This module starts the Reflex application and provides a system tray integration
for easy access and control.

Usage:
    python main.py [--no-tray] [--no-browser]

Arguments:
    --no-tray: Start without system tray icon
    --no-browser: Don't auto-open browser on startup
"""
import argparse
import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from trailing_stop_web.tray import SystemTray
from trailing_stop_web.paths import get_app_data_dir

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# === PID Management (shared with main_desktop.py) ===
def get_pid_file_path() -> Path:
    """Get PID file path in app data directory."""
    return get_app_data_dir() / ".trailing_stop.pid"


def save_pids(pids: dict[str, int]) -> None:
    """Save process IDs to file for cleanup on next start."""
    try:
        pid_file = get_pid_file_path()
        with open(pid_file, "w") as f:
            for name, pid in pids.items():
                f.write(f"{name}:{pid}\n")
        logger.info(f"Saved PIDs to {pid_file}")
    except Exception as e:
        logger.debug(f"Could not save PIDs: {e}")


def cleanup_ports() -> None:
    """Kill any processes using our ports (3000, 8000)."""
    ports = [3000, 8000]
    for port in ports:
        try:
            # Use lsof to find PIDs on port
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid_str in result.stdout.strip().split('\n'):
                    try:
                        pid = int(pid_str)
                        # Don't kill ourselves
                        if pid != os.getpid():
                            os.kill(pid, signal.SIGKILL)
                            logger.info(f"Killed process on port {port} (PID {pid})")
                    except (ProcessLookupError, ValueError, PermissionError):
                        pass
        except Exception:
            pass


def cleanup_previous_instance() -> None:
    """Kill processes from previous instance using saved PIDs and port cleanup."""
    # First: cleanup by PID file
    pid_file = get_pid_file_path()
    if pid_file.exists():
        try:
            with open(pid_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if ":" in line:
                        name, pid_str = line.split(":", 1)
                        try:
                            pid = int(pid_str)
                            os.kill(pid, signal.SIGKILL)
                            logger.info(f"Killed previous {name} (PID {pid})")
                        except (ProcessLookupError, ValueError):
                            pass  # Process already dead
                        except PermissionError:
                            logger.warning(f"No permission to kill {name} (PID {pid_str})")
            pid_file.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"PID cleanup error: {e}")

    # Second: cleanup by ports (catches orphaned processes)
    cleanup_ports()


def remove_pid_file() -> None:
    """Remove PID file on clean shutdown."""
    try:
        get_pid_file_path().unlink(missing_ok=True)
    except Exception:
        pass


class ReflexApp:
    """Manager for the Reflex application subprocess."""

    def __init__(self, project_dir: Path):
        """Initialize Reflex app manager.

        Args:
            project_dir: Path to the Reflex project directory
        """
        self.project_dir = project_dir
        self.process: subprocess.Popen | None = None
        self.tray: SystemTray | None = None
        self._shutdown_initiated = threading.Event()
        self._reflex_ready = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    def _wait_for_reflex_ready(self, timeout: int = 60) -> bool:
        """Poll localhost:3000 until Reflex is ready or timeout.

        Args:
            timeout: Maximum seconds to wait for Reflex

        Returns:
            True if Reflex is ready, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            if self._shutdown_initiated.is_set():
                return False

            try:
                urllib.request.urlopen("http://localhost:3000", timeout=2)
                self._reflex_ready.set()
                return True
            except Exception:
                time.sleep(1)

        return False

    def _monitor_reflex_process(self) -> None:
        """Monitor Reflex process health in background thread."""
        while not self._shutdown_initiated.is_set():
            if self.process and self.process.poll() is not None:
                exit_code = self.process.returncode
                if not self._shutdown_initiated.is_set():
                    logger.error(f"Reflex process crashed (exit code: {exit_code})")
                    self._reflex_ready.clear()
                break
            time.sleep(2)

    def start_reflex(self) -> None:
        """Start the Reflex application as a subprocess."""
        try:
            # Start reflex run in the project directory
            # Don't capture stdout - let it flow to terminal
            self.process = subprocess.Popen(
                [sys.executable, "-m", "reflex", "run", "--loglevel", "info"],
                cwd=self.project_dir,
            )

            logger.info("Starting Reflex application...")

            # Check for immediate crash
            time.sleep(1)
            if self.process.poll() is not None:
                logger.error(f"Reflex failed to start (exit code: {self.process.returncode})")
                return

            # Start process monitor
            self._monitor_thread = threading.Thread(
                target=self._monitor_reflex_process,
                daemon=True
            )
            self._monitor_thread.start()

            # Wait for process to complete (runs until shutdown)
            self.process.wait()

        except FileNotFoundError:
            logger.error("Reflex not installed. Run: pip install reflex")
        except Exception as e:
            logger.error(f"Failed to start Reflex: {e}")

    def stop_reflex(self) -> None:
        """Stop the Reflex application gracefully."""
        if not self.process:
            return

        # Check if already terminated
        if self.process.poll() is not None:
            logger.info(f"Reflex already stopped (exit code: {self.process.returncode})")
            self.process = None
            return

        logger.info("Shutting down Reflex application...")

        try:
            # Try graceful shutdown first
            self.process.terminate()

            try:
                exit_code = self.process.wait(timeout=5)
                logger.info(f"Reflex stopped gracefully (exit code: {exit_code})")
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown fails
                logger.warning("Force stopping Reflex...")
                self.process.kill()
                exit_code = self.process.wait(timeout=2)
                logger.info(f"Reflex force stopped (exit code: {exit_code})")

        except ProcessLookupError:
            logger.info("Reflex process already terminated")
        except Exception as e:
            logger.error(f"Error stopping Reflex: {type(e).__name__}: {e}")
        finally:
            self.process = None

    def start_tray(self) -> None:
        """Start the system tray icon (runs in main thread on macOS)."""
        self.tray = SystemTray(on_quit=self._on_tray_quit)
        logger.info("System tray icon started")
        # Run tray in main thread (required on macOS)
        self.tray.run()

    def _on_tray_quit(self) -> None:
        """Callback when user clicks Quit in tray menu."""
        # Don't call shutdown() directly to avoid recursion
        # Just initiate shutdown - tray.run() will return after icon.stop()
        self._initiate_shutdown()

    def _initiate_shutdown(self) -> None:
        """Initiate shutdown sequence (idempotent)."""
        if self._shutdown_initiated.is_set():
            return
        self._shutdown_initiated.set()
        logger.info("Shutdown initiated...")

    def shutdown(self) -> None:
        """Shutdown the entire application (idempotent)."""
        # Mark shutdown as initiated
        self._initiate_shutdown()

        # Stop Reflex
        self.stop_reflex()

        # Stop tray if running
        if self.tray:
            try:
                self.tray.stop()
            except Exception as e:
                logger.debug(f"Tray already stopped: {e}")

        # Remove PID file on clean shutdown
        remove_pid_file()

    def run(self, use_tray: bool = True, open_browser: bool = True) -> None:
        """Run the application.

        Args:
            use_tray: Whether to show system tray icon
            open_browser: Whether to auto-open browser on startup
        """
        # Register cleanup handler
        atexit.register(self.shutdown)

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}")
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Clean up any leftover processes from previous runs
        cleanup_previous_instance()

        # Start Reflex in separate thread to avoid blocking
        reflex_thread = threading.Thread(target=self.start_reflex, daemon=False)
        reflex_thread.start()

        # Wait for Reflex to be ready (with health check)
        logger.info("Waiting for Reflex to be ready...")
        if not self._wait_for_reflex_ready(timeout=60):
            if not self._shutdown_initiated.is_set():
                logger.error("Reflex failed to start within timeout")
                self.shutdown()
                return

        logger.info("Reflex is ready!")

        # Save PIDs for cleanup on next start
        pids = {"main": os.getpid()}
        if self.process and self.process.pid:
            pids["reflex"] = self.process.pid
        save_pids(pids)

        # Auto-open browser if requested
        if open_browser and self._reflex_ready.is_set():
            import webbrowser
            logger.info("Opening browser...")
            webbrowser.open("http://localhost:3000")

        # Start system tray if requested
        if use_tray:
            print("\nApplication running. Use system tray to control.")
            print("Press Ctrl+C to quit if system tray is not available.\n")
            # Tray runs in main thread (blocking) - required on macOS
            self.start_tray()
            # After tray.run() returns (user clicked Quit), perform cleanup
            self.shutdown()
        else:
            print("\nApplication running at http://localhost:3000")
            print("Press Ctrl+C to quit.\n")

            # Wait for reflex thread or shutdown
            try:
                while not self._shutdown_initiated.is_set():
                    reflex_thread.join(timeout=1)
                    if not reflex_thread.is_alive():
                        break
            except KeyboardInterrupt:
                pass
            finally:
                self.shutdown()


def main() -> None:
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description="Trailing Stop Manager - Desktop Application"
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Start without system tray icon"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open browser on startup"
    )

    args = parser.parse_args()

    # Get project directory
    project_dir = Path(__file__).parent

    # Create and run app
    app = ReflexApp(project_dir)
    app.run(
        use_tray=not args.no_tray,
        open_browser=not args.no_browser
    )


if __name__ == "__main__":
    main()
