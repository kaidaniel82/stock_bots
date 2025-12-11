#!/usr/bin/env python3
"""Deploy script for Trailing Stop Manager.

Builds a standalone desktop application using:
1. reflex export - Static frontend + production backend
2. nuitka - Compile Python to standalone executable

Usage:
    python scripts/deploy.py [--target macos|windows] [--clean] [--skip-export]

Requirements:
    pip install nuitka ordered-set zstandard

Output:
    dist/TrailingStopManager.app (macOS)
    dist/TrailingStopManager.exe (Windows)
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime


# Configuration
APP_NAME = "TrailingStopManager"
PROJECT_ROOT = Path(__file__).parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
EXPORT_DIR = PROJECT_ROOT / ".web" / "_static"


class DeployError(Exception):
    """Deployment error."""
    pass


class Deployer:
    """Handles the deployment process."""

    def __init__(self, target: str, skip_export: bool = False, verbose: bool = False):
        self.target = target or self._detect_platform()
        self.skip_export = skip_export
        self.verbose = verbose
        self.start_time = datetime.now()

    def _detect_platform(self) -> str:
        """Detect current platform."""
        system = platform.system().lower()
        if system == "darwin":
            return "macos"
        elif system == "windows":
            return "windows"
        else:
            return "linux"

    def _log(self, msg: str, level: str = "INFO") -> None:
        """Log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {msg}")

    def _run(self, cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run command with logging."""
        if self.verbose:
            self._log(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or PROJECT_ROOT,
                check=check,
                capture_output=not self.verbose,
                text=True,
            )
            return result
        except subprocess.CalledProcessError as e:
            self._log(f"Command failed: {e.stderr}", "ERROR")
            raise DeployError(f"Command failed: {' '.join(cmd)}")

    def _check_dependencies(self) -> None:
        """Check if required tools are installed."""
        self._log("Checking dependencies...")

        # Check Python
        if sys.version_info < (3, 10):
            raise DeployError("Python 3.10+ required")

        # Check nuitka
        try:
            self._run([sys.executable, "-m", "nuitka", "--version"])
        except (DeployError, FileNotFoundError):
            raise DeployError("Nuitka not installed. Run: pip install nuitka ordered-set zstandard")

        # Check reflex
        try:
            self._run([sys.executable, "-m", "reflex", "--version"])
        except (DeployError, FileNotFoundError):
            raise DeployError("Reflex not installed. Run: pip install reflex")

        # Check C compiler (for nuitka)
        if self.target == "macos":
            try:
                self._run(["clang", "--version"])
            except FileNotFoundError:
                raise DeployError("Xcode Command Line Tools required. Run: xcode-select --install")
        elif self.target == "windows":
            # Nuitka will use MSVC or MinGW
            pass

        self._log("All dependencies OK")

    def _clean_build_dirs(self) -> None:
        """Clean previous build artifacts."""
        self._log("Cleaning build directories...")

        dirs_to_clean = [
            BUILD_DIR,
            DIST_DIR,
            PROJECT_ROOT / f"{APP_NAME}.build",
            PROJECT_ROOT / f"{APP_NAME}.dist",
            PROJECT_ROOT / f"{APP_NAME}.onefile-build",
        ]

        for dir_path in dirs_to_clean:
            if dir_path.exists():
                self._log(f"  Removing {dir_path.name}/")
                shutil.rmtree(dir_path)

    def _export_reflex(self) -> None:
        """Export Reflex app for production."""
        if self.skip_export:
            self._log("Skipping Reflex export (--skip-export)")
            return

        self._log("Exporting Reflex app...")

        # Run reflex export
        self._run([
            sys.executable, "-m", "reflex", "export",
            "--no-zip",
            "--env", "prod",
        ])

        # Verify export
        frontend_dir = PROJECT_ROOT / "frontend.zip" if not (PROJECT_ROOT / ".web" / "_static").exists() else PROJECT_ROOT / ".web" / "_static"
        if not (PROJECT_ROOT / ".web").exists():
            raise DeployError("Reflex export failed - .web directory not found")

        self._log("Reflex export complete")

    def _create_production_entry_point(self) -> Path:
        """Create production entry point that doesn't use hot-reload."""
        self._log("Creating production entry point...")

        prod_main = BUILD_DIR / "main_prod.py"
        BUILD_DIR.mkdir(parents=True, exist_ok=True)

        # Read the original main.py and modify for production
        original_main = PROJECT_ROOT / "main.py"

        prod_code = '''#!/usr/bin/env python3
"""Production entry point for Trailing Stop Manager.

Runs Granian directly (no Node.js) with static frontend mounting.
"""
import multiprocessing
import logging
import os
import signal
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Set production environment BEFORE importing reflex
# IMPORTANT: Internal Reflex env vars need double-underscore prefix!
os.environ["REFLEX_ENV_MODE"] = "prod"
os.environ["__REFLEX_SKIP_COMPILE"] = "true"  # Skip frontend compilation
os.environ["__REFLEX_MOUNT_FRONTEND_COMPILED_APP"] = "true"  # Serve static files

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_app_dir() -> Path:
    """Get the application directory (handles Nuitka + dev mode).

    Für Nuitka macOS App-Bundles:
    - __compiled__.containing_dir zeigt auf das Parent-Verzeichnis des .app-Bundles
    - sys.executable zeigt direkt auf Contents/MacOS/TrailingStopManager
    - .web/ wird nach Contents/MacOS/.web/ kopiert

    Die zuverlässigste Methode ist sys.executable.parent für macOS-Bundles.
    """
    # Debug logging
    logger.info(f"sys.executable = {sys.executable}")
    logger.info(f"os.getcwd() before chdir = {os.getcwd()}")

    compiled_obj = globals().get("__compiled__", None)

    if compiled_obj is not None:
        logger.info(f"__compiled__ present: {compiled_obj}")
        macos_bundle = getattr(compiled_obj, "macos_bundle_mode", False)
        logger.info(f"macos_bundle_mode = {macos_bundle}")

    # 1. Beste Methode für Nuitka: sys.executable.parent
    # Dies funktioniert für ALLE Nuitka-Builds (standalone, onefile, macos_bundle)
    exe_path = Path(sys.executable).resolve()
    exe_dir = exe_path.parent

    # Für macOS App-Bundles: exe_dir ist Contents/MacOS/
    if (exe_dir / ".web").exists():
        logger.info(f"Using app dir from sys.executable.parent: {exe_dir}")
        return exe_dir

    # 2. Falls .web nicht direkt neben exe gefunden: erweiterte Suche
    # (für edge cases oder andere Bundle-Strukturen)
    candidates = [
        exe_dir,
        exe_dir / "MacOS",
        exe_dir.parent / "MacOS",
        exe_dir.parent / "Resources",  # Alternative macOS-Bundle-Location
    ]

    # Auch im containing_dir suchen falls vorhanden
    if compiled_obj is not None:
        containing_dir = getattr(compiled_obj, "containing_dir", None)
        if containing_dir:
            base = Path(containing_dir).resolve()
            candidates.extend([
                base,
                base / "MacOS",
            ])
            # Für macOS: Suche in *.app/Contents/MacOS/ innerhalb von containing_dir
            for app_bundle in base.glob("*.app"):
                macos_path = app_bundle / "Contents" / "MacOS"
                if macos_path.exists():
                    candidates.append(macos_path)

    # Deduplizieren und prüfen
    seen = set()
    unique_candidates = []
    for c in candidates:
        resolved = c.resolve() if c.exists() else c
        if str(resolved) not in seen:
            seen.add(str(resolved))
            unique_candidates.append(resolved)

    for cand in unique_candidates:
        if cand.exists() and (cand / ".web").exists():
            logger.info(f"Using app dir from extended search: {cand}")
            return cand

    logger.warning(
        f"Could not find .web in any expected location. "
        f"exe_dir={exe_dir}, tried: {[str(c) for c in unique_candidates]}"
    )

    # 3. Fallback für Dev-Mode (kein __compiled__ vorhanden)
    if compiled_obj is None:
        dev_path = Path(__file__).parent.parent
        logger.info(f"Using dev mode path: {dev_path}")
        return dev_path

    # Letzter Fallback: exe_dir
    return exe_dir


# CRITICAL: Change to app directory IMMEDIATELY - before any imports
# This is necessary because Reflex's StaticFiles validation happens at import time
APP_DIR = get_app_dir()
os.chdir(APP_DIR)
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
logger.info(f"Working directory set to: {APP_DIR}")


class ProductionApp:
    """Production application manager."""

    def __init__(self):
        self.app_dir = APP_DIR  # Use globally set app dir
        self._shutdown_initiated = threading.Event()
        self._app_ready = threading.Event()
        self.tray = None
        self._server_thread = None

    def _wait_for_ready(self, url: str, timeout: int = 60) -> bool:
        """Wait for service to be ready."""
        start = time.time()
        while time.time() - start < timeout:
            if self._shutdown_initiated.is_set():
                return False
            try:
                urllib.request.urlopen(url, timeout=2)
                return True
            except Exception:
                time.sleep(1)
        return False

    def _run_uvicorn_server(self) -> None:
        """Run the uvicorn server directly (no subprocess, no Node.js).

        Uses uvicorn instead of Granian because uvicorn supports
        running in a background thread when properly configured.
        """
        try:
            import asyncio
            import uvicorn

            # CRITICAL: Create event loop BEFORE importing reflex modules
            # Reflex uses asyncio internally and needs an event loop present
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Working directory is already set at module load time
            logger.info(f"Starting uvicorn server (cwd: {os.getcwd()})...")

            # MONKEY-PATCH: Disable ALL frontend build/compile functions
            # This is more reliable than env vars which may be read before we set them

            # 1. Disable App._compile to prevent build process
            import reflex.app
            reflex.app.App._compile = lambda self, *args, **kwargs: None

            # 2. Disable install_frontend_packages to prevent npm/bun install
            import reflex.utils.js_runtimes
            reflex.utils.js_runtimes.install_frontend_packages = lambda *args, **kwargs: None

            # 3. Disable any other prerequisite functions that might call npm/bun
            import reflex.utils.prerequisites
            if hasattr(reflex.utils.prerequisites, 'initialize_frontend_dependencies'):
                reflex.utils.prerequisites.initialize_frontend_dependencies = lambda *args, **kwargs: None

            logger.info("Disabled frontend compilation via monkey-patches")

            # Import the app module FIRST (before calling app factory)
            # This module is compiled into the Nuitka binary
            import trailing_stop_web.trailing_stop_web as app_module

            # 4. CRITICAL: Monkey-patch get_app() to return the pre-imported module
            # config.app_module is read-only, so we patch the function directly
            # This bypasses dynamic __import__() which doesn't work in Nuitka
            def patched_get_app(reload: bool = False):
                return app_module
            reflex.utils.prerequisites.get_app = patched_get_app

            # Also mark the app name as valid to skip filesystem checks
            from reflex.config import get_config
            rx_config = get_config()
            rx_config._app_name_is_valid = True
            logger.info("Patched get_app() to return pre-imported module")

            # Now call the app factory
            asgi_app = app_module.app()

            uvicorn_config = uvicorn.Config(
                app=asgi_app,
                host="0.0.0.0",
                port=8000,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(uvicorn_config)

            # Run server (event loop is already set above)
            loop.run_until_complete(server.serve())
        except Exception as e:
            logger.error(f"Uvicorn server error: {e}")

    def start_server(self) -> bool:
        """Start the uvicorn server in a background thread."""
        logger.info("Starting server...")

        self._server_thread = threading.Thread(
            target=self._run_uvicorn_server,
            daemon=True
        )
        self._server_thread.start()

        # Wait for server to be ready (port 8000 now, not 3000)
        if self._wait_for_ready("http://localhost:8000", timeout=60):
            logger.info("Server ready!")
            self._app_ready.set()
            return True
        else:
            logger.error("Server failed to start within timeout")
            return False

    def start_tray(self) -> None:
        """Start system tray icon."""
        try:
            from trailing_stop_web.tray import SystemTray
            self.tray = SystemTray(on_quit=self._on_quit)
            logger.info("System tray started")
            self.tray.run()
        except ImportError as e:
            logger.warning(f"System tray not available: {e}")
            # Keep running without tray
            try:
                while not self._shutdown_initiated.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    def _on_quit(self) -> None:
        """Handle quit from tray."""
        self._shutdown_initiated.set()

    def shutdown(self) -> None:
        """Shutdown all services."""
        if self._shutdown_initiated.is_set():
            return
        self._shutdown_initiated.set()
        logger.info("Shutting down...")

        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass

    def run(self, open_browser: bool = True) -> None:
        """Run the application."""
        # Setup signal handlers
        def signal_handler(sig, frame):
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Start server
            if not self.start_server():
                logger.error("Failed to start server")
                return

            # Open browser (now port 8000)
            if open_browser:
                logger.info("Opening browser...")
                webbrowser.open("http://localhost:8000")

            # Start tray (blocks until quit)
            self.start_tray()

        finally:
            self.shutdown()


def main():
    """Main entry point."""
    import argparse
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="Trailing Stop Manager")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    app = ProductionApp()
    app.run(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
'''

        prod_main.write_text(prod_code)
        self._log(f"Created {prod_main}")

        return prod_main

    def _build_nuitka(self, entry_point: Path) -> Path:
        """Build standalone executable with Nuitka."""
        self._log(f"Building with Nuitka for {self.target}...")

        # Get plotly package path dynamically
        import plotly
        plotly_path = Path(plotly.__path__[0])

        # Base nuitka command
        cmd = [
            sys.executable, "-m", "nuitka",
            "--standalone",
            "--assume-yes-for-downloads",  # Auto-download dependencies
            f"--output-dir={BUILD_DIR}",
            f"--output-filename={APP_NAME}",

            # Include packages
            "--include-package=trailing_stop_web",
            "--include-package=reflex",
            "--include-package=uvicorn",
            "--include-package=pystray",
            "--include-package=PIL",
            "--include-package=plotly",

            # Include data files
            f"--include-data-dir={PROJECT_ROOT / 'trailing_stop_web'}=trailing_stop_web",

            # Include plotly validators JSON (required at runtime)
            f"--include-data-dir={plotly_path / 'validators'}=plotly/validators",

            # Optimization
            "--remove-output",
        ]

        # Platform-specific options
        if self.target == "macos":
            cmd.extend([
                "--macos-create-app-bundle",
                f"--macos-app-name={APP_NAME}",
                "--macos-app-mode=ui-element",  # No dock icon
            ])

            # Add icon if exists
            icon_path = PROJECT_ROOT / "trailing_stop_web" / "EdgeSeeker-Icon.png"
            if icon_path.exists():
                # Convert PNG to ICNS for macOS (would need iconutil)
                pass

        elif self.target == "windows":
            cmd.extend([
                "--windows-console-mode=disable",  # No console window
            ])

            # Add icon if exists
            icon_path = PROJECT_ROOT / "assets" / "icon.ico"
            if icon_path.exists():
                cmd.append(f"--windows-icon-from-ico={icon_path}")

        # Add entry point
        cmd.append(str(entry_point))

        # Run nuitka (this takes a while)
        self._log("This may take 10-30 minutes...")
        self._run(cmd)

        # Find output
        if self.target == "macos":
            # Nuitka creates main_prod.app when entry point is main_prod.py
            output = BUILD_DIR / "main_prod.app"
            if not output.exists():
                output = BUILD_DIR / f"{APP_NAME}.app"
        else:
            output = BUILD_DIR / f"{APP_NAME}.dist" / f"{APP_NAME}.exe"

        if not output.exists():
            # Check alternative locations - look for .app bundles first
            for pattern in BUILD_DIR.glob("**/*.app"):
                if pattern.is_dir():
                    output = pattern
                    break

        if not output.exists() or not output.is_dir():
            raise DeployError(f"Build output not found at {output}")

        self._log(f"Build complete: {output}")
        return output

    def _copy_assets(self, output: Path) -> None:
        """Copy additional assets to the build."""
        self._log("Copying assets...")

        if self.target == "macos" and output.suffix == ".app":
            resources_dir = output / "Contents" / "Resources"
            # .web must be in MacOS folder (where binary runs from)
            macos_dir = output / "Contents" / "MacOS"
        else:
            resources_dir = output.parent if output.is_file() else output
            macos_dir = resources_dir

        resources_dir.mkdir(parents=True, exist_ok=True)

        # Copy web export to MacOS folder (where binary is located)
        web_export = PROJECT_ROOT / ".web"
        if web_export.exists():
            dest = macos_dir / ".web"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(web_export, dest)
            self._log(f"  Copied .web/")

        # Copy icon
        icon_src = PROJECT_ROOT / "trailing_stop_web" / "EdgeSeeker-Icon.png"
        if icon_src.exists():
            shutil.copy2(icon_src, resources_dir / "EdgeSeeker-Icon.png")
            self._log(f"  Copied icon")

        # Copy rxconfig.py (needed by Reflex at runtime for app_name)
        rxconfig_src = PROJECT_ROOT / "rxconfig.py"
        if rxconfig_src.exists():
            shutil.copy2(rxconfig_src, macos_dir / "rxconfig.py")
            self._log(f"  Copied rxconfig.py")

    def _create_dist(self, build_output: Path) -> Path:
        """Create final distribution."""
        self._log("Creating distribution...")

        DIST_DIR.mkdir(parents=True, exist_ok=True)

        if self.target == "macos":
            dist_path = DIST_DIR / f"{APP_NAME}.app"
            if dist_path.exists():
                shutil.rmtree(dist_path)
            shutil.copytree(build_output, dist_path)
        else:
            dist_path = DIST_DIR / f"{APP_NAME}.exe"
            shutil.copy2(build_output, dist_path)

        self._log(f"Distribution created: {dist_path}")
        return dist_path

    def _cleanup(self) -> None:
        """Clean up temporary build files."""
        self._log("Cleaning up temporary files...")

        temp_dirs = [
            BUILD_DIR,
            PROJECT_ROOT / f"{APP_NAME}.build",
            PROJECT_ROOT / f"{APP_NAME}.onefile-build",
        ]

        for dir_path in temp_dirs:
            if dir_path.exists():
                shutil.rmtree(dir_path)
                self._log(f"  Removed {dir_path.name}/")

        # Keep .web for now as it's needed at runtime
        self._log("Cleanup complete")

    def deploy(self) -> Path:
        """Run the full deployment process."""
        self._log(f"Starting deployment for {self.target}...")
        self._log(f"Project root: {PROJECT_ROOT}")

        try:
            # Step 1: Check dependencies
            self._check_dependencies()

            # Step 2: Clean previous builds
            self._clean_build_dirs()

            # Step 3: Export Reflex
            self._export_reflex()

            # Step 4: Create production entry point
            entry_point = self._create_production_entry_point()

            # Step 5: Build with Nuitka
            build_output = self._build_nuitka(entry_point)

            # Step 6: Copy assets
            self._copy_assets(build_output)

            # Step 7: Create distribution
            dist_path = self._create_dist(build_output)

            # Step 8: Cleanup
            self._cleanup()

            # Done
            elapsed = datetime.now() - self.start_time
            self._log(f"Deployment complete in {elapsed}")
            self._log(f"Output: {dist_path}")

            return dist_path

        except DeployError as e:
            self._log(str(e), "ERROR")
            raise
        except Exception as e:
            self._log(f"Unexpected error: {e}", "ERROR")
            raise DeployError(str(e))


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Trailing Stop Manager as standalone application"
    )
    parser.add_argument(
        "--target",
        choices=["macos", "windows", "linux"],
        help="Target platform (default: auto-detect)"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build directories only"
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Skip Reflex export step"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    deployer = Deployer(
        target=args.target,
        skip_export=args.skip_export,
        verbose=args.verbose,
    )

    if args.clean:
        deployer._clean_build_dirs()
        print("Build directories cleaned.")
        return

    try:
        dist_path = deployer.deploy()
        print(f"\n✅ Success! Application built at: {dist_path}")
    except DeployError as e:
        print(f"\n❌ Deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
