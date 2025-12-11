#!/usr/bin/env python3
"""Build macOS application with Nuitka and create .pkg installer.

This script:
1. Generates icons (if not present)
2. Builds the Nuitka standalone app bundle
3. Creates a .pkg installer that includes Bun runtime

Usage:
    python scripts/build_mac.py [--skip-icons] [--skip-nuitka] [--skip-installer]

Requirements:
    pip install nuitka ordered-set zstandard pillow numpy
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
INSTALLER_DIR = PROJECT_ROOT / "installer" / "mac"

APP_NAME = "Trailing Stop Manager"
APP_BUNDLE_NAME = "TrailingStopManager"
APP_IDENTIFIER = "com.edgeseeker.trailingstop"
APP_VERSION = "1.0.0"


class MacBuilder:
    """Handles macOS build process."""

    def __init__(self, skip_icons: bool = False, skip_nuitka: bool = False, skip_installer: bool = False):
        self.skip_icons = skip_icons
        self.skip_nuitka = skip_nuitka
        self.skip_installer = skip_installer
        self.start_time = datetime.now()

    def log(self, msg: str, level: str = "INFO"):
        """Log with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {msg}")

    def run(self, cmd: list[str], cwd: Path = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run command."""
        self.log(f"Running: {' '.join(cmd[:3])}...")
        return subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, check=check, capture_output=False)

    def check_platform(self):
        """Ensure we're on macOS."""
        if platform.system() != "Darwin":
            self.log("This script must be run on macOS!", "ERROR")
            sys.exit(1)
        self.log("Platform: macOS")

    def generate_icons(self):
        """Generate icon assets."""
        if self.skip_icons and (ASSETS_DIR / "AppIcon.icns").exists():
            self.log("Skipping icon generation (--skip-icons)")
            return

        self.log("Generating icons...")
        self.run([sys.executable, str(PROJECT_ROOT / "scripts" / "generate_icons.py")])

    def clean_build(self):
        """Clean previous build artifacts."""
        self.log("Cleaning previous builds...")
        for path in [BUILD_DIR, DIST_DIR / f"{APP_BUNDLE_NAME}.app"]:
            if path.exists():
                shutil.rmtree(path)
                self.log(f"  Removed: {path.name}")

    def build_nuitka(self):
        """Build with Nuitka."""
        if self.skip_nuitka:
            self.log("Skipping Nuitka build (--skip-nuitka)")
            return

        self.log("Building with Nuitka (this takes 10-30 minutes)...")

        # Get plotly path for validators data
        import plotly
        plotly_path = Path(plotly.__path__[0])

        cmd = [
            sys.executable, "-m", "nuitka",
            "--standalone",
            "--assume-yes-for-downloads",
            f"--output-dir={BUILD_DIR}",

            # macOS App Bundle
            "--macos-create-app-bundle",
            f"--macos-app-name={APP_NAME}",
            f"--macos-app-icon={ASSETS_DIR / 'AppIcon.icns'}",
            "--macos-app-mode=ui-element",  # No dock icon (tray app)

            # Include packages
            "--include-package=trailing_stop_web",
            "--include-package=reflex",
            "--include-package=uvicorn",
            "--include-package=pystray",
            "--include-package=PIL",
            "--include-package=plotly",
            "--include-package=ib_insync",

            # Include data files
            f"--include-data-dir={PROJECT_ROOT / 'trailing_stop_web'}=trailing_stop_web",
            f"--include-data-dir={PROJECT_ROOT / '.web'}=.web",
            f"--include-data-file={PROJECT_ROOT / 'rxconfig.py'}=rxconfig.py",
            f"--include-data-dir={plotly_path / 'validators'}=plotly/validators",

            # Include tray icons
            f"--include-data-file={ASSETS_DIR / 'TrayIconTemplate.png'}=assets/TrayIconTemplate.png",
            f"--include-data-file={ASSETS_DIR / 'TrayIconTemplate@2x.png'}=assets/TrayIconTemplate@2x.png",
            f"--include-data-file={ASSETS_DIR / 'EdgeSeeker-Icon.png'}=assets/EdgeSeeker-Icon.png",

            # Optimization
            "--remove-output",

            # Entry point
            str(PROJECT_ROOT / "main.py"),
        ]

        self.run(cmd)

        # Find and rename output
        output_app = None
        for app in BUILD_DIR.glob("*.app"):
            output_app = app
            break

        if not output_app:
            self.log("Nuitka build failed - no .app found!", "ERROR")
            sys.exit(1)

        # Move to dist
        DIST_DIR.mkdir(exist_ok=True)
        final_app = DIST_DIR / f"{APP_BUNDLE_NAME}.app"
        if final_app.exists():
            shutil.rmtree(final_app)
        shutil.move(str(output_app), str(final_app))

        self.log(f"App bundle created: {final_app}")

    def download_bun(self) -> Path:
        """Download Bun runtime for macOS."""
        self.log("Downloading Bun runtime...")

        bun_dir = BUILD_DIR / "bun"
        bun_dir.mkdir(parents=True, exist_ok=True)

        # Detect architecture
        arch = "aarch64" if platform.machine() == "arm64" else "x64"
        bun_url = f"https://github.com/oven-sh/bun/releases/latest/download/bun-darwin-{arch}.zip"

        zip_path = bun_dir / "bun.zip"

        # Download
        self.run(["curl", "-L", "-o", str(zip_path), bun_url])

        # Extract
        self.run(["unzip", "-o", str(zip_path), "-d", str(bun_dir)])

        # Find bun binary
        bun_binary = None
        for f in bun_dir.rglob("bun"):
            if f.is_file() and os.access(f, os.X_OK):
                bun_binary = f
                break

        if not bun_binary:
            self.log("Failed to find Bun binary!", "ERROR")
            sys.exit(1)

        self.log(f"Bun downloaded: {bun_binary}")
        return bun_binary

    def create_pkg_installer(self):
        """Create .pkg installer."""
        if self.skip_installer:
            self.log("Skipping installer creation (--skip-installer)")
            return

        self.log("Creating .pkg installer...")

        INSTALLER_DIR.mkdir(parents=True, exist_ok=True)

        app_path = DIST_DIR / f"{APP_BUNDLE_NAME}.app"
        if not app_path.exists():
            self.log(f"App bundle not found: {app_path}", "ERROR")
            sys.exit(1)

        # Download Bun
        bun_binary = self.download_bun()

        # Create package root
        pkg_root = BUILD_DIR / "pkg_root"
        if pkg_root.exists():
            shutil.rmtree(pkg_root)

        # Structure: /Applications/Trailing Stop Manager.app
        app_dest = pkg_root / "Applications" / f"{APP_NAME}.app"
        app_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(app_path, app_dest)

        # Add Bun to app bundle
        bun_dest = app_dest / "Contents" / "MacOS" / "bun"
        shutil.copy2(bun_binary, bun_dest)
        os.chmod(bun_dest, 0o755)

        # Create scripts directory for post-install
        scripts_dir = BUILD_DIR / "scripts"
        scripts_dir.mkdir(exist_ok=True)

        # Post-install script: setup Bun in PATH for the app
        postinstall = scripts_dir / "postinstall"
        postinstall.write_text(f'''#!/bin/bash
# Post-install script for {APP_NAME}

APP_PATH="/Applications/{APP_NAME}.app"
BUN_PATH="$APP_PATH/Contents/MacOS/bun"

# Make bun executable
chmod +x "$BUN_PATH"

# Create symlink in /usr/local/bin (optional, for CLI access)
# mkdir -p /usr/local/bin
# ln -sf "$BUN_PATH" /usr/local/bin/bun-trailing-stop

echo "{APP_NAME} installed successfully!"
exit 0
''')
        os.chmod(postinstall, 0o755)

        # Build component package
        component_pkg = BUILD_DIR / "component.pkg"
        self.run([
            "pkgbuild",
            "--root", str(pkg_root),
            "--scripts", str(scripts_dir),
            "--identifier", APP_IDENTIFIER,
            "--version", APP_VERSION,
            "--install-location", "/",
            str(component_pkg)
        ])

        # Create distribution.xml
        distribution_xml = INSTALLER_DIR / "distribution.xml"
        distribution_xml.write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>{APP_NAME}</title>
    <organization>{APP_IDENTIFIER}</organization>
    <domains enable_localSystem="true"/>
    <options customize="never" require-scripts="true" rootVolumeOnly="true"/>

    <welcome file="welcome.html"/>
    <conclusion file="conclusion.html"/>

    <choices-outline>
        <line choice="default">
            <line choice="{APP_IDENTIFIER}"/>
        </line>
    </choices-outline>

    <choice id="default"/>
    <choice id="{APP_IDENTIFIER}" visible="false">
        <pkg-ref id="{APP_IDENTIFIER}"/>
    </choice>

    <pkg-ref id="{APP_IDENTIFIER}" version="{APP_VERSION}" onConclusion="none">component.pkg</pkg-ref>
</installer-gui-script>
''')

        # Create welcome.html
        welcome_html = INSTALLER_DIR / "welcome.html"
        welcome_html.write_text(f'''<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; }}
        h1 {{ color: #f5a623; }}
    </style>
</head>
<body>
    <h1>{APP_NAME}</h1>
    <p>This installer will install {APP_NAME} on your computer.</p>
    <p>The application includes:</p>
    <ul>
        <li>Trailing Stop Manager application</li>
        <li>Bun runtime (for frontend)</li>
    </ul>
    <p>Click "Continue" to proceed.</p>
</body>
</html>
''')

        # Create conclusion.html
        conclusion_html = INSTALLER_DIR / "conclusion.html"
        conclusion_html.write_text(f'''<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; }}
        h1 {{ color: #4CAF50; }}
    </style>
</head>
<body>
    <h1>Installation Complete!</h1>
    <p>{APP_NAME} has been installed successfully.</p>
    <p>You can find it in your Applications folder.</p>
    <p><strong>Note:</strong> Make sure TWS or IB Gateway is running before starting the app.</p>
</body>
</html>
''')

        # Build final product package
        final_pkg = DIST_DIR / f"{APP_BUNDLE_NAME}-{APP_VERSION}.pkg"
        self.run([
            "productbuild",
            "--distribution", str(distribution_xml),
            "--resources", str(INSTALLER_DIR),
            "--package-path", str(BUILD_DIR),
            str(final_pkg)
        ])

        self.log(f"Installer created: {final_pkg}")

    def cleanup(self):
        """Clean up temporary build files."""
        self.log("Cleaning up...")
        if BUILD_DIR.exists():
            shutil.rmtree(BUILD_DIR)

    def build(self):
        """Run full build process."""
        self.log("=" * 60)
        self.log(f"Building {APP_NAME} for macOS")
        self.log("=" * 60)

        self.check_platform()
        self.generate_icons()
        self.clean_build()
        self.build_nuitka()
        self.create_pkg_installer()
        self.cleanup()

        elapsed = datetime.now() - self.start_time
        self.log("=" * 60)
        self.log(f"Build complete in {elapsed}")
        self.log(f"App: {DIST_DIR / f'{APP_BUNDLE_NAME}.app'}")
        self.log(f"Installer: {DIST_DIR / f'{APP_BUNDLE_NAME}-{APP_VERSION}.pkg'}")
        self.log("=" * 60)


def main():
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} for macOS")
    parser.add_argument("--skip-icons", action="store_true", help="Skip icon generation")
    parser.add_argument("--skip-nuitka", action="store_true", help="Skip Nuitka build")
    parser.add_argument("--skip-installer", action="store_true", help="Skip .pkg creation")
    args = parser.parse_args()

    builder = MacBuilder(
        skip_icons=args.skip_icons,
        skip_nuitka=args.skip_nuitka,
        skip_installer=args.skip_installer
    )
    builder.build()


if __name__ == "__main__":
    main()
