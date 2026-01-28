"""CLD UI components."""

import sys
from pathlib import Path

from cld.ui.overlay import STTOverlay
from cld.ui.hardware import HardwareInfo, detect_hardware, get_available_models
from cld.ui.key_scanner import KeyScanner, KeyCapture, scan_key
from cld.ui.settings_popup import SettingsPopup
from cld.ui.settings_dialog import SettingsDialog, show_settings
from cld.ui.tray import TrayIcon, is_tray_available


def _is_frozen() -> bool:
    """Check if running as frozen exe (PyInstaller or Nuitka)."""
    # PyInstaller sets sys.frozen
    if getattr(sys, "frozen", False):
        return True
    # Nuitka sets __compiled__ on __main__
    main_mod = sys.modules.get("__main__", object())
    return "__compiled__" in dir(main_mod)


def get_app_icon_path() -> Path:
    """Get path to cld_icon.png for all UI components.

    Returns:
        Path to cld_icon.png in project root (source) or _internal (frozen exe).
    """
    if _is_frozen():
        exe_dir = Path(sys.executable).parent
        # Nuitka: file next to exe
        nuitka_path = exe_dir / "cld_icon.png"
        if nuitka_path.exists():
            return nuitka_path
        # PyInstaller: in _internal/
        return exe_dir / "_internal" / "cld_icon.png"
    return Path(__file__).parent.parent.parent / "cld_icon.png"


__all__ = [
    # Overlay
    "STTOverlay",
    # Hardware detection
    "HardwareInfo",
    "detect_hardware",
    "get_available_models",
    # Key scanner
    "KeyScanner",
    "KeyCapture",
    "scan_key",
    # Settings
    "SettingsPopup",
    "SettingsDialog",
    "show_settings",
    # Tray
    "TrayIcon",
    "is_tray_available",
    # Utilities
    "get_app_icon_path",
]
