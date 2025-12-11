#!/bin/bash
# Shared configuration for macOS build scripts

# Paths
export PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ASSETS_DIR="$PROJECT_ROOT/assets"
export BUILD_DIR="$PROJECT_ROOT/build"
export DIST_DIR="$PROJECT_ROOT/dist"

# App Info
export APP_NAME="Trailing Stop Manager"
export APP_BUNDLE_NAME="TrailingStopManager"
export APP_IDENTIFIER="com.edgeseeker.trailingstop"
export APP_VERSION="1.0.0"

# Python (use project venv)
export PYTHON="$PROJECT_ROOT/.venv/bin/python"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log_error "This script must be run on macOS"
        exit 1
    fi
}
