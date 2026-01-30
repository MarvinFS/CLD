# PyInstaller hook for pywhispercpp
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# Collect all submodules
hiddenimports = collect_submodules('pywhispercpp')

# Collect the native extension and DLL
binaries = collect_dynamic_libs('pywhispercpp')

# Also explicitly add from site-packages root (where delvewheel puts the DLL)
import os
import sys

# Find site-packages
for path in sys.path:
    if 'site-packages' in path:
        # Look for the pyd and dll
        pyd = os.path.join(path, '_pywhispercpp.cp312-win_amd64.pyd')
        if os.path.exists(pyd):
            binaries.append((pyd, '.'))
        # Find whisper dll
        for f in os.listdir(path):
            if f.startswith('whisper-') and f.endswith('.dll'):
                binaries.append((os.path.join(path, f), '.'))
        break
