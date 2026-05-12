#!/bin/sh
# POSIX-compliant installer for the ops CLI.
#
# Usage:
#     curl -fsSL https://raw.githubusercontent.com/jonathan-chery/ops/main/install.sh | sh
#     curl -fsSL ... | sh -s -- --version 1.2.3 --prefix ~/.local
#
# Parameters (passed as arguments after ``sh -s --``):
#     --version   Release tag (default: latest)
#     --prefix    Install directory (default: /usr/local/bin)
#     --os        Override OS detection (default: auto)
#     --arch      Override architecture detection (default: auto)
#     --verify    SHA256 verification (default: true)
#     --no-sudo   Fail instead of prompting for sudo (default: false)
#     --dry-run   Print actions without executing (default: false)

set -eu

# ------------------------------------------------------------------
# Defaults (override via environment for CI flexibility)
# ------------------------------------------------------------------
OWNER_REPO="${GITHUB_REPOSITORY:-jonathan-chery/ops}"
VERSION="${INSTALL_VERSION:-latest}"
PREFIX="${INSTALL_PREFIX:-/usr/local/bin}"
OS_OVERRIDE="${INSTALL_OS:-}"
ARCH_OVERRIDE="${INSTALL_ARCH:-}"
VERIFY="${INSTALL_VERIFY:-true}"
NO_SUDO="${INSTALL_NO_SUDO:-false}"
DRY_RUN="${INSTALL_DRY_RUN:-false}"

# ------------------------------------------------------------------
# Parse CLI arguments
# ------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --os)
            OS_OVERRIDE="$2"
            shift 2
            ;;
        --arch)
            ARCH_OVERRIDE="$2"
            shift 2
            ;;
        --verify)
            VERIFY="true"
            shift
            ;;
        --no-verify)
            VERIFY="false"
            shift
            ;;
        --no-sudo)
            NO_SUDO="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        *)
            echo "[ERROR] Unknown option: $1" >&2
            echo "Usage: install.sh [--version TAG] [--prefix DIR] [--os OS] [--arch ARCH] [--verify|--no-verify] [--no-sudo] [--dry-run]"
            exit 1
            ;;
    esac
done

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
log_info()  { printf '[INFO] %s\n' "$1"; }
log_ok()    { printf '[OK]   %s\n' "$1"; }
log_warn()  { printf '[WARN] %s\n' "$1" >&2; }
log_error() { printf '[ERROR] %s\n' "$1" >&2; }

detect_os() {
    _raw=$(uname -s)
    case "$_raw" in
        Linux*)     echo "linux" ;;
        Darwin*)    echo "macos" ;;
        MINGW*|CYGWIN*|MSYS*) echo "windows" ;;
        *)          echo "$_raw" | tr '[:upper:]' '[:lower:]' ;;
    esac
}

detect_arch() {
    _raw=$(uname -m)
    case "$_raw" in
        x86_64)  echo "amd64" ;;
        amd64)   echo "amd64" ;;
        aarch64) echo "arm64" ;;
        arm64)   echo "arm64" ;;
        armv7l)  echo "armv7" ;;
        *)       echo "$_raw" ;;
    esac
}

http_get() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$1"
    else
        log_error "Neither curl nor wget found. Please install one of them."
        exit 1
    fi
}

run_cmd() {
    if [ "$DRY_RUN" = "true" ]; then
        log_info "[DRY-RUN] Would execute: $*"
        return 0
    fi
    "$@"
}

# ------------------------------------------------------------------
# Detect platform
# ------------------------------------------------------------------
OS=${OS_OVERRIDE:-$(detect_os)}
ARCH=${ARCH_OVERRIDE:-$(detect_arch)}

# For Linux-only releases, provide a clearer error for unsupported OS
if [ "$OS" != "linux" ]; then
    log_warn "Pre-built binaries are only available for Linux at this time."
    log_warn "Detected OS: $OS. You can build from source with:"
    log_warn "  pip install git+https://github.com/$OWNER_REPO"
    exit 1
fi

log_info "Detected platform: $OS / $ARCH"
log_info "Target version: $VERSION"
log_info "Install prefix: $PREFIX"

# ------------------------------------------------------------------
# Resolve release metadata from GitHub API
# ------------------------------------------------------------------
if [ "$VERSION" = "latest" ]; then
    API_URL="https://api.github.com/repos/$OWNER_REPO/releases/latest"
else
    API_URL="https://api.github.com/repos/$OWNER_REPO/releases/tags/$VERSION"
fi

log_info "Fetching release metadata..."
RELEASE_JSON=$(http_get "$API_URL") || {
    log_error "Failed to fetch release metadata from GitHub API."
    log_error "URL: $API_URL"
    log_error "You can manually download from: https://github.com/$OWNER_REPO/releases"
    exit 1
}

TAG_NAME=$(printf '%s' "$RELEASE_JSON" | grep '"tag_name"' | head -n1 | sed 's/.*"tag_name": "\([^"]*\)".*/\1/')
if [ -z "$TAG_NAME" ]; then
    log_error "Could not find release tag in GitHub API response."
    exit 1
fi
log_info "Resolved release: $TAG_NAME"

ASSET_NAME="ops-${TAG_NAME}-${OS}-${ARCH}"
CHECKSUMS_NAME="SHA256SUMS.txt"

# ------------------------------------------------------------------
# Derive download URLs
# ------------------------------------------------------------------
BASE_URL="https://github.com/$OWNER_REPO/releases/download/$TAG_NAME"
ASSET_URL="$BASE_URL/$ASSET_NAME"
CHECKSUMS_URL="$BASE_URL/$CHECKSUMS_NAME"

# ------------------------------------------------------------------
# Create temp directory
# ------------------------------------------------------------------
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# ------------------------------------------------------------------
# Download binary
# ------------------------------------------------------------------
log_info "Downloading $ASSET_NAME ..."
http_get "$ASSET_URL" > "$TMPDIR/$ASSET_NAME" || {
    log_error "Failed to download binary: $ASSET_URL"
    log_error "Available assets for this release:"
    printf '%s' "$RELEASE_JSON" | grep '"name"' | sed 's/.*"name": "\([^"]*\)".*/  - \1/'
    exit 1
}
run_cmd chmod +x "$TMPDIR/$ASSET_NAME"
log_info "Downloaded $(wc -c < "$TMPDIR/$ASSET_NAME" | sed 's/ *//') bytes"

# ------------------------------------------------------------------
# Verify checksum (optional)
# ------------------------------------------------------------------
if [ "$VERIFY" = "true" ]; then
    log_info "Verifying SHA256 checksum..."
    CHECKSUMS=$(http_get "$CHECKSUMS_URL" 2>/dev/null) || {
        log_warn "Could not download SHA256SUMS.txt — skipping verification."
        CHECKSUMS=""
    }
    if [ -n "$CHECKSUMS" ]; then
        EXPECTED=$(printf '%s' "$CHECKSUMS" | grep "$ASSET_NAME" | awk '{print $1}')
        if [ -n "$EXPECTED" ]; then
            ACTUAL=$(sha256sum "$TMPDIR/$ASSET_NAME" | awk '{print $1}')
            if [ "$EXPECTED" != "$ACTUAL" ]; then
                log_error "SHA256 checksum mismatch!"
                log_error "  Expected: $EXPECTED"
                log_error "  Actual:   $ACTUAL"
                log_error "The downloaded file may be corrupted. Aborting."
                exit 1
            fi
            log_ok "SHA256 checksum verified."
        else
            log_warn "Asset not found in SHA256SUMS.txt — skipping verification."
        fi
    fi
fi

# ------------------------------------------------------------------
# Ensure install directory exists
# ------------------------------------------------------------------
if [ ! -d "$PREFIX" ]; then
    log_info "Creating directory $PREFIX ..."
    if [ "$NO_SUDO" = "true" ]; then
        run_cmd mkdir -p "$PREFIX" || {
            log_error "Failed to create $PREFIX. Try: sudo mkdir -p $PREFIX"
            exit 1
        }
    else
        run_cmd mkdir -p "$PREFIX" 2>/dev/null || {
            log_info "Requesting sudo to create $PREFIX ..."
            run_cmd sudo mkdir -p "$PREFIX"
        }
    fi
fi

# ------------------------------------------------------------------
# Install binary
# ------------------------------------------------------------------
TARGET="$PREFIX/ops"
log_info "Installing to $TARGET ..."
if [ -w "$PREFIX" ]; then
    run_cmd cp "$TMPDIR/$ASSET_NAME" "$TARGET"
else
    if [ "$NO_SUDO" = "true" ]; then
        log_error "$PREFIX is not writable and --no-sudo is set."
        log_error "Try: --prefix ~/.local/bin   or   sudo sh install.sh"
        exit 1
    fi
    log_info "Requesting sudo to install to $PREFIX ..."
    run_cmd sudo cp "$TMPDIR/$ASSET_NAME" "$TARGET"
fi
run_cmd chmod +x "$TARGET"
log_ok "Installed ops to $TARGET"

# ------------------------------------------------------------------
# Verify installation
# ------------------------------------------------------------------
INSTALLED_VERSION=$("$TARGET" --version 2>/dev/null) || {
    log_warn "Could not verify installed version. Ensure $TARGET is executable."
    INSTALLED_VERSION="unknown"
}
log_ok "ops version: $INSTALLED_VERSION"

# ------------------------------------------------------------------
# PATH check
# ------------------------------------------------------------------
case ":${PATH}:" in
    *":$PREFIX:"*)
        : # Already in PATH
        ;;
    *)
        log_warn "$PREFIX is not in your PATH."
        log_warn "Add it to your shell profile:"
        log_warn "  export PATH=\"$PREFIX:\$PATH\""
        ;;
esac

# ------------------------------------------------------------------
# Next steps
# ------------------------------------------------------------------
echo ""
log_ok "Installation complete!"
echo ""
echo "  Quick start:"
echo "    ops config --show"
echo "    ops deploy simple-lxc"
echo ""
echo "  Docs:    https://jonathan-chery.github.io/ops/"
echo "  Issues:  https://github.com/$OWNER_REPO/issues"
