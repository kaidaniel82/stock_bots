#!/bin/bash
# Step 5: Create styled .dmg installer
# Creates a drag-and-drop DMG with background and icon positions

set -e
source "$(dirname "$0")/config.sh"
check_macos

log_info "=============================================="
log_info "Step 5: Create .dmg Installer"
log_info "=============================================="

FINAL_APP="$DIST_DIR/$APP_BUNDLE_NAME.app"
DMG_DIR="$BUILD_DIR/dmg_contents"
DMG_TEMP="$BUILD_DIR/temp.dmg"
DMG_OUTPUT="$DIST_DIR/${APP_BUNDLE_NAME}-${APP_VERSION}.dmg"
BACKGROUND="$ASSETS_DIR/dmg_background.png"
VOLUME_NAME="$APP_NAME"

# DMG window settings
WINDOW_WIDTH=600
WINDOW_HEIGHT=400
ICON_SIZE=100
APP_X=150
APP_Y=200
APPS_X=450
APPS_Y=200

# Check prerequisites - try both locations
if [[ ! -d "$FINAL_APP" ]]; then
    PKG_APP="$BUILD_DIR/pkg_root/Applications/$APP_NAME.app"
    if [[ -d "$PKG_APP" ]]; then
        log_info "Using app from pkg_root..."
        mkdir -p "$DIST_DIR"
        cp -R "$PKG_APP" "$FINAL_APP"
    else
        log_error "App bundle not found"
        log_error "Run ./scripts/mac/1_nuitka.sh first"
        exit 1
    fi
fi

# Generate background if missing
if [[ ! -f "$BACKGROUND" ]]; then
    log_info "Generating DMG background..."
    $PYTHON "$PROJECT_ROOT/scripts/mac/create_dmg_background.py"
fi

# Clean previous build
rm -rf "$DMG_DIR"
rm -f "$DMG_TEMP" "$DMG_OUTPUT"
mkdir -p "$DMG_DIR"

# Copy app
log_info "Copying app to DMG..."
cp -R "$FINAL_APP" "$DMG_DIR/$APP_BUNDLE_NAME.app"

# Create Applications symlink
ln -s /Applications "$DMG_DIR/Applications"

# Create hidden background folder
mkdir -p "$DMG_DIR/.background"
cp "$BACKGROUND" "$DMG_DIR/.background/background.png"

# Calculate DMG size (app size + 50MB buffer)
APP_SIZE=$(du -sm "$DMG_DIR" | cut -f1)
DMG_SIZE=$((APP_SIZE + 50))

# Unmount if already mounted
hdiutil detach "/Volumes/$VOLUME_NAME" 2>/dev/null || true

# Create temporary read-write DMG
log_info "Creating temporary DMG..."
hdiutil create \
    -volname "$VOLUME_NAME" \
    -size "${DMG_SIZE}m" \
    -fs HFS+ \
    -srcfolder "$DMG_DIR" \
    "$DMG_TEMP"

# Mount DMG
log_info "Mounting DMG for styling..."
DEVICE=$(hdiutil attach -readwrite -noverify -noautoopen "$DMG_TEMP" | awk '/Apple_HFS/ {print $1}')

if [[ -z "$DEVICE" ]]; then
    log_error "Failed to mount DMG. Grant Terminal 'Full Disk Access' in System Preferences."
    log_info "Falling back to unstyled DMG..."
    hdiutil convert "$DMG_TEMP" -format UDZO -o "$DMG_OUTPUT" 2>/dev/null || \
        hdiutil create -volname "$VOLUME_NAME" -srcfolder "$DMG_DIR" -ov -format UDZO "$DMG_OUTPUT"
    rm -f "$DMG_TEMP"
    rm -rf "$DMG_DIR"
    exit 0
fi

sleep 2

# Apply styling with AppleScript
log_info "Applying DMG styling..."
osascript <<EOF
tell application "Finder"
    tell disk "$VOLUME_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {100, 100, $((100 + WINDOW_WIDTH)), $((100 + WINDOW_HEIGHT))}

        set theViewOptions to icon view options of container window
        set arrangement of theViewOptions to not arranged
        set icon size of theViewOptions to $ICON_SIZE
        set background picture of theViewOptions to file ".background:background.png"

        set position of item "$APP_BUNDLE_NAME.app" of container window to {$APP_X, $APP_Y}
        set position of item "Applications" of container window to {$APPS_X, $APPS_Y}

        update without registering applications
        delay 1
        close
    end tell
end tell
EOF

# Sync and unmount
sync
sleep 2
hdiutil detach "$DEVICE" -quiet

# Convert to compressed read-only DMG
log_info "Compressing DMG..."
hdiutil convert "$DMG_TEMP" -format UDZO -imagekey zlib-level=9 -o "$DMG_OUTPUT"

# Cleanup
rm -f "$DMG_TEMP"
rm -rf "$DMG_DIR"

# Get final size
DMG_SIZE=$(du -h "$DMG_OUTPUT" | cut -f1)

log_success "DMG created: $DMG_OUTPUT ($DMG_SIZE)"
log_info ""
log_info "To install: Open DMG, drag app to Applications folder"
