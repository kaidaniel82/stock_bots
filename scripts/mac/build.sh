#!/bin/bash
# Full build: Run all steps in sequence
# Usage: ./scripts/mac/build.sh [--skip-nuitka] [--skip-pkg]

set -e
source "$(dirname "$0")/config.sh"
check_macos

SKIP_NUITKA=false
SKIP_PKG=false

# =============================================================================
# Version Management (YYMMDD-NNN format)
# =============================================================================
bump_version() {
    local VERSION_FILE="$PROJECT_ROOT/trailing_stop_web/version.py"
    local TODAY=$(date +"%y%m%d")

    # Read current version (macOS compatible)
    local CURRENT_VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$VERSION_FILE" 2>/dev/null || echo "")

    if [[ -z "$CURRENT_VERSION" ]]; then
        # No version found, start fresh
        NEW_VERSION="${TODAY}-001"
    else
        # Parse current version
        local CURRENT_DATE="${CURRENT_VERSION%-*}"
        local CURRENT_NUM="${CURRENT_VERSION##*-}"

        if [[ "$CURRENT_DATE" == "$TODAY" ]]; then
            # Same day: increment build number
            local NEXT_NUM=$(printf "%03d" $((10#$CURRENT_NUM + 1)))
            NEW_VERSION="${TODAY}-${NEXT_NUM}"
        else
            # New day: reset to 001
            NEW_VERSION="${TODAY}-001"
        fi
    fi

    # Write new version (proper Python format)
    cat > "$VERSION_FILE" << EOF
"""Version information for Trailing Stop Manager."""

__version__ = "$NEW_VERSION"
EOF

    log_success "Version bumped to: $NEW_VERSION"

    # Git commit and push
    log_info "Committing version bump..."
    cd "$PROJECT_ROOT"
    git add "$VERSION_FILE"
    git commit -m "$NEW_VERSION"
    git push
    log_success "Version committed and pushed"

    # Export for use in rest of script
    export APP_VERSION="$NEW_VERSION"
}

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

# Step 0: Bump version and commit
bump_version
echo ""

# Step 1: Generate icons if needed
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
