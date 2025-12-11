#!/usr/bin/env python3
"""Generate all icon formats from source PNG.

Creates:
- macOS: AppIcon.icns, TrayIconTemplate.png, TrayIconTemplate@2x.png
- Windows: AppIcon.ico, TrayIcon.ico

Usage:
    python scripts/generate_icons.py
"""
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
SOURCE_ICON = PROJECT_ROOT / "trailing_stop_web" / "EdgeSeeker-Icon.png"


def check_dependencies():
    """Check if required packages are available."""
    try:
        from PIL import Image
        import numpy as np
        return True
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Install with: pip install Pillow numpy")
        return False


def generate_ico(source_path: Path, output_path: Path, sizes: list[tuple[int, int]]):
    """Generate Windows .ico file with multiple sizes."""
    from PIL import Image

    img = Image.open(source_path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    icon_images = []
    for size in sizes:
        resized = img.resize(size, Image.Resampling.LANCZOS)
        icon_images.append(resized)

    icon_images[0].save(
        output_path,
        format='ICO',
        sizes=sizes,
        append_images=icon_images[1:] if len(icon_images) > 1 else []
    )
    print(f"  Created: {output_path.name}")


def generate_icns(source_path: Path, output_path: Path):
    """Generate macOS .icns file using iconutil."""
    from PIL import Image

    if platform.system() != "Darwin":
        print("  Skipping .icns generation (not on macOS)")
        return False

    iconset_dir = output_path.parent / "AppIcon.iconset"
    iconset_dir.mkdir(exist_ok=True)

    img = Image.open(source_path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    icon_sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    for size, filename in icon_sizes:
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(iconset_dir / filename)

    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_path)],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"  Error creating .icns: {result.stderr}")
        return False

    import shutil
    shutil.rmtree(iconset_dir)

    print(f"  Created: {output_path.name}")
    return True


def generate_tray_template(source_path: Path, output_dir: Path):
    """Generate macOS tray template icons (white on transparent)."""
    from PIL import Image
    import numpy as np

    img = Image.open(source_path).convert('RGBA')
    data = np.array(img)

    alpha = data[:, :, 3]
    mask = alpha > 0
    data[mask, 0] = 255
    data[mask, 1] = 255
    data[mask, 2] = 255

    white_img = Image.fromarray(data, 'RGBA')

    white_img.resize((22, 22), Image.Resampling.LANCZOS).save(
        output_dir / "TrayIconTemplate.png"
    )
    white_img.resize((44, 44), Image.Resampling.LANCZOS).save(
        output_dir / "TrayIconTemplate@2x.png"
    )

    print("  Created: TrayIconTemplate.png")
    print("  Created: TrayIconTemplate@2x.png")


def main():
    print("=" * 50)
    print("Icon Generator for Trailing Stop Manager")
    print("=" * 50)

    if not check_dependencies():
        sys.exit(1)

    if not SOURCE_ICON.exists():
        print(f"Error: Source icon not found: {SOURCE_ICON}")
        sys.exit(1)

    ASSETS_DIR.mkdir(exist_ok=True)

    print(f"\nSource: {SOURCE_ICON}")
    print(f"Output: {ASSETS_DIR}/\n")

    print("[1/4] Generating Windows App Icon...")
    generate_ico(
        SOURCE_ICON,
        ASSETS_DIR / "AppIcon.ico",
        [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )

    print("[2/4] Generating Windows Tray Icon...")
    generate_ico(SOURCE_ICON, ASSETS_DIR / "TrayIcon.ico", [(16, 16), (32, 32)])

    print("[3/4] Generating macOS App Icon...")
    generate_icns(SOURCE_ICON, ASSETS_DIR / "AppIcon.icns")

    print("[4/4] Generating macOS Tray Template Icons...")
    generate_tray_template(SOURCE_ICON, ASSETS_DIR)

    print("\n" + "=" * 50)
    print("Done! Icons generated in assets/")
    print("=" * 50)


if __name__ == "__main__":
    main()
