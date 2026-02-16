# PyInstaller spec for the pyglet game.
# Build: .\.venv\Scripts\python.exe -m PyInstaller .\kiro2_game.spec

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("pyglet")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/fonts/Orbitron-Variable.ttf", "assets/fonts"),
        ("assets/fonts/Rajdhani-Regular.ttf", "assets/fonts"),
        ("assets/fonts/Rajdhani-SemiBold.ttf", "assets/fonts"),
        ("assets/fonts/OFL-Orbitron.txt", "assets/fonts"),
        ("assets/fonts/OFL-Rajdhani.txt", "assets/fonts"),
    ],
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
