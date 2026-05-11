"""System tray integration for CLD using pystray."""

import ctypes
import logging
import re
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional, Set

logger = logging.getLogger(__name__)

# Try to import pystray
try:
    import pystray
    from PIL import Image, ImageDraw

    _TRAY_AVAILABLE = True
except ImportError:
    _TRAY_AVAILABLE = False
    logger.debug("pystray or PIL not available")


def is_tray_available() -> bool:
    """Check if system tray is available."""
    return _TRAY_AVAILABLE


# --- Ghost tray icon cleanup (Windows) ----------------------------------
# pystray.Icon.stop() posts WM_STOP to its mainloop thread and returns
# immediately. If that thread is wedged or already dead after sleep/wake,
# the WM_STOP is never processed and Shell_NotifyIcon(NIM_DELETE) is never
# called, so Explorer keeps drawing the ghost icon until reboot. We track
# every hwnd we hand to pystray and force-remove any leftovers ourselves.

_NIM_DELETE = 0x00000002
_WM_CLOSE = 0x0010
_IS_WIN32 = sys.platform == "win32"

# hwnds owned by previous pystray.Icon instances in this process.
# Cleaned up by _sweep_stale_tray_windows() the next time we (re)start.
_stale_hwnds: Set[int] = set()
_stale_lock = threading.Lock()


def _force_delete_shell_icon(hwnd: int) -> bool:
    """Manually call Shell_NotifyIcon(NIM_DELETE) for (hwnd, uID=0).

    pystray passes ``hID`` (a typo it never noticed) to NOTIFYICONDATAW,
    which ctypes silently drops, so the real uID field is always 0. We
    match that here. Safe to call repeatedly; failure just means the
    shell entry is already gone.
    """
    if not _IS_WIN32 or not hwnd:
        return False

    class _NIDW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    nid = _NIDW()
    nid.cbSize = ctypes.sizeof(_NIDW)
    nid.hWnd = hwnd
    nid.uID = 0
    try:
        ok = bool(ctypes.windll.shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(nid)))
        logger.debug("NIM_DELETE hwnd=0x%X result=%s", hwnd, ok)
        return ok
    except OSError as e:
        logger.debug("NIM_DELETE hwnd=0x%X raised: %s", hwnd, e)
        return False


def _post_close_to_window(hwnd: int) -> None:
    """Best-effort PostMessage(WM_CLOSE) to a leaked pystray window."""
    if not _IS_WIN32 or not hwnd:
        return
    try:
        ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), _WM_CLOSE, 0, 0)
    except OSError:
        pass


def _sweep_stale_tray_windows() -> int:
    """Force-remove every hwnd recorded as stale. Returns count cleaned.

    Also walks our own process's window list for any class matching
    ``CLD<digits>SystemTrayIcon`` we don't already know about, to handle
    cases where the tracking set got reset (e.g. after import reload).
    """
    if not _IS_WIN32:
        return 0

    discovered: Set[int] = set()
    try:
        EnumWindows = ctypes.windll.user32.EnumWindows
        GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
        GetClassNameW = ctypes.windll.user32.GetClassNameW
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        own_pid = ctypes.windll.kernel32.GetCurrentProcessId()
        pattern = re.compile(r"^CLD\d+SystemTrayIcon$")

        def _cb(hwnd, _lparam):
            pid = wintypes.DWORD(0)
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != own_pid:
                return True
            buf = ctypes.create_unicode_buffer(64)
            GetClassNameW(hwnd, buf, 64)
            if pattern.match(buf.value):
                discovered.add(int(hwnd))
            return True

        EnumWindows(WNDENUMPROC(_cb), 0)
    except OSError:
        pass

    with _stale_lock:
        targets = set(_stale_hwnds) | discovered
        cleaned = 0
        for hwnd in targets:
            if _force_delete_shell_icon(hwnd):
                cleaned += 1
            _post_close_to_window(hwnd)
            _stale_hwnds.discard(hwnd)

    if cleaned:
        logger.info("Swept %d stale tray icon(s)", cleaned)
    return cleaned


class TrayIcon:
    """System tray icon for CLD."""

    # Icon states
    STATE_READY = "ready"
    STATE_RECORDING = "recording"
    STATE_PROCESSING = "processing"

    def __init__(
        self,
        on_show_overlay: Optional[Callable[[], None]] = None,
        on_hide_overlay: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        on_about: Optional[Callable[[], None]] = None,
    ):
        """Initialize the tray icon.

        Args:
            on_show_overlay: Callback to show overlay.
            on_hide_overlay: Callback to hide overlay.
            on_settings: Callback to open settings.
            on_exit: Callback to exit application.
            on_about: Callback to show about dialog.
        """
        self._on_show_overlay = on_show_overlay
        self._on_hide_overlay = on_hide_overlay
        self._on_settings = on_settings
        self._on_exit = on_exit
        self._on_about = on_about

        self._icon: Optional["pystray.Icon"] = None
        self._state = self.STATE_READY
        self._overlay_visible = True
        self._running = False

        # Icon images cache
        self._icons: dict[str, "Image.Image"] = {}
        self._app_icon: Optional["Image.Image"] = None

    def _load_app_icon(self) -> "Image.Image":
        """Load the app icon from cld_icon.png."""
        if self._app_icon is not None:
            return self._app_icon

        from cld.ui import get_app_icon_path
        icon_path = get_app_icon_path()
        if icon_path.exists():
            try:
                img = Image.open(icon_path)
                # Resize to 32x32 for tray
                self._app_icon = img.resize((32, 32), Image.Resampling.LANCZOS)
                logger.debug("Loaded tray icon from %s", icon_path)
                return self._app_icon
            except Exception as e:
                logger.warning("Failed to load app icon: %s", e)

        # Fallback to generated icon
        return self._create_icon_image("ready")

    def _create_icon_image(self, state: str) -> "Image.Image":
        """Create an icon image for the given state.

        Args:
            state: One of STATE_READY, STATE_RECORDING, STATE_PROCESSING.

        Returns:
            PIL Image for the icon.
        """
        # Icon size (Windows typically uses 16x16 or 32x32)
        size = 32

        # Colors based on state
        colors = {
            self.STATE_READY: "#ffffff",  # White (visible on dark taskbar)
            self.STATE_RECORDING: "#66ff66",  # Green
            self.STATE_PROCESSING: "#ffaa00",  # Amber
        }
        color = colors.get(state, colors[self.STATE_READY])

        # Create image
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Draw a simple microphone icon
        # Base circle
        margin = 4
        center = size // 2

        # Microphone body (rounded rectangle approximated with ellipse + rectangle)
        mic_width = 10
        mic_height = 14
        mic_left = center - mic_width // 2
        mic_top = margin
        mic_bottom = margin + mic_height

        # Mic head (top rounded)
        draw.ellipse(
            [mic_left, mic_top, mic_left + mic_width, mic_top + mic_width],
            fill=color,
        )
        # Mic body
        draw.rectangle(
            [mic_left, mic_top + mic_width // 2, mic_left + mic_width, mic_bottom],
            fill=color,
        )
        # Mic bottom rounded
        draw.ellipse(
            [mic_left, mic_bottom - mic_width, mic_left + mic_width, mic_bottom],
            fill=color,
        )

        # Stand arc
        arc_top = mic_bottom - 2
        arc_radius = 8
        draw.arc(
            [center - arc_radius, arc_top, center + arc_radius, arc_top + arc_radius * 2],
            start=0,
            end=180,
            fill=color,
            width=2,
        )

        # Stand base
        stand_y = arc_top + arc_radius + 2
        draw.line(
            [center, stand_y, center, size - margin],
            fill=color,
            width=2,
        )
        draw.line(
            [center - 5, size - margin, center + 5, size - margin],
            fill=color,
            width=2,
        )

        return image

    def _get_icon(self, state: str) -> "Image.Image":
        """Get the app icon (static, same for all states)."""
        # Use static app icon for all states
        if "app" not in self._icons:
            self._icons["app"] = self._load_app_icon()
        return self._icons["app"]

    def _create_menu(self) -> "pystray.Menu":
        """Create the tray menu."""
        return pystray.Menu(
            pystray.MenuItem(
                "Show Overlay" if not self._overlay_visible else "Hide Overlay",
                self._toggle_overlay,
                default=True,
            ),
            pystray.MenuItem("Settings...", self._open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("About CLD", self._show_about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )

    def _toggle_overlay(self, icon=None, item=None):
        """Toggle overlay visibility."""
        if self._overlay_visible:
            if self._on_hide_overlay:
                self._on_hide_overlay()
            self._overlay_visible = False
        else:
            if self._on_show_overlay:
                self._on_show_overlay()
            self._overlay_visible = True

        # Update menu
        if self._icon:
            self._icon.menu = self._create_menu()

    def _open_settings(self, icon=None, item=None):
        """Open settings dialog."""
        logger.info("Tray _open_settings called, callback=%s", self._on_settings)
        if self._on_settings:
            logger.info("Calling settings callback")
            self._on_settings()
        else:
            logger.warning("No settings callback registered")

    def _show_about(self, icon=None, item=None):
        """Show about dialog.

        Note: This runs from a background thread (pystray), so we use
        the callback to queue the dialog for the main thread.
        """
        logger.info("Tray _show_about called, callback=%s", self._on_about)
        if self._on_about:
            logger.info("Calling about callback")
            self._on_about()
        else:
            logger.info("CLD - ClaudeCli-Dictate: Local speech-to-text")

    def _exit(self, icon=None, item=None):
        """Exit the application."""
        self.stop()
        if self._on_exit:
            self._on_exit()

    def start(self):
        """Start the tray icon (non-blocking via run_detached)."""
        if not _TRAY_AVAILABLE:
            logger.warning("System tray not available")
            return False

        if self._running:
            return True

        # Force-remove any ghost icons left over from previous Icon
        # instances in this process (sleep/wake or crash-recovery leftovers).
        _sweep_stale_tray_windows()

        try:
            self._icon = pystray.Icon(
                name="CLD",
                icon=self._get_icon(self._state),
                title="CLD - Ready",
                menu=self._create_menu(),
            )

            # Run detached so it doesn't block the main thread
            self._icon.run_detached()
            self._running = True
            logger.info("Tray icon started")
            return True

        except Exception as e:
            logger.error("Failed to start tray icon: %s", e)
            return False

    def stop(self):
        """Stop the tray icon, with hard cleanup for sleep-wedged pystray.

        pystray.Icon.stop() just PostMessages WM_STOP and returns. If the
        Icon's mainloop thread is wedged or dead (common after sleep/wake),
        WM_STOP is never processed, NIM_DELETE is never sent, and the icon
        ghosts in Explorer until reboot. We:
          1. Record the icon's hwnds as "stale" before asking pystray to
             stop, so we can clean them up even if pystray's stop fails.
          2. Call pystray.Icon.stop() and give its thread up to 2s to drain.
          3. Force-remove via Shell_NotifyIcon(NIM_DELETE) regardless.
        """
        icon = self._icon
        self._icon = None
        self._running = False

        if icon is None:
            return

        # Capture hwnds BEFORE we touch the icon - they may be cleared by
        # pystray's cleanup if it succeeds, but we want them for our fallback
        # if it doesn't.
        hwnd = getattr(icon, "_hwnd", None) or 0
        menu_hwnd = getattr(icon, "_menu_hwnd", None) or 0
        worker = getattr(icon, "_thread", None)

        with _stale_lock:
            if hwnd:
                _stale_hwnds.add(int(hwnd))
            if menu_hwnd:
                _stale_hwnds.add(int(menu_hwnd))

        try:
            icon.stop()
        except Exception:
            logger.warning("pystray Icon.stop() failed", exc_info=True)

        # Give pystray's mainloop thread a brief window to process WM_STOP
        # and run its own NIM_DELETE / DestroyWindow. After the timeout we
        # do it ourselves anyway - belt and suspenders.
        if isinstance(worker, threading.Thread) and worker.is_alive() and \
                worker.ident != threading.current_thread().ident:
            worker.join(timeout=2.0)

        # Force-cleanup whether pystray finished or not.
        _sweep_stale_tray_windows()

    def restart(self):
        """Restart the tray icon (stop and start fresh).

        Used to recover the tray icon after sleep/hibernate when Windows
        may fail to send WM_TASKBARCREATED to restore icons.
        """
        logger.info("Restarting tray icon")
        if self._running:
            self.stop()
        return self.start()

    def set_state(self, state: str):
        """Update the tray icon state.

        Args:
            state: One of STATE_READY, STATE_RECORDING, STATE_PROCESSING.
        """
        self._state = state

        if not self._icon:
            return

        # Update icon
        self._icon.icon = self._get_icon(state)

        # Update tooltip
        titles = {
            self.STATE_READY: "CLD - Ready",
            self.STATE_RECORDING: "CLD - Recording...",
            self.STATE_PROCESSING: "CLD - Processing...",
        }
        self._icon.title = titles.get(state, "CLD")

    def set_overlay_visible(self, visible: bool):
        """Update overlay visibility state (for menu sync)."""
        self._overlay_visible = visible
        if self._icon:
            self._icon.menu = self._create_menu()

    def is_running(self) -> bool:
        """Check if tray icon is running."""
        return self._running
