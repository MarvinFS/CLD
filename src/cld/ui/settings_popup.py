"""Quick settings popup for CLD overlay."""

import logging
import tkinter as tk
from typing import Callable, Optional

from cld.config import Config

logger = logging.getLogger(__name__)


class ToggleSwitch(tk.Canvas):
    """Custom toggle switch widget."""

    def __init__(
        self,
        parent,
        initial: bool = False,
        on_change: Optional[Callable[[bool], None]] = None,
        **kwargs,
    ):
        self._width = 44
        self._height = 24
        super().__init__(
            parent,
            width=self._width,
            height=self._height,
            highlightthickness=0,
            **kwargs,
        )

        self._value = initial
        self._on_change = on_change

        # Colors
        self._bg_off = "#404040"
        self._bg_on = "#4a9eff"
        self._knob_color = "#ffffff"

        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self):
        """Draw the toggle switch."""
        self.delete("all")

        # Background pill
        bg = self._bg_on if self._value else self._bg_off
        self.create_oval(0, 0, self._height, self._height, fill=bg, outline="")
        self.create_oval(
            self._width - self._height, 0, self._width, self._height, fill=bg, outline=""
        )
        self.create_rectangle(
            self._height // 2,
            0,
            self._width - self._height // 2,
            self._height,
            fill=bg,
            outline="",
        )

        # Knob
        padding = 3
        knob_size = self._height - 2 * padding
        if self._value:
            knob_x = self._width - self._height + padding
        else:
            knob_x = padding

        self.create_oval(
            knob_x,
            padding,
            knob_x + knob_size,
            padding + knob_size,
            fill=self._knob_color,
            outline="",
        )

    def _toggle(self, event=None):
        """Toggle the switch."""
        self._value = not self._value
        self._draw()
        if self._on_change:
            self._on_change(self._value)

    def get(self) -> bool:
        """Get current value."""
        return self._value

    def set(self, value: bool):
        """Set value without triggering callback."""
        self._value = value
        self._draw()


class SettingsPopup:
    """Quick settings popup that appears above the overlay."""

    def __init__(
        self,
        parent: tk.Tk,
        config: Config,
        on_settings_click: Optional[Callable[[], None]] = None,
        on_change: Optional[Callable[[Config], None]] = None,
        on_hide_overlay: Optional[Callable[[], None]] = None,
    ):
        """Initialize the settings popup.

        Args:
            parent: Parent window (the overlay).
            config: Current configuration.
            on_settings_click: Callback when "All Settings" is clicked.
            on_change: Callback when a setting changes.
            on_hide_overlay: Callback when "Hide Overlay" is clicked.
        """
        self._parent = parent
        self._config = config
        self._on_settings_click = on_settings_click
        self._on_change = on_change
        self._on_hide_overlay = on_hide_overlay
        self._window: Optional[tk.Toplevel] = None
        self._toggles: dict[str, ToggleSwitch] = {}

        # Colors (dark theme)
        self._bg = "#1a1a1a"
        self._surface = "#242424"
        self._border = "#333333"
        self._text = "#ffffff"
        self._text_dim = "#888888"
        self._accent = "#4a9eff"

    def show(self):
        """Show the popup above the parent window."""
        if self._window:
            self._window.lift()
            return

        self._window = tk.Toplevel(self._parent)
        self._window.title("")
        self._window.configure(bg=self._bg)
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)

        # Calculate position (above parent, centered)
        width, height = 300, 220
        px = self._parent.winfo_x()
        py = self._parent.winfo_y()
        pw = self._parent.winfo_width()

        x = px + (pw - width) // 2
        y = py - height - 10  # 10px gap above overlay

        # Ensure on screen
        if y < 10:
            y = py + self._parent.winfo_height() + 10  # Below if no room above

        self._window.geometry(f"{width}x{height}+{x}+{y}")

        # Border frame
        border = tk.Frame(self._window, bg=self._border)
        border.pack(fill=tk.BOTH, expand=True)

        container = tk.Frame(border, bg=self._bg)
        container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Title bar
        title_frame = tk.Frame(container, bg=self._surface)
        title_frame.pack(fill=tk.X, padx=8, pady=(8, 0))

        title = tk.Label(
            title_frame,
            text="Quick Settings",
            font=("Segoe UI Semibold", 10),
            fg=self._text,
            bg=self._surface,
        )
        title.pack(side=tk.LEFT, padx=8, pady=6)

        # Close button
        close_btn = tk.Label(
            title_frame,
            text="\u2715",
            font=("Segoe UI", 10),
            fg=self._text_dim,
            bg=self._surface,
            cursor="hand2",
        )
        close_btn.pack(side=tk.RIGHT, padx=8, pady=6)
        close_btn.bind("<Button-1>", lambda e: self.hide())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=self._text))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=self._text_dim))

        # Settings list
        settings_frame = tk.Frame(container, bg=self._bg)
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Toggle settings
        self._add_toggle(
            settings_frame,
            "Hotkey Enabled",
            self._config.activation.enabled,
            self._on_hotkey_enabled_change,
        )
        self._add_toggle(
            settings_frame,
            "Sound Effects",
            self._config.output.sound_effects,
            self._on_sound_effects_change,
        )
        self._add_toggle(
            settings_frame,
            "Hide Overlay",
            False,  # Always starts as "off" - it's an action, not a setting
            self._on_hide_overlay_change,
        )

        # Divider
        divider = tk.Frame(container, bg=self._border, height=1)
        divider.pack(fill=tk.X, padx=16, pady=(4, 8))

        # All Settings link
        link = tk.Label(
            container,
            text="All Settings...",
            font=("Segoe UI", 10),
            fg=self._accent,
            bg=self._bg,
            cursor="hand2",
        )
        link.pack(pady=(0, 12))
        link.bind("<Button-1>", self._on_all_settings_click)
        link.bind("<Enter>", lambda e: link.config(font=("Segoe UI Underline", 10)))
        link.bind("<Leave>", lambda e: link.config(font=("Segoe UI", 10)))

        # Bind escape
        self._window.bind("<Escape>", lambda e: self.hide())

        # Focus
        self._window.focus_force()

    def _add_toggle(
        self,
        parent: tk.Frame,
        label: str,
        initial: bool,
        on_change: Callable[[bool], None],
        disabled: bool = False,
    ):
        """Add a toggle setting row."""
        row = tk.Frame(parent, bg=self._bg)
        row.pack(fill=tk.X, pady=4)

        lbl = tk.Label(
            row,
            text=label,
            font=("Segoe UI", 10),
            fg=self._text_dim if disabled else self._text,
            bg=self._bg,
            anchor="w",
        )
        lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        toggle = ToggleSwitch(
            row,
            initial=initial,
            on_change=None if disabled else on_change,
            bg=self._bg,
        )
        toggle.pack(side=tk.RIGHT)
        if disabled:
            toggle.unbind("<Button-1>")  # Disable click

        self._toggles[label] = toggle

    def _on_hotkey_enabled_change(self, value: bool):
        """Handle hotkey enabled toggle."""
        self._config.activation.enabled = value
        self._save_and_notify()

    def _on_sound_effects_change(self, value: bool):
        """Handle sound effects toggle."""
        self._config.output.sound_effects = value
        self._save_and_notify()

    def _on_hide_overlay_change(self, value: bool):
        """Handle hide overlay toggle."""
        if value and self._on_hide_overlay:
            self.hide()  # Close popup first
            self._on_hide_overlay()

    def _save_and_notify(self):
        """Save config and notify listener."""
        self._config.save()
        if self._on_change:
            self._on_change(self._config)

    def _on_all_settings_click(self, event=None):
        """Handle click on All Settings link."""
        self.hide()
        if self._on_settings_click:
            self._on_settings_click()

    def hide(self):
        """Hide the popup."""
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def is_visible(self) -> bool:
        """Check if popup is visible."""
        return self._window is not None

    def update_config(self, config: Config):
        """Update displayed values from config."""
        self._config = config
        if self._window and self._toggles:
            # Update toggle states
            for name, toggle in self._toggles.items():
                if "Hotkey Enabled" in name:
                    toggle.set(config.activation.enabled)
                elif "Sound Effects" in name:
                    toggle.set(config.output.sound_effects)
