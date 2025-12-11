# Desktop Deployment Guide

This guide explains how to run the Trailing Stop Manager as a desktop application with system tray integration.

## Architecture

The desktop deployment consists of:

1. **main.py**: Entry point that manages the application lifecycle
2. **trailing_stop_web/tray.py**: System tray integration (cross-platform)
3. **EdgeSeeker-Icon.png**: Application icon for the system tray

## Installation

Install the additional dependencies required for desktop deployment:

```bash
pip install -r requirements.txt
```

This includes:
- `pystray>=0.19` - System tray integration
- `Pillow>=10.0` - Image handling for the tray icon

## Running the Application

### Standard Mode (with System Tray)

```bash
python main.py
```

This will:
1. Start the Reflex application
2. Show a system tray icon
3. Auto-open your browser to http://localhost:3000

### Command Line Options

```bash
# Start without system tray (console only)
python main.py --no-tray

# Start without auto-opening browser
python main.py --no-browser

# Both options combined
python main.py --no-tray --no-browser
```

## System Tray Features

When running with system tray, you can:

- **Open in Browser**: Click to open http://localhost:3000 in your default browser
- **Quit**: Gracefully shutdown the application

## Platform Support

The application is tested on:
- **macOS**: Uses EdgeSeeker-Icon.png for the tray icon
- **Windows**: Uses EdgeSeeker-Icon.png for the tray icon

## Graceful Shutdown

The application handles shutdown gracefully:

1. Via system tray "Quit" menu
2. Via `Ctrl+C` in terminal
3. Via `SIGTERM` signal

All methods ensure:
- The Reflex subprocess is terminated properly
- The system tray icon is removed
- Resources are cleaned up

## File Structure

```
stock_bots/
├── main.py                              # Entry point
├── trailing_stop_web/
│   ├── tray.py                          # System tray integration
│   ├── EdgeSeeker-Icon.png              # Application icon
│   └── ...                              # Other app files
└── requirements.txt                     # Dependencies
```

## Troubleshooting

### System Tray Icon Not Showing

If the system tray icon doesn't appear:

1. Check that `pystray` is installed: `pip show pystray`
2. Try running with `--no-tray` flag to verify the app works
3. Check console output for error messages

### Icon Not Loading

The tray integration tries multiple paths for the icon:
1. `trailing_stop_web/EdgeSeeker-Icon.png`
2. `assets/icon.png`

If no icon is found, a simple green fallback icon is generated.

### Port Already in Use

If port 3000 is already in use, Reflex will fail to start. Check if another instance is running:

```bash
# macOS/Linux
lsof -i :3000

# Windows
netstat -ano | findstr :3000
```

## Development vs Production

### Development Mode
```bash
# Traditional Reflex development (hot reload)
reflex run
```

### Desktop Mode
```bash
# Desktop deployment with system tray
python main.py
```

The desktop mode is ideal for:
- End users who want a simple "double-click" experience
- Running the app in the background
- Quick access via system tray
- Clean shutdown without terminal access

## Creating a Standalone Executable (Optional)

For distribution to users without Python, you can create a standalone executable:

### Using PyInstaller

```bash
# Install PyInstaller
pip install pyinstaller

# Create executable
pyinstaller --name "Trailing Stop Manager" \
            --windowed \
            --icon=trailing_stop_web/EdgeSeeker-Icon.png \
            --add-data "trailing_stop_web:trailing_stop_web" \
            main.py
```

This will create a `dist/Trailing Stop Manager` executable that can be distributed to users.

## Future Enhancements

Potential improvements for desktop deployment:

- [ ] Add "Restart" menu item to system tray
- [ ] Show connection status in tray icon tooltip
- [ ] Add tray notifications for important events
- [ ] Create installers for macOS (.dmg) and Windows (.exe)
- [ ] Add auto-updater functionality
- [ ] Support custom port configuration
