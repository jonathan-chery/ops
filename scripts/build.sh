#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ARCH="$(uname -m)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
VERSION="${VERSION:-$(grep -m1 '^version' "$PROJECT_DIR/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')}"

echo "=== ops CLI binary build ==="
echo "  OS: $OS"
echo "  Arch: $ARCH"
echo "  Version: $VERSION"

# Activate venv and install deps
cd "$PROJECT_DIR"
source .venv/bin/activate

pip install -q -e ".[build]"

# Build with pyinstaller
SPEC_FILE="build/ops.spec"
mkdir -p dist build

# Create spec file
cat > "$SPEC_FILE" <<PYI
# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path

project_dir = Path(os.getcwd())
src_dir = project_dir / "src"
blueprints_dir = src_dir / "ops" / "blueprints"
templates_dir = blueprints_dir / "templates"

entrypoint = "/tmp/_ops_entrypoint.py"
with open(entrypoint, "w") as f:
    f.write("from ops.cli import app\nimport sys\nsys.exit(app())\n")

a = Analysis(
    [entrypoint],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[
        (str(blueprints_dir), "ops/blueprints"),
        (str(templates_dir), "ops/blueprints/templates"),
    ],
    hiddenimports=[
        "proxmoxer.backends.https",
        "keyring.backends.SecretService",
        "keyring.backends.OS_X",
        "keyring.backends.Windows",
        "keyring.backends.chainer",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ops',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
PYI

pyinstaller --noconfirm "$SPEC_FILE" \
    --clean \
    --distpath "dist/$OS-$ARCH" \
    --workpath "build/pyinstaller"

echo ""
echo "=== Build complete ==="
echo "Binary: dist/$OS-$ARCH/ops"
echo ""
echo "To run:"
echo "  ./dist/$OS-$ARCH/ops --help"
