#!/usr/bin/env bash
# Universal build script for macOS, Linux, and Windows (via Wine)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Read version from __init__.py if available, else from pyproject
VERSION="${VERSION:-$(grep -m1 '__version__' src/ops/__init__.py 2>/dev/null | grep -o '".*"' | tr -d '"' || echo "0.1.0")}"

echo "========================================"
echo "  ops CLI - Release Builder"
echo "  Version: $VERSION"
echo "========================================"

# Ensure dependencies
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -e ".[build]"

mkdir -p dist build

# ===== Linux x86_64 build =====
echo ""
echo "[1/3] Building for Linux x86_64..."
UNAME_S=$(uname -s)
UNAME_M=$(uname -m)

if [ "$UNAME_S" == "Linux" ]; then
    PYTHON_VERSION=$(python3 --version | grep -o '[0-9]\+\.[0-9]\+')
    
    cat > build/ops-linux.spec <<PYI_SPEC
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

base_dir = Path(os.getcwd())
src_dir = base_dir / "src"

copy_files = [
    (str(src_dir / "ops" / "blueprints"), "ops/blueprints"),
]

a = Analysis(
    [str(src_dir / "ops" / "cli.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=copy_files,
    hiddenimports=[
        "proxmoxer.backends.https",
        "keyring.backends.SecretService",
        "keyring.backends.chainer",
        "psycopg2",
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
    strip=True,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)
PYI_SPEC

    pyinstaller --distpath "dist/linux-$UNAME_M" --workpath "build/linux-$UNAME_M" --noconfirm build/ops-linux.spec
    
    echo "  [OK] Linux binary: dist/linux-$UNAME_M/ops"
else
    echo "  [SKIP] Not running on Linux"
fi

# ===== macOS build =====
echo ""
echo "[2/3] Building for macOS..."
if [ "$UNAME_S" == "Darwin" ]; then
    
    cat > build/ops-macos.spec <<PYI_SPEC2
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

base_dir = Path(os.getcwd())
src_dir = base_dir / "src"

copy_files = [
    (str(src_dir / "ops" / "blueprints"), "ops/blueprints"),
]

a = Analysis(
    [str(src_dir / "ops" / "cli.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=copy_files,
    hiddenimports=[
        "proxmoxer.backends.https",
        "keyring.backends.OS_X",
        "keyring.backends.chainer",
        "psycopg2",
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
    strip=True,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch='universal2',
    codesign_identity=None,
    entitlements_file=None,
)
PYI_SPEC2
    
    pyinstaller --distpath "dist/macos-$UNAME_M" --workpath "build/macos-$UNAME_M" --noconfirm build/ops-macos.spec
    
    echo "  [OK] macOS binary: dist/macos-$UNAME_M/ops"
else
    echo "  [SKIP] Not running on macOS. Run this script on macOS for native build."
fi

# ===== Summary =====
echo ""
echo "========================================"
echo "  Release Build Summary"
echo "========================================"
ls -lh dist/*/
echo ""
echo "To package for release, run:"
echo "  tar czf ops-${VERSION}-linux-${UNAME_M}.tar.gz -C dist/linux-${UNAME_M} ops"
echo ""
echo "Done."
