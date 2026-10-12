# PyInstaller spec for the pyglet game.
# Build: .\.venv\Scripts\python.exe -m PyInstaller .\kiro2_game.spec

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# asset_manifest.py sits next to this spec and imports only the standard library.
sys.path.insert(0, os.path.abspath(SPECPATH))
import asset_manifest  # noqa: E402

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("pyglet")

# Bundle every file in assets/fonts and assets/audio. verify_bundle() stops the build when the
# code opens an asset that is missing from the tree or is not in this list.
datas = asset_manifest.bundle_datas(SPECPATH)
asset_manifest.verify_bundle(datas, SPECPATH)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Plouto",
    icon="laser-gun_38685.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Set to True if you want a console for tracebacks.
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Plouto",
)
