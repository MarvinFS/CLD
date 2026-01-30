# PyInstaller runtime hook to set Tcl/Tk library paths
import os
import sys

if getattr(sys, 'frozen', False):
    # Running as compiled exe
    base_path = os.path.dirname(sys.executable)
    tcl_path = None
    tk_path = None

    # Search order for tcl/tk data:
    # 1. --onedir with _internal folder (PyInstaller 6.x default)
    # 2. --onedir with tcl/ next to exe
    # 3. --onefile with _MEIPASS temp directory
    search_paths = [
        (os.path.join(base_path, '_internal', 'tcl', 'tcl8.6'),
         os.path.join(base_path, '_internal', 'tcl', 'tk8.6')),
        (os.path.join(base_path, 'tcl', 'tcl8.6'),
         os.path.join(base_path, 'tcl', 'tk8.6')),
    ]

    # Add _MEIPASS paths for --onefile
    if hasattr(sys, '_MEIPASS'):
        search_paths.append(
            (os.path.join(sys._MEIPASS, '_tcl_data', 'tcl8.6'),
             os.path.join(sys._MEIPASS, '_tcl_data', 'tk8.6'))
        )
        search_paths.append(
            (os.path.join(sys._MEIPASS, 'tcl', 'tcl8.6'),
             os.path.join(sys._MEIPASS, 'tcl', 'tk8.6'))
        )

    # Find first valid path
    for tcl_candidate, tk_candidate in search_paths:
        if os.path.exists(tcl_candidate):
            tcl_path = tcl_candidate
            tk_path = tk_candidate
            break

    if tcl_path and os.path.exists(tcl_path):
        os.environ['TCL_LIBRARY'] = tcl_path
    if tk_path and os.path.exists(tk_path):
        os.environ['TK_LIBRARY'] = tk_path
