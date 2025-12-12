"""System Tray Integration for Trailing Stop Manager.

Provides a system tray icon with menu items for:
- Opening the app in browser
- Quitting the application

Cross-platform support for Windows and macOS.
"""
import sys
import webbrowser
from pathlib import Path
from typing import Callable

from PIL import Image
import pystray
from pystray import MenuItem as Item

try:
    from trailing_stop_web.version import __version__
except ImportError:
    __version__ = "unknown"

# Hide Dock icon on macOS
if sys.platform == "darwin":
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except ImportError:
        pass  # pyobjc not installed


class SystemTray:
    """System tray manager for the Trailing Stop application."""

    def __init__(self, on_quit: Callable[[], None], app_url: str = "http://localhost:3000"):
        """Initialize system tray.

        Args:
            on_quit: Callback function to execute when user selects "Quit"
            app_url: URL to open when user selects "Open in Browser"
        """
        self.on_quit = on_quit
        self.app_url = app_url
        self.icon: pystray.Icon | None = None

    def _load_icon(self) -> Image.Image:
        """Load the application icon.

        Returns:
            PIL Image for the system tray icon

        Raises:
            FileNotFoundError: If icon file cannot be found
        """
        # Try to find icon in multiple locations
        possible_paths = [
            Path(__file__).parent / "EdgeSeeker-Icon.png",
            Path(__file__).parent.parent / "assets" / "icon.png",
            Path(__file__).parent.parent / "trailing_stop_web" / "EdgeSeeker-Icon.png",
        ]

        for icon_path in possible_paths:
            if icon_path.exists():
                return Image.open(icon_path)

        # Fallback: create simple icon programmatically
        return self._create_fallback_icon()

    def _create_fallback_icon(self) -> Image.Image:
        """Create a simple fallback icon if no icon file is found.

        Returns:
            PIL Image with simple green square
        """
        img = Image.new('RGB', (64, 64), color='#10B981')
        return img

    def _open_browser(self, icon: pystray.Icon, item: Item) -> None:
        """Open the application URL in the default browser.

        Args:
            icon: System tray icon instance (required by pystray)
            item: Menu item that was clicked (required by pystray)
        """
        webbrowser.open(self.app_url)

    def _quit_app(self, icon: pystray.Icon, item: Item) -> None:
        """Quit the application gracefully.

        Args:
            icon: System tray icon instance (required by pystray)
            item: Menu item that was clicked (required by pystray)
        """
        # Stop the tray icon
        icon.stop()

        # Call the on_quit callback to clean up the Reflex subprocess
        self.on_quit()

    def _create_menu(self) -> tuple[Item, ...]:
        """Create the system tray menu.

        Returns:
            Tuple of menu items
        """
        return (
            Item("Open in Browser", self._open_browser),
            pystray.Menu.SEPARATOR,
            Item("Quit", self._quit_app),
        )

    def run(self) -> None:
        """Run the system tray icon (blocking call).

        This method blocks until the icon is stopped (via Quit menu item).
        MUST be run in the main thread on macOS due to UI framework requirements.
        """
        # Load icon image
        icon_image = self._load_icon()

        # Create tray icon
        self.icon = pystray.Icon(
            name="Trailing Stop Manager",
            icon=icon_image,
            title=f"Trailing Stop Manager v{__version__}",
            menu=pystray.Menu(*self._create_menu()),
        )

        # Run the icon (blocking)
        self.icon.run()

    def stop(self) -> None:
        """Stop the system tray icon programmatically."""
        if self.icon:
            self.icon.stop()
