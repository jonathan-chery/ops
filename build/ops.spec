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
