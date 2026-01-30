# -*- mode: python ; coding: utf-8 -*-
import glob
import os

# Collect pywhispercpp binaries
site_packages = '.venv/Lib/site-packages'
pywhispercpp_binaries = []

# Python extension
for f in glob.glob(f'{site_packages}/_pywhispercpp*.pyd'):
    pywhispercpp_binaries.append((f, '.'))

# Core DLLs (whisper, ggml)
for pattern in ['whisper*.dll', 'ggml*.dll']:
    for f in glob.glob(f'{site_packages}/{pattern}'):
        pywhispercpp_binaries.append((f, '.'))

a = Analysis(
    ['src\\cld\\cli.py'],
    pathex=[],
    binaries=pywhispercpp_binaries,
    datas=[('sounds', 'sounds'), ('cld_icon.png', '.'), ('mic_256.png', '.'), ('C:/Program Files/Python312/tcl/tcl8.6', 'tcl/tcl8.6'), ('C:/Program Files/Python312/tcl/tk8.6', 'tcl/tk8.6'), ('.venv/Lib/site-packages/_sounddevice_data', '_sounddevice_data')],
    hiddenimports=['pywhispercpp', 'pywhispercpp.model'],
    hookspath=[],
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
