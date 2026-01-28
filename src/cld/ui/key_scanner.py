"""Key scanner dialog for capturing activation keys."""

import logging
import queue
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Key name mappings for display
KEY_DISPLAY_NAMES = {
    "alt": "Alt (any)",
    "alt_gr": "Alt Gr",
    "alt_l": "Left Alt",
    "alt_r": "Right Alt",
    "ctrl": "Ctrl (any)",
    "ctrl_l": "Left Ctrl",
    "ctrl_r": "Right Ctrl",
    "shift": "Shift (any)",
    "shift_l": "Left Shift",
    "shift_r": "Right Shift",
    "space": "Space",
    "tab": "Tab",
    "caps_lock": "Caps Lock",
    "scroll_lock": "Scroll Lock",
    "num_lock": "Num Lock",
    "print_screen": "Print Screen",
    "pause": "Pause",
    "insert": "Insert",
    "delete": "Delete",
    "home": "Home",
    "end": "End",
    "page_up": "Page Up",
    "page_down": "Page Down",
}


@dataclass
class KeyCapture:
    """Captured key information."""

    key: str
    scancode: int
    display_name: str


class KeyScanner:
    """Dialog for capturing a single key press."""

    def __init__(
        self,
        parent: Optional[tk.Tk] = None,
        on_capture: Optional[Callable[[KeyCapture], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        on_scanning_start: Optional[Callable[[], None]] = None,
        on_scanning_end: Optional[Callable[[], None]] = None,
    ):
        """Initialize the key scanner.

        Args:
            parent: Parent window (for positioning).
            on_capture: Callback when key is confirmed.
            on_cancel: Callback when cancelled.
            on_scanning_start: Called when scanner starts (to suppress global hotkey).
            on_scanning_end: Called when scanner ends (to restore global hotkey).
        """
        self._parent = parent
        self._on_capture = on_capture
        self._on_cancel = on_cancel
        self._on_scanning_start = on_scanning_start
        self._on_scanning_end = on_scanning_end
        self._window: Optional[tk.Toplevel] = None
        self._pending_key: Optional[KeyCapture] = None
        self._timeout_id: Optional[str] = None
        self._keyboard_hook = None
        self._event_queue: queue.Queue = queue.Queue()
        self._poll_id: Optional[str] = None

        # Colors (dark theme)
        self._bg = "#1a1a1a"
        self._surface = "#242424"
        self._border = "#333333"
        self._text = "#ffffff"
        self._text_dim = "#888888"
        self._accent = "#4a9eff"

    def show(self):
        """Show the key scanner dialog."""
        if self._window:
            self._window.lift()
            return

        # Create window
        if self._parent:
            self._window = tk.Toplevel(self._parent)
        else:
            self._window = tk.Toplevel()

        self._window.title("Press a Key")
        self._window.configure(bg=self._bg)
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)

        # Size and position
        width, height = 320, 160
        if self._parent:
            px = self._parent.winfo_x()
            py = self._parent.winfo_y()
            pw = self._parent.winfo_width()
            ph = self._parent.winfo_height()
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
        else:
            x = (self._window.winfo_screenwidth() - width) // 2
            y = (self._window.winfo_screenheight() - height) // 2

        self._window.geometry(f"{width}x{height}+{x}+{y}")

        # Border frame
        border = tk.Frame(self._window, bg=self._border)
        border.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        container = tk.Frame(border, bg=self._bg)
        container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Title
        title = tk.Label(
            container,
            text="Press a Key",
            font=("Segoe UI Semibold", 12),
            fg=self._text,
            bg=self._bg,
        )
        title.pack(pady=(20, 10))

        # Instruction / key display
        self._key_label = tk.Label(
            container,
            text="Waiting for keypress...",
            font=("Consolas", 11),
            fg=self._text_dim,
            bg=self._surface,
            padx=20,
            pady=10,
        )
        self._key_label.pack(pady=10, padx=20, fill=tk.X)

        # Hint
        self._hint_label = tk.Label(
            container,
            text="ESC to cancel",
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._bg,
        )
        self._hint_label.pack(pady=(5, 15))

        # Grab focus
        self._window.focus_force()
        self._window.grab_set()

        # Notify that scanning is starting (to suppress global hotkey)
        if self._on_scanning_start:
            try:
                self._on_scanning_start()
            except Exception:
                pass

        # Start keyboard listener
        self._start_keyboard_listener()

        # Timeout after 30 seconds
        self._timeout_id = self._window.after(30000, self._on_timeout)

    def _start_keyboard_listener(self):
        """Start the keyboard hook to capture keys."""
        try:
            import keyboard

            def on_key(event):
                if event.event_type == "down":
                    # Queue the event for processing in main thread
                    self._event_queue.put(event)

            self._keyboard_hook = keyboard.hook(on_key)

            # Start polling the queue from main thread
            self._poll_queue()
        except ImportError:
            logger.error("keyboard library not installed")
            self._key_label.config(text="Error: keyboard library missing")
        except Exception as e:
            logger.error("Failed to start keyboard listener: %s", e)
            self._key_label.config(text=f"Error: {e}")

    def _poll_queue(self):
        """Poll the event queue from main thread."""
        if not self._window:
            return

        try:
            while True:
                event = self._event_queue.get_nowait()
                self._on_key_press(event)
        except queue.Empty:
            pass

        # Schedule next poll only if window still exists
        if self._window:
            try:
                self._poll_id = self._window.after(16, self._poll_queue)
            except Exception:
                pass  # Window may have been destroyed

    def _stop_keyboard_listener(self):
        """Stop the keyboard hook."""
        if self._keyboard_hook:
            try:
                import keyboard

                keyboard.unhook(self._keyboard_hook)
            except Exception:
                pass
            self._keyboard_hook = None

    def _on_key_press(self, event):
        """Handle a key press event."""
        if not self._window:
            return

        key_name = event.name.lower() if event.name else ""
        scancode = event.scan_code or 0

        # Handle escape - cancel
        if key_name == "esc" or key_name == "escape":
            self._cancel()
            return

        # Normalize key name
        normalized = self._normalize_key_name(key_name, scancode)
        display = KEY_DISPLAY_NAMES.get(normalized, key_name.upper() if len(key_name) == 1 else key_name.title())

        capture = KeyCapture(key=normalized, scancode=scancode, display_name=display)

        # Check if this is a confirmation (same key pressed twice)
        if self._pending_key and self._pending_key.scancode == scancode:
            self._confirm(capture)
            return

        # Store as pending and update UI
        self._pending_key = capture
        self._key_label.config(
            text=f"{display}\n(scancode: {scancode})",
            fg=self._accent,
        )
        self._hint_label.config(text="Press again to confirm, ESC to cancel")

    def _normalize_key_name(self, name: str, scancode: int) -> str:
        """Normalize key name for storage.

        Keeps specific variants (alt_gr, alt_l, alt_r) to allow users to
        configure exactly which key they want. The hotkey matcher will
        handle normalization based on the configured key.
        """
        name_lower = name.lower()

        # Alt keys - keep specific variants
        # Scancode 541 is specifically Alt Gr on Windows
        if scancode == 541 or name_lower == "alt gr":
            return "alt_gr"
        if name_lower == "right alt":
            return "alt_r"
        if name_lower == "left alt":
            return "alt_l"
        if name_lower == "alt":
            return "alt"  # Generic alt (will match any)

        # Ctrl keys - keep specific variants
        if name_lower in ("right ctrl", "right control"):
            return "ctrl_r"
        if name_lower in ("left ctrl", "left control"):
            return "ctrl_l"
        if name_lower in ("ctrl", "control"):
            return "ctrl"

        # Shift keys - keep specific variants
        if name_lower == "right shift":
            return "shift_r"
        if name_lower == "left shift":
            return "shift_l"
        if name_lower == "shift":
            return "shift"

        return name_lower.replace(" ", "_")

    def _confirm(self, capture: KeyCapture):
        """Confirm the key capture."""
        self._cleanup()
        if self._on_capture:
            self._on_capture(capture)

    def _cancel(self):
        """Cancel key capture."""
        self._cleanup()
        if self._on_cancel:
            self._on_cancel()

    def _on_timeout(self):
        """Handle timeout."""
        self._cancel()

    def _cleanup(self):
        """Clean up resources."""
        self._stop_keyboard_listener()

        # Cancel poll timer
        if self._poll_id and self._window:
            try:
                self._window.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

        if self._timeout_id and self._window:
            try:
                self._window.after_cancel(self._timeout_id)
            except Exception:
                pass
            self._timeout_id = None

        if self._window:
            try:
                self._window.grab_release()
                self._window.destroy()
            except Exception:
                pass
            self._window = None

        self._pending_key = None

        # Notify that scanning has ended (to restore global hotkey)
        if self._on_scanning_end:
            try:
                self._on_scanning_end()
            except Exception:
                pass


def scan_key(
    parent: Optional[tk.Tk] = None,
    callback: Optional[Callable[[Optional[KeyCapture]], None]] = None,
):
    """Convenience function to scan for a key.

    Args:
        parent: Parent window for positioning.
        callback: Called with KeyCapture on success, None on cancel.
    """

    def on_capture(capture: KeyCapture):
        if callback:
            callback(capture)

    def on_cancel():
        if callback:
            callback(None)

    scanner = KeyScanner(parent=parent, on_capture=on_capture, on_cancel=on_cancel)
    scanner.show()
