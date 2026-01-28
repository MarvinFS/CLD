# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\cld\\cli.py'],
    pathex=[],
    binaries=[
        ('.venv/Lib/site-packages/_pywhispercpp.cp312-win_amd64.pyd', '.'),
        ('.venv/Lib/site-packages/whisper-26648edb58a0c29d5e01cf4bb43f8fa7.dll', '.'),
    ],
    datas=[('sounds', 'sounds'), ('cld_icon.png', '.'), ('mic_256.png', '.'), ('C:/Python314/tcl/tcl8.6', 'tcl/tcl8.6'), ('C:/Python314/tcl/tk8.6', 'tcl/tk8.6'), ('.venv/Lib/site-packages/_sounddevice_data', '_sounddevice_data')],
    hiddenimports=['pywhispercpp', 'pywhispercpp.model', '_pywhispercpp'],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=['pyi_rth_numpy.py', 'pyi_rth_tcltk.py', 'pyi_rth_pywhispercpp.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CLD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['cld_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CLD',
)
