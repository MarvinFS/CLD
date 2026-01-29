"""Windows window focus tracking and restoration."""

import ctypes
import logging
from dataclasses import dataclass
from typing import Optional

_logger = logging.getLogger(__name__)

# Desktop window class names that don't accept text input
_DESKTOP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd"}


@dataclass
class WindowInfo:
    """Information about a captured window."""

    window_id: str
    platform: str = "Windows"
    app_name: Optional[str] = None


def _get_window_class(hwnd: int) -> Optional[str]:
    """Get the window class name."""
    try:
        user32 = ctypes.windll.user32
        buffer = ctypes.create_unicode_buffer(256)
        length = user32.GetClassNameW(hwnd, buffer, 256)
        if length > 0:
            return buffer.value
    except Exception:
        pass
    return None


def _is_desktop_window(hwnd: int) -> bool:
    """Check if the window is the desktop or shell (can't accept text)."""
    class_name = _get_window_class(hwnd)
    if class_name in _DESKTOP_CLASSES:
        _logger.debug("Window class '%s' is a desktop/shell window", class_name)
        return True
    return False


def get_active_window() -> Optional[WindowInfo]:
    """Capture the currently active window.

    Returns:
        WindowInfo with the window handle, or None if desktop/shell is active.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            # Don't capture desktop or shell windows - they can't receive text
            if _is_desktop_window(hwnd):
                _logger.debug("Desktop/shell is active, returning None")
                return None
            return WindowInfo(window_id=str(hwnd))
    except Exception:
        _logger.debug("Failed to capture active window", exc_info=True)
    return None


def restore_focus(window_info: Optional[WindowInfo]) -> bool:
    """Restore focus to a previously captured window.

    Args:
        window_info: The window information from get_active_window().

    Returns:
        True if focus was restored, False otherwise.
    """
    if window_info is None or not window_info.window_id:
        return False

    try:
        hwnd = int(window_info.window_id)
        return _set_foreground(hwnd)
    except (ValueError, TypeError):
        return False


def _set_foreground(hwnd: int) -> bool:
    """Set a window to foreground by handle."""
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


def focus_window_by_hwnd(hwnd: int) -> bool:
    """Focus a window by its handle.

    Args:
        hwnd: Window handle from GetForegroundWindow() or similar.

    Returns:
        True if focus was set successfully, False otherwise.
    """
    if not _set_foreground(hwnd):
        _logger.debug("Failed to focus window by hwnd")
        return False
    return True
