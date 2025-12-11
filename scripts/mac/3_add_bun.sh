#!/bin/bash
# Step 3: Download and add Bun runtime to app bundle

set -e
source "$(dirname "$0")/config.sh"
check_macos

log_info "=============================================="
log_info "Step 3: Add Bun Runtime"
log_info "=============================================="

FINAL_APP="$DIST_DIR/$APP_BUNDLE_NAME.app"
MACOS_DIR="$FINAL_APP/Contents/MacOS"
BUN_DEST="$MACOS_DIR/bun"

# Check prerequisites
if [[ ! -d "$FINAL_APP" ]]; then
    log_error "App bundle not found: $FINAL_APP"
    log_error "Run ./scripts/mac/1_nuitka.sh first"
    exit 1
fi

# Detect architecture
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    BUN_ARCH="aarch64"
else
    BUN_ARCH="x64"
fi

log_info "Detected architecture: $ARCH -> bun-darwin-$BUN_ARCH"

# Download Bun
BUN_URL="https://github.com/oven-sh/bun/releases/latest/download/bun-darwin-$BUN_ARCH.zip"
BUN_TMP="$BUILD_DIR/bun_download"

mkdir -p "$BUN_TMP"

log_info "Downloading Bun from $BUN_URL..."
curl -L -o "$BUN_TMP/bun.zip" "$BUN_URL"

log_info "Extracting..."
unzip -o "$BUN_TMP/bun.zip" -d "$BUN_TMP"

# Find bun binary
BUN_BINARY=$(find "$BUN_TMP" -name "bun" -type f -perm +111 | head -1)

if [[ -z "$BUN_BINARY" ]]; then
    log_error "Bun binary not found in download"
    exit 1
fi

# Copy to app bundle
cp "$BUN_BINARY" "$BUN_DEST"
chmod +x "$BUN_DEST"

# Verify
BUN_VERSION=$("$BUN_DEST" --version 2>/dev/null || echo "unknown")
log_success "Bun $BUN_VERSION added to app bundle"

# Cleanup
rm -rf "$BUN_TMP"

log_info "Next: Run ./scripts/mac/4_create_pkg.sh (optional)"
log_info "Or test the app: open \"$FINAL_APP\""
