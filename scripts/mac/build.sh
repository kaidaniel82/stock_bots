#!/bin/bash
# Full build: Run all steps in sequence
# Usage: ./scripts/mac/build.sh [--skip-nuitka] [--skip-pkg]

set -e
source "$(dirname "$0")/config.sh"
check_macos

SKIP_NUITKA=false
SKIP_PKG=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-nuitka)
            SKIP_NUITKA=true
            shift
            ;;
        --skip-pkg)
            SKIP_PKG=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--skip-nuitka] [--skip-pkg]"
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(dirname "$0")"

log_info "=============================================="
log_info "Building $APP_NAME for macOS"
log_info "=============================================="
echo ""

# Step 0: Generate icons if needed
if [[ ! -f "$ASSETS_DIR/AppIcon.icns" ]]; then
    log_info "Generating icons..."
    $PYTHON "$PROJECT_ROOT/scripts/generate_icons.py"
fi

# Step 1: Nuitka build
if [[ "$SKIP_NUITKA" == "false" ]]; then
    "$SCRIPT_DIR/1_nuitka.sh"
else
    log_warn "Skipping Nuitka build (--skip-nuitka)"
fi
echo ""

# Step 2: Copy .web
"$SCRIPT_DIR/2_copy_web.sh"
echo ""

# Step 3: Add Bun
"$SCRIPT_DIR/3_add_bun.sh"
echo ""

# Step 4: Create installer
if [[ "$SKIP_PKG" == "false" ]]; then
    "$SCRIPT_DIR/4_create_pkg.sh"
else
    log_warn "Skipping .pkg creation (--skip-pkg)"
fi
echo ""

log_success "=============================================="
log_success "Build complete!"
log_success "=============================================="
log_info "App: $DIST_DIR/$APP_BUNDLE_NAME.app"
if [[ "$SKIP_PKG" == "false" ]]; then
    log_info "Installer: $DIST_DIR/${APP_BUNDLE_NAME}-${APP_VERSION}.pkg"
fi
echo ""
log_info "To test: open \"$DIST_DIR/$APP_BUNDLE_NAME.app\""
