#!/bin/bash
# Step 1: Build with Nuitka
# Creates the base .app bundle without .web directory

set -e  # Exit on error
source "$(dirname "$0")/config.sh"
check_macos

log_info "=============================================="
log_info "Step 1: Nuitka Build"
log_info "=============================================="

# Check prerequisites
if [[ ! -f "$ASSETS_DIR/AppIcon.icns" ]]; then
    log_error "AppIcon.icns not found. Run: python scripts/generate_icons.py"
    exit 1
fi

# Clean previous build and dist
log_info "Cleaning previous build and dist..."
rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR"

# Get plotly validators path
PLOTLY_VALIDATORS=$($PYTHON -c "import plotly; print(plotly.__path__[0] + '/validators')")

log_info "Starting Nuitka compilation..."
log_info "This takes 10-30 minutes on first run (cached afterwards)"

$PYTHON -m nuitka \
    --standalone \
    --assume-yes-for-downloads \
    --output-dir="$BUILD_DIR" \
    \
    --macos-create-app-bundle \
    --macos-app-name="$APP_NAME" \
    --macos-app-icon="$ASSETS_DIR/AppIcon.icns" \
    --macos-app-mode=ui-element \
    \
    --include-package=trailing_stop_web \
    --include-package=reflex \
    --include-package=uvicorn \
    --include-package=pystray \
    --include-package=PIL \
    --include-package=plotly \
    --include-package=ib_insync \
    \
    --nofollow-import-to=plotly.matplotlylib.mplexporter.tests \
    --nofollow-import-to=pytest \
    --nofollow-import-to=_pytest \
    --nofollow-import-to=hypothesis \
    \
    --include-data-dir="$PROJECT_ROOT/trailing_stop_web"=trailing_stop_web \
    --include-data-file="$PROJECT_ROOT/rxconfig.py"=rxconfig.py \
    --include-data-dir="$PLOTLY_VALIDATORS"=plotly/validators \
    \
    --include-data-file="$ASSETS_DIR/TrayIconTemplate.png"=assets/TrayIconTemplate.png \
    --include-data-file="$ASSETS_DIR/TrayIconTemplate@2x.png"=assets/TrayIconTemplate@2x.png \
    --include-data-file="$ASSETS_DIR/EdgeSeeker-Icon.png"=assets/EdgeSeeker-Icon.png \
    \
    --remove-output \
    \
    "$PROJECT_ROOT/main_desktop.py"

# Find the generated app bundle
APP_BUNDLE=$(find "$BUILD_DIR" -maxdepth 1 -name "*.app" -type d | head -1)

if [[ -z "$APP_BUNDLE" ]]; then
    log_error "Nuitka build failed - no .app bundle found"
    exit 1
fi

# Move to dist
mkdir -p "$DIST_DIR"
FINAL_APP="$DIST_DIR/$APP_BUNDLE_NAME.app"

if [[ -d "$FINAL_APP" ]]; then
    rm -rf "$FINAL_APP"
fi

mv "$APP_BUNDLE" "$FINAL_APP"

log_success "Nuitka build complete: $FINAL_APP"
log_info "Next: Run ./scripts/mac/2_copy_web.sh"
