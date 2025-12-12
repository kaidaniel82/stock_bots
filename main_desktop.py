#!/usr/bin/env python3
"""Desktop entry point for Nuitka-bundled Trailing Stop Manager.

This module starts:
1. Backend: Reflex/uvicorn on port 8000
2. Frontend: Bun dev server on port 3000
3. System tray for control

For Nuitka deployment only - use main.py for development.
"""
import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_app_dir() -> Path:
    """Get the application directory (handles Nuitka bundle)."""
    # Check if running as Nuitka bundle
    if getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS'):
        # Nuitka/PyInstaller bundle
        return Path(sys.executable).parent

    # Check for __compiled__ (Nuitka specific)
    if '__compiled__' in dir():
        return Path(sys.executable).parent

    # Development mode
    return Path(__file__).parent


# Set up app directory immediately
APP_DIR = get_app_dir()
os.chdir(APP_DIR)
logger.info(f"App directory: {APP_DIR}")


def get_pid_file_path() -> Path:
    """Get PID file path in app data directory (lazy evaluation)."""
    try:
        from trailing_stop_web.paths import get_app_data_dir
        return get_app_data_dir() / ".trailing_stop.pid"
    except ImportError:
        # Fallback if paths module not available
        return APP_DIR / ".trailing_stop.pid"


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
    """Kill any processes using our ports (5173-5178, 8000-8005)."""
    ports = list(range(5173, 5179)) + list(range(8000, 8006))
    for port in ports:
        try:
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
                        if pid != os.getpid():
                            os.kill(pid, signal.SIGKILL)
                            logger.info(f"Killed process on port {port} (PID {pid})")
                    except (ProcessLookupError, ValueError, PermissionError):
                        pass
        except Exception:
            pass


def cleanup_processes_by_name() -> None:
    """Kill related processes by name patterns."""
    patterns = [
        "main_desktop",
        "trailing_stop_web",
        "bun run dev",
        "bun.*trailing",
    ]
    for pattern in patterns:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid_str in result.stdout.strip().split('\n'):
                    try:
                        pid = int(pid_str)
                        if pid != os.getpid():
                            os.kill(pid, signal.SIGKILL)
                            logger.info(f"Killed '{pattern}' (PID {pid})")
                    except (ProcessLookupError, ValueError, PermissionError):
                        pass
        except Exception:
            pass


def cleanup_previous_instance() -> None:
    """Kill processes from previous instance (aggressive cleanup)."""
    # 1. Cleanup by PID file
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
                            pass
                        except PermissionError:
                            logger.warning(f"No permission to kill {name} (PID {pid_str})")
            pid_file.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"PID cleanup error: {e}")

    # 2. Cleanup by process name patterns
    cleanup_processes_by_name()

    # 3. Cleanup by ports
    cleanup_ports()


def remove_pid_file() -> None:
    """Remove PID file on clean shutdown."""
    try:
        get_pid_file_path().unlink(missing_ok=True)
    except Exception:
        pass


class DesktopApp:
    """Desktop application manager for Nuitka bundle."""

    def __init__(self):
        self.app_dir = APP_DIR
        self._shutdown = threading.Event()
        self._backend_ready = threading.Event()
        self._frontend_ready = threading.Event()
        self.backend_process = None
        self.frontend_process = None
        self.tray = None

    def _find_bun(self) -> Path | None:
        """Find bundled Bun executable."""
        # In Nuitka bundle, bun is next to the main executable
        bun_path = self.app_dir / "bun"
        if bun_path.exists() and os.access(bun_path, os.X_OK):
            return bun_path

        # Fallback: check if bun is in PATH
        import shutil
        system_bun = shutil.which("bun")
        if system_bun:
            return Path(system_bun)

        return None

    def _wait_for_port(self, port: int, timeout: int = 60) -> bool:
        """Wait for a port to become available."""
        start = time.time()
        while time.time() - start < timeout:
            if self._shutdown.is_set():
                return False
            try:
                urllib.request.urlopen(f"http://localhost:{port}", timeout=2)
                return True
            except Exception:
                time.sleep(0.5)
        return False

    def start_backend(self):
        """Start the Reflex backend server."""
        logger.info("Starting backend server...")

        try:
            import asyncio
            import uvicorn

            # Create event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Apply patches for production mode
            self._apply_backend_patches()

            # Import app module AFTER patches
            import trailing_stop_web.trailing_stop_web as app_module

            # Patch get_app to return our module
            import reflex.utils.prerequisites
            reflex.utils.prerequisites.get_app = lambda reload=False: app_module

            # Get ASGI app
            asgi_app = app_module.app()

            # Configure uvicorn
            config = uvicorn.Config(
                app=asgi_app,
                host="127.0.0.1",
                port=8000,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)

            logger.info("Backend starting on http://localhost:8000")

            # Run server (set ready flag after server starts)
            async def serve_and_signal():
                # Server.serve() doesn't have a "started" callback, so we use startup event
                self._backend_ready.set()
                await server.serve()

            loop.run_until_complete(serve_and_signal())

        except Exception as e:
            logger.error(f"Backend error: {e}")
            import traceback
            traceback.print_exc()

    def _apply_backend_patches(self):
        """Apply necessary patches for production mode."""
        import reflex.utils.js_runtimes

        # Only disable frontend package installation since we run Bun separately
        # Let Reflex compile normally - no _compile patch needed!
        reflex.utils.js_runtimes.install_frontend_packages = lambda *a, **kw: None

        logger.info("Applied minimal production patches (frontend handled by Bun)")

    def start_frontend(self):
        """Start the frontend dev server using Bun."""
        bun = self._find_bun()
        if not bun:
            logger.error("Bun not found! Frontend will not start.")
            return

        web_dir = self.app_dir / ".web"
        if not web_dir.exists():
            logger.error(f".web directory not found: {web_dir}")
            return

        logger.info(f"Starting frontend with Bun: {bun}")

        try:
            # First install dependencies
            logger.info("Installing frontend dependencies...")
            install_proc = subprocess.run(
                [str(bun), "install"],
                cwd=web_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            if install_proc.returncode != 0:
                logger.error(f"Bun install failed: {install_proc.stderr}")
                return

            # Start dev server
            logger.info("Starting frontend dev server...")
            self.frontend_process = subprocess.Popen(
                [str(bun), "run", "dev"],
                cwd=web_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            # Wait for frontend to be ready (Vite uses port 5173 by default)
            if self._wait_for_port(5173, timeout=60):
                self._frontend_ready.set()
                logger.info("Frontend ready on http://localhost:5173")
            else:
                logger.error("Frontend failed to start")

        except Exception as e:
            logger.error(f"Frontend error: {e}")

    def start_tray(self):
        """Start system tray icon."""
        try:
            from trailing_stop_web.tray import SystemTray
            # Use port 5173 in Nuitka bundle (Bun/Vite frontend)
            self.tray = SystemTray(on_quit=self._on_quit, app_url="http://localhost:5173")
            logger.info("System tray started")
            self.tray.run()  # Blocks
        except ImportError as e:
            logger.warning(f"System tray not available: {e}")
            # Keep running without tray
            try:
                while not self._shutdown.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    def _on_quit(self):
        """Handle quit from tray."""
        self._shutdown.set()

    def shutdown(self):
        """Shutdown all services."""
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        logger.info("Shutting down...")

        # Stop frontend
        if self.frontend_process:
            try:
                self.frontend_process.terminate()
                self.frontend_process.wait(timeout=5)
            except Exception:
                self.frontend_process.kill()

        # Stop tray
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass

        # Remove PID file on clean shutdown
        remove_pid_file()

    def run(self, open_browser: bool = True):
        """Run the application."""
        # Signal handlers
        def signal_handler(sig, frame):
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        atexit.register(self.shutdown)

        # Clean up any leftover processes from previous runs
        cleanup_previous_instance()

        # Start backend in thread
        backend_thread = threading.Thread(target=self.start_backend, daemon=True)
        backend_thread.start()

        # Start frontend in thread
        frontend_thread = threading.Thread(target=self.start_frontend, daemon=True)
        frontend_thread.start()

        # Wait for both to be ready
        logger.info("Waiting for services...")

        backend_ok = self._backend_ready.wait(timeout=30)
        frontend_ok = self._frontend_ready.wait(timeout=120)

        if not backend_ok:
            logger.error("Backend failed to start")
            self.shutdown()
            return

        if not frontend_ok:
            logger.warning("Frontend not ready, continuing anyway...")

        # Save PIDs for cleanup on next start
        pids = {"main": os.getpid()}
        if self.frontend_process and self.frontend_process.pid:
            pids["frontend"] = self.frontend_process.pid
        save_pids(pids)

        # Open browser
        if open_browser and (backend_ok or frontend_ok):
            url = "http://localhost:5173" if frontend_ok else "http://localhost:8000"
            logger.info(f"Opening browser: {url}")
            webbrowser.open(url)

        # Start tray (blocks)
        self.start_tray()

        # Cleanup
        self.shutdown()


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Trailing Stop Manager")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    app = DesktopApp()
    app.run(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
