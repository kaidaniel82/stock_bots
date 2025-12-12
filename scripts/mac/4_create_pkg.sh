#!/bin/bash
# Step 4: Create .pkg installer

set -e
source "$(dirname "$0")/config.sh"
check_macos

log_info "=============================================="
log_info "Step 4: Create .pkg Installer"
log_info "=============================================="

FINAL_APP="$DIST_DIR/$APP_BUNDLE_NAME.app"
PKG_ROOT="$BUILD_DIR/pkg_root"
SCRIPTS_DIR="$BUILD_DIR/pkg_scripts"
INSTALLER_DIR="$PROJECT_ROOT/installer/mac"

# Check prerequisites
if [[ ! -d "$FINAL_APP" ]]; then
    log_error "App bundle not found: $FINAL_APP"
    log_error "Run steps 1-3 first"
    exit 1
fi

# Clean
rm -rf "$PKG_ROOT" "$SCRIPTS_DIR"
mkdir -p "$PKG_ROOT/Applications" "$SCRIPTS_DIR" "$INSTALLER_DIR"

# Copy app to package root
log_info "Preparing package contents..."
cp -R "$FINAL_APP" "$PKG_ROOT/Applications/$APP_NAME.app"

# Create postinstall script
cat > "$SCRIPTS_DIR/postinstall" << 'POSTINSTALL'
#!/bin/bash
APP_PATH="/Applications/Trailing Stop Manager.app"
MACOS_PATH="$APP_PATH/Contents/MacOS"

# Make entire app readable/executable by all users
chmod -R 755 "$APP_PATH"

# Make bun executable
chmod +x "$MACOS_PATH/bun" 2>/dev/null || true

# Make .web writable for node_modules
chmod -R 777 "$MACOS_PATH/.web" 2>/dev/null || true

echo "Trailing Stop Manager installed successfully!"
exit 0
POSTINSTALL
chmod +x "$SCRIPTS_DIR/postinstall"

# Build component package
log_info "Building component package..."
COMPONENT_PKG="$BUILD_DIR/component.pkg"

pkgbuild \
    --root "$PKG_ROOT" \
    --scripts "$SCRIPTS_DIR" \
    --identifier "$APP_IDENTIFIER" \
    --version "$APP_VERSION" \
    --install-location "/" \
    "$COMPONENT_PKG"

# Create distribution.xml
cat > "$INSTALLER_DIR/distribution.xml" << EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>$APP_NAME</title>
    <organization>$APP_IDENTIFIER</organization>
    <domains enable_localSystem="true" enable_anywhere="false"/>
    <options customize="never" require-scripts="true" rootVolumeOnly="true" hostArchitectures="arm64,x86_64"/>

    <choices-outline>
        <line choice="default">
            <line choice="$APP_IDENTIFIER"/>
        </line>
    </choices-outline>

    <choice id="default"/>
    <choice id="$APP_IDENTIFIER" visible="false">
        <pkg-ref id="$APP_IDENTIFIER"/>
    </choice>

    <pkg-ref id="$APP_IDENTIFIER" version="$APP_VERSION" onConclusion="none">component.pkg</pkg-ref>
</installer-gui-script>
EOF

# Build final product
log_info "Building final installer..."
FINAL_PKG="$DIST_DIR/${APP_BUNDLE_NAME}-${APP_VERSION}.pkg"

productbuild \
    --distribution "$INSTALLER_DIR/distribution.xml" \
    --package-path "$BUILD_DIR" \
    "$FINAL_PKG"

log_success "Installer created: $FINAL_PKG"
log_info ""
log_info "To install: double-click the .pkg file"
log_info "To test app directly: open \"$FINAL_APP\""
