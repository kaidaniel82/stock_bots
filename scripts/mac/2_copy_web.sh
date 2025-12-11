#!/bin/bash
# Step 2: Copy .web directory (without node_modules)
# This avoids the codesign "Argument list too long" error

set -e
source "$(dirname "$0")/config.sh"
check_macos

log_info "=============================================="
log_info "Step 2: Copy .web Directory"
log_info "=============================================="

FINAL_APP="$DIST_DIR/$APP_BUNDLE_NAME.app"
MACOS_DIR="$FINAL_APP/Contents/MacOS"
DEST_WEB="$MACOS_DIR/.web"
SOURCE_WEB="$PROJECT_ROOT/.web"

# Check prerequisites
if [[ ! -d "$FINAL_APP" ]]; then
    log_error "App bundle not found: $FINAL_APP"
    log_error "Run ./scripts/mac/1_nuitka.sh first"
    exit 1
fi

if [[ ! -d "$SOURCE_WEB" ]]; then
    log_error ".web directory not found. Run: reflex export --no-zip"
    exit 1
fi

# Remove existing .web if present
if [[ -d "$DEST_WEB" ]]; then
    log_info "Removing existing .web..."
    rm -rf "$DEST_WEB"
fi

log_info "Copying .web (excluding node_modules)..."

# Use rsync to copy everything except node_modules
rsync -a \
    --exclude='node_modules' \
    --exclude='.react-router' \
    "$SOURCE_WEB/" "$DEST_WEB/"

# Count files
FILE_COUNT=$(find "$DEST_WEB" -type f | wc -l | tr -d ' ')
log_success "Copied $FILE_COUNT files to .web"

log_info "Next: Run ./scripts/mac/3_add_bun.sh"
