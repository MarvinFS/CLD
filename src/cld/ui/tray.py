"""System tray integration for CLD using pystray."""

import logging
from typing import Callable, Optional

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
        """Stop the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        self._running = False

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
