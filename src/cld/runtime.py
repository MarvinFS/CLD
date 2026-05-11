"""Shared runtime helpers consolidated from multiple modules.

Pre-existing implementations of ``_is_frozen()`` were duplicated across
``daemon.py``, ``setup.py``, ``sounds.py``, ``ui/overlay.py``, and
``ui/__init__.py``. The drift between them was small but real (some
checked Nuitka's ``__compiled__`` differently). Importing from this module
gives a single source of truth.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def is_frozen() -> bool:
    """True when running as PyInstaller or Nuitka frozen executable."""
    if getattr(sys, "frozen", False):
        return True
    main_mod = sys.modules.get("__main__")
    return main_mod is not None and hasattr(main_mod, "__compiled__")


def apply_dark_title_bar(window: Any) -> None:
    """Best-effort dark title bar for a Tk window on Windows 10/11.

    Consolidates the near-identical helpers that lived in ``daemon_service``,
    ``ui/model_dialog`` and ``ui/settings_dialog``. Safe to call on
    non-Windows (no-op) and tolerates DwmSetWindowAttribute failure.
    """
    if sys.platform != "win32" or window is None:
        return
    try:
        window.update_idletasks()
        window.update()
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
        GA_ROOT = 2
        value = ctypes.c_int(1)

        hwnd = ctypes.windll.user32.GetAncestor(window.winfo_id(), GA_ROOT)
        if not hwnd:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            return

        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value),
        )
        if result != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                ctypes.byref(value), ctypes.sizeof(value),
            )

        SWP_FRAMECHANGED = 0x0020
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER,
        )
    except Exception:
        logger.debug("apply_dark_title_bar failed", exc_info=True)
