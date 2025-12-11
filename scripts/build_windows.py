#!/usr/bin/env python3
"""Build Windows application with Nuitka and create Inno Setup installer.

This script:
1. Generates icons (if not present)
2. Builds the Nuitka standalone executable
3. Creates an Inno Setup installer that includes Node.js runtime

Usage:
    python scripts/build_windows.py [--skip-icons] [--skip-nuitka] [--skip-installer]

Requirements:
    pip install nuitka ordered-set zstandard pillow numpy
    Inno Setup must be installed: https://jrsoftware.org/isinfo.php

Note: This script must be run on Windows!
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
INSTALLER_DIR = PROJECT_ROOT / "installer" / "windows"

APP_NAME = "Trailing Stop Manager"
APP_BUNDLE_NAME = "TrailingStopManager"
APP_IDENTIFIER = "com.edgeseeker.trailingstop"
APP_VERSION = "1.0.0"
APP_PUBLISHER = "EdgeSeeker"
APP_URL = "https://github.com/edgeseeker/trailing-stop-manager"


class WindowsBuilder:
    """Handles Windows build process."""

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
        return subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, check=check, shell=True)

    def check_platform(self):
        """Ensure we're on Windows."""
        if platform.system() != "Windows":
            self.log("This script must be run on Windows!", "ERROR")
            sys.exit(1)
        self.log("Platform: Windows")

    def check_inno_setup(self) -> Path:
        """Check if Inno Setup is installed."""
        possible_paths = [
            Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6" / "ISCC.exe",
        ]

        for path in possible_paths:
            if path.exists():
                self.log(f"Found Inno Setup: {path}")
                return path

        self.log("Inno Setup not found! Download from: https://jrsoftware.org/isinfo.php", "ERROR")
        sys.exit(1)

    def generate_icons(self):
        """Generate icon assets."""
        if self.skip_icons and (ASSETS_DIR / "AppIcon.ico").exists():
            self.log("Skipping icon generation (--skip-icons)")
            return

        self.log("Generating icons...")
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "generate_icons.py")], check=True)

    def clean_build(self):
        """Clean previous build artifacts."""
        self.log("Cleaning previous builds...")
        for path in [BUILD_DIR, DIST_DIR / APP_BUNDLE_NAME]:
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
            f"--output-filename={APP_BUNDLE_NAME}.exe",

            # Windows specific
            "--windows-console-mode=disable",
            f"--windows-icon-from-ico={ASSETS_DIR / 'AppIcon.ico'}",
            f"--windows-company-name={APP_PUBLISHER}",
            f"--windows-product-name={APP_NAME}",
            f"--windows-file-version={APP_VERSION}",
            f"--windows-product-version={APP_VERSION}",
            f"--windows-file-description={APP_NAME}",

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

            # Include tray icon
            f"--include-data-file={ASSETS_DIR / 'TrayIcon.ico'}=assets/TrayIcon.ico",
            f"--include-data-file={ASSETS_DIR / 'EdgeSeeker-Icon.png'}=assets/EdgeSeeker-Icon.png",

            # Optimization
            "--remove-output",

            # Entry point
            str(PROJECT_ROOT / "main.py"),
        ]

        subprocess.run(cmd, check=True)

        # Find output directory
        output_dir = None
        for d in BUILD_DIR.glob("*.dist"):
            output_dir = d
            break

        if not output_dir:
            self.log("Nuitka build failed - no .dist folder found!", "ERROR")
            sys.exit(1)

        # Move to dist
        DIST_DIR.mkdir(exist_ok=True)
        final_dir = DIST_DIR / APP_BUNDLE_NAME
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.move(str(output_dir), str(final_dir))

        self.log(f"Build created: {final_dir}")

    def download_nodejs(self) -> Path:
        """Download Node.js for Windows."""
        self.log("Downloading Node.js...")

        node_dir = BUILD_DIR / "nodejs"
        node_dir.mkdir(parents=True, exist_ok=True)

        # Node.js LTS version
        node_version = "20.10.0"
        arch = "x64"  # or win-x86 for 32-bit
        node_url = f"https://nodejs.org/dist/v{node_version}/node-v{node_version}-win-{arch}.zip"

        zip_path = node_dir / "node.zip"

        # Download
        self.log(f"Downloading from {node_url}...")
        urllib.request.urlretrieve(node_url, zip_path)

        # Extract
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(node_dir)

        # Find node directory
        node_extracted = None
        for d in node_dir.iterdir():
            if d.is_dir() and d.name.startswith("node-"):
                node_extracted = d
                break

        if not node_extracted:
            self.log("Failed to extract Node.js!", "ERROR")
            sys.exit(1)

        self.log(f"Node.js downloaded: {node_extracted}")
        return node_extracted

    def create_inno_installer(self):
        """Create Inno Setup installer."""
        if self.skip_installer:
            self.log("Skipping installer creation (--skip-installer)")
            return

        self.log("Creating Inno Setup installer...")

        iscc_path = self.check_inno_setup()

        app_dir = DIST_DIR / APP_BUNDLE_NAME
        if not app_dir.exists():
            self.log(f"App directory not found: {app_dir}", "ERROR")
            sys.exit(1)

        # Download Node.js
        node_dir = self.download_nodejs()

        INSTALLER_DIR.mkdir(parents=True, exist_ok=True)

        # Create Inno Setup script
        iss_file = INSTALLER_DIR / "setup.iss"
        iss_content = f'''#define MyAppName "{APP_NAME}"
#define MyAppVersion "{APP_VERSION}"
#define MyAppPublisher "{APP_PUBLISHER}"
#define MyAppURL "{APP_URL}"
#define MyAppExeName "{APP_BUNDLE_NAME}.exe"

[Setup]
AppId={{{{{APP_IDENTIFIER}}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
AppPublisherURL={{#MyAppURL}}
AppSupportURL={{#MyAppURL}}
AppUpdatesURL={{#MyAppURL}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
AllowNoIcons=yes
LicenseFile=
OutputDir={DIST_DIR}
OutputBaseFilename={APP_BUNDLE_NAME}-{APP_VERSION}-Setup
SetupIconFile={ASSETS_DIR / "AppIcon.ico"}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"; Flags: unchecked

[Files]
; Main application
Source: "{app_dir}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Node.js runtime
Source: "{node_dir}\\*"; DestDir: "{{app}}\\nodejs"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{group}}\\{{cm:UninstallProgram,{{#MyAppName}}}}"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "{{cm:LaunchProgram,{{#StringChange(MyAppName, '&', '&&')}}}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Add Node.js to PATH for this application
Root: HKLM; Subkey: "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{{olddata}};{{app}}\\nodejs"; Flags: preservestringtype

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Any post-install steps
  end;
end;
'''

        iss_file.write_text(iss_content)

        # Run Inno Setup compiler
        self.log("Compiling installer...")
        subprocess.run([str(iscc_path), str(iss_file)], check=True)

        self.log(f"Installer created: {DIST_DIR / f'{APP_BUNDLE_NAME}-{APP_VERSION}-Setup.exe'}")

    def cleanup(self):
        """Clean up temporary build files."""
        self.log("Cleaning up...")
        if BUILD_DIR.exists():
            shutil.rmtree(BUILD_DIR)

    def build(self):
        """Run full build process."""
        self.log("=" * 60)
        self.log(f"Building {APP_NAME} for Windows")
        self.log("=" * 60)

        self.check_platform()
        self.generate_icons()
        self.clean_build()
        self.build_nuitka()
        self.create_inno_installer()
        self.cleanup()

        elapsed = datetime.now() - self.start_time
        self.log("=" * 60)
        self.log(f"Build complete in {elapsed}")
        self.log(f"App: {DIST_DIR / APP_BUNDLE_NAME}")
        self.log(f"Installer: {DIST_DIR / f'{APP_BUNDLE_NAME}-{APP_VERSION}-Setup.exe'}")
        self.log("=" * 60)


def main():
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} for Windows")
    parser.add_argument("--skip-icons", action="store_true", help="Skip icon generation")
    parser.add_argument("--skip-nuitka", action="store_true", help="Skip Nuitka build")
    parser.add_argument("--skip-installer", action="store_true", help="Skip Inno Setup creation")
    args = parser.parse_args()

    builder = WindowsBuilder(
        skip_icons=args.skip_icons,
        skip_nuitka=args.skip_nuitka,
        skip_installer=args.skip_installer
    )
    builder.build()


if __name__ == "__main__":
    main()
