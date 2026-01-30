# PyInstaller runtime hook for pywhispercpp
# Ensures the whisper DLL can be found by the native extension

import os
import sys

def setup_dll_directory():
    """Add the internal directory to DLL search path for whisper.cpp."""
    if sys.platform != 'win32':
        return

    # In frozen exe, DLLs are in _internal or next to the exe
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')

        # Add both directories to DLL search path
        try:
            if hasattr(os, 'add_dll_directory'):
                if os.path.isdir(internal_dir):
                    os.add_dll_directory(internal_dir)
                os.add_dll_directory(exe_dir)
        except Exception:
            pass

        # Also prepend to PATH for older Windows
        path_dirs = [exe_dir]
        if os.path.isdir(internal_dir):
            path_dirs.append(internal_dir)
        os.environ['PATH'] = os.pathsep.join(path_dirs) + os.pathsep + os.environ.get('PATH', '')

setup_dll_directory()
