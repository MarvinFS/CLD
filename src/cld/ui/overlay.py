"""Floating overlay GUI for CLD status display with tiny mode and settings access."""

import logging
import math
import queue
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageTk

logger = logging.getLogger(__name__)

# Animation frame interval in milliseconds (approximately 30 FPS)
ANIMATION_FRAME_MS = 33


def _is_frozen() -> bool:
    """Check if running as frozen exe (PyInstaller or Nuitka)."""
    # PyInstaller sets sys.frozen
    if getattr(sys, "frozen", False):
        return True
    # Nuitka sets __compiled__ on __main__
    main_mod = sys.modules.get("__main__", object())
    return "__compiled__" in dir(main_mod)


def _get_mic_icon_path() -> Path:
    """Get path to mic icon file."""
    if _is_frozen():
        exe_dir = Path(sys.executable).parent
        # Nuitka: file next to exe
        nuitka_path = exe_dir / "mic_256.png"
        if nuitka_path.exists():
            return nuitka_path
        # PyInstaller: in _internal/
        return exe_dir / "_internal" / "mic_256.png"
    # Running from source
    return Path(__file__).parent.parent.parent.parent / "mic_256.png"


class STTOverlay:
    """Floating overlay window showing STT status with waveform visualization.

    Supports two display modes:
    - Normal: Full overlay with timer, waveform, status, and gear button
    - Tiny: Compact dot indicator (~24x24) with drag handle

    State machine: TINY <-> READY -> RECORDING -> TRANSCRIBING -> READY
    """

    # Display modes
    MODE_NORMAL = "normal"
    MODE_TINY = "tiny"

    def has_window(self) -> bool:
        """Check if the overlay window exists."""
        return self._root is not None

    def get_root(self) -> "tk.Tk | None":
        """Get the root window for parent relationships (may be None)."""
        return self._root

    def __init__(
        self,
        on_close: Optional[Callable] = None,
        on_settings: Optional[Callable] = None,
        get_audio_level: Optional[Callable[[], float]] = None,
        get_audio_spectrum: Optional[Callable[[], list[float]]] = None,
    ):
        """Initialize the overlay.

        Args:
            on_close: Callback when overlay is closed.
            on_settings: Callback when gear button is clicked.
            get_audio_level: Callback to get current audio level (0.0-1.0).
            get_audio_spectrum: Callback to get 16-band spectrum (list of 0.0-1.0).
        """
        self.on_close = on_close
        self.on_settings = on_settings
        self._get_audio_level = get_audio_level
        self._get_audio_spectrum = get_audio_spectrum

        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None
        self._drag_canvas: Optional[tk.Canvas] = None
        self._tiny_canvas: Optional[tk.Canvas] = None
        self._separator_canvas: Optional[tk.Canvas] = None
        self._timer_label: Optional[tk.Label] = None
        self._status_label: Optional[tk.Label] = None
        self._gear_btn: Optional[tk.Label] = None
        self._tiny_gear: Optional[tk.Label] = None
        self._main_container: Optional[tk.Frame] = None
        self._mic_photo: Optional[ImageTk.PhotoImage] = None  # Keep reference to prevent GC
        self._mic_base_image: Optional[Image.Image] = None  # Base white mic icon

        self._state = "ready"
        self._mode = self.MODE_NORMAL
        self._animation_id: Optional[str] = None
        self._running = False
        self._record_start_time: float = 0
        self._audio_levels: list[float] = [0.3] * 16  # 16 bars
        self._state_queue: queue.Queue = queue.Queue()  # Thread-safe state updates

        # Dragging state
        self._drag_x = 0
        self._drag_y = 0

        # Mode switch protection
        self._mode_switching = False  # Prevent concurrent mode switches
        self._last_gear_click = 0.0   # Debounce gear clicks

        # Window dimensions
        self._normal_width = 300
        self._normal_height = 80
        self._tiny_width = 120
        self._tiny_height = 40

        # Colors (dark theme - Industrial/Recording Studio)
        self._bg_color = "#1a1a1a"
        self._surface_color = "#242424"
        self._border_color = "#333333"
        self._bar_color_idle = "#444444"
        self._bar_color_active = "#ffffff"
        self._bar_color_recording = "#66ff66"
        self._timer_color = "#888888"
        self._status_color = "#666666"
        self._accent_color = "#4a9eff"
        self._green = "#66ff66"
        self._amber = "#ffaa00"
        self._red = "#ff4444"

        # Tiny mode colors (Microsoft Voice Typing style)
        self._tiny_bg = "#2d2d2d"  # Slightly lighter than black - visible on dark taskbars
        self._tiny_drag_bg = "#1f1f1f"  # Darker drag bar area
        self._tiny_shadow = "#0a0a0a"  # Shadow color for depth
        self._mic_idle = "#999999"  # Brighter gray mic (was #666666)
        self._mic_active = "#66ff66"  # Green when recording
        self._mic_busy = "#ffaa00"  # Amber when processing

    def _apply_rounded_corners(self, radius: int = 8):
        """Apply rounded corners to window using Win32 API."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            # Get the HWND
            hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
            if not hwnd:
                hwnd = ctypes.windll.user32.GetAncestor(self._root.winfo_id(), 2)  # GA_ROOT
            if hwnd:
                # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                value = ctypes.c_int(2)  # DWMWCP_ROUND
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:
            pass

    def _enable_shadow(self):
        """Enable drop shadow using DWM."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
            if not hwnd:
                hwnd = ctypes.windll.user32.GetAncestor(self._root.winfo_id(), 2)  # GA_ROOT
            if hwnd:
                # Enable non-client rendering for shadow
                DWMWA_NCRENDERING_POLICY = 2
                value = ctypes.c_int(2)  # DWMNCRP_ENABLED
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_NCRENDERING_POLICY,
                    ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:
            pass

    def _create_window(self):
        """Create the overlay window."""
        self._root = tk.Tk()
        self._root.title("CLD")
        self._root.overrideredirect(True)  # No window decorations
        self._root.attributes("-topmost", True)  # Always on top
        self._root.configure(bg=self._bg_color)

        # Position in bottom-center of screen
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = (screen_w - self._normal_width) // 2
        y = screen_h - self._normal_height - 100  # Above taskbar
        self._root.geometry(f"{self._normal_width}x{self._normal_height}+{x}+{y}")

        # Store position for mode switching
        self._pos_x = x
        self._pos_y = y

        # Build normal mode UI
        self._build_normal_ui()

        # Apply Windows 11 rounded corners and shadow
        self._root.update()
        self._apply_rounded_corners()
        self._enable_shadow()

        self._root.protocol("WM_DELETE_WINDOW", self._close)

    def _build_normal_ui(self):
        """Build the normal mode UI."""
        # Main container with border
        self._main_container = tk.Frame(
            self._root,
            bg=self._bg_color,
            highlightbackground=self._border_color,
            highlightthickness=1,
        )
        self._main_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Make window draggable
        self._main_container.bind("<Button-1>", self._start_drag)
        self._main_container.bind("<B1-Motion>", self._on_drag)

        # Right-click to close
        self._main_container.bind("<Button-3>", lambda e: self._close())

        # Top row: timer, status, and gear button
        top_frame = tk.Frame(self._main_container, bg=self._bg_color)
        top_frame.pack(fill=tk.X, padx=12, pady=(10, 5))

        # Timer on left
        self._timer_label = tk.Label(
            top_frame,
            text="00:00.0",
            font=("Consolas", 14),
            fg=self._timer_color,
            bg=self._bg_color,
        )
        self._timer_label.pack(side=tk.LEFT)
        self._timer_label.bind("<Button-1>", self._start_drag)
        self._timer_label.bind("<B1-Motion>", self._on_drag)

        # Gear button on right (settings)
        self._gear_btn = tk.Label(
            top_frame,
            text="\u2699",  # Gear unicode
            font=("Segoe UI Symbol", 14),
            fg=self._status_color,
            bg=self._bg_color,
            cursor="hand2",
        )
        self._gear_btn.pack(side=tk.RIGHT)
        self._gear_btn.bind("<Button-1>", self._on_gear_click)
        self._gear_btn.bind("<Enter>", lambda e: self._gear_btn.config(fg=self._accent_color))
        self._gear_btn.bind("<Leave>", lambda e: self._gear_btn.config(fg=self._status_color))

        # Minimize button (to tiny mode)
        self._min_btn = tk.Label(
            top_frame,
            text="\u2212",  # Minus sign
            font=("Segoe UI", 12),
            fg=self._status_color,
            bg=self._bg_color,
            cursor="hand2",
        )
        self._min_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self._min_btn.bind("<Button-1>", lambda e: self._switch_to_tiny())
        self._min_btn.bind("<Enter>", lambda e: self._min_btn.config(fg=self._accent_color))
        self._min_btn.bind("<Leave>", lambda e: self._min_btn.config(fg=self._status_color))

        # Status in middle-right
        self._status_label = tk.Label(
            top_frame,
            text="Ready",
            font=("Segoe UI", 10),
            fg=self._status_color,
            bg=self._bg_color,
        )
        self._status_label.pack(side=tk.RIGHT, padx=(0, 12))
        self._status_label.bind("<Button-1>", self._start_drag)
        self._status_label.bind("<B1-Motion>", self._on_drag)

        # Waveform canvas
        self._canvas = tk.Canvas(
            self._main_container,
            width=270,
            height=30,
            bg=self._bg_color,
            highlightthickness=0,
        )
        self._canvas.pack(pady=(0, 8))
        self._canvas.bind("<Button-1>", self._start_drag)
        self._canvas.bind("<B1-Motion>", self._on_drag)

        # Draw initial idle bars
        self._draw_waveform(idle=True)

    def _build_tiny_ui(self):
        """Build the tiny mode UI (Windows Voice Typing style)."""
        # Tiny container with lighter background (visible on dark taskbars)
        self._main_container = tk.Frame(
            self._root,
            bg=self._tiny_bg,  # Lighter background like Windows Voice Typing
            highlightthickness=0,
        )
        self._main_container.pack(fill=tk.BOTH, expand=True)

        # Horizontal layout: vertical bar | gear | mic | menu dots
        inner = tk.Frame(self._main_container, bg=self._tiny_bg)
        inner.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Vertical separator bar (left edge) - Windows Voice Typing style
        self._separator_canvas = tk.Canvas(
            inner,
            width=6,
            height=self._tiny_height,
            bg=self._tiny_bg,
            highlightthickness=0,
        )
        self._separator_canvas.pack(side=tk.LEFT, padx=(4, 2))
        # Draw rounded vertical bar
        self._separator_canvas.create_rectangle(
            1, 8, 5, self._tiny_height - 8,
            fill="#555555", outline="", width=0
        )

        # Gear button
        self._tiny_gear = tk.Label(
            inner,
            text="\u2699",
            font=("Segoe UI Symbol", 11),
            fg="#888888",  # Brighter gear
            bg=self._tiny_bg,
            cursor="hand2",
        )
        self._tiny_gear.pack(side=tk.LEFT, padx=(2, 4))
        self._tiny_gear.bind("<Button-1>", self._on_gear_click)
        self._tiny_gear.bind("<Enter>", lambda e: self._tiny_gear.config(fg=self._accent_color))
        self._tiny_gear.bind("<Leave>", lambda e: self._tiny_gear.config(fg="#888888"))

        # Canvas for microphone icon (center)
        self._canvas = tk.Canvas(
            inner,
            width=36,
            height=self._tiny_height - 4,
            bg=self._tiny_bg,
            highlightthickness=0,
        )
        self._canvas.pack(side=tk.LEFT, expand=True)
        self._canvas.bind("<Double-Button-1>", lambda e: self._switch_to_normal())
        self._canvas.bind("<Button-3>", lambda e: self._close())

        # Draw the microphone icon
        self._draw_tiny_mic()

        # Menu dots (right side) - 3 vertical dots like Windows Voice Typing
        self._drag_canvas = tk.Canvas(
            inner,
            width=20,
            height=self._tiny_height - 4,
            bg=self._tiny_bg,
            highlightthickness=0,
            cursor="fleur",
        )
        self._drag_canvas.pack(side=tk.RIGHT, padx=(4, 6))
        self._draw_menu_dots()

        # Drag bindings on menu dots
        self._drag_canvas.bind("<Button-1>", self._start_drag)
        self._drag_canvas.bind("<B1-Motion>", self._on_drag)

        # Right-click to close on main container
        self._main_container.bind("<Button-3>", lambda e: self._close())

    def _load_mic_icon(self):
        """Load the base mic icon image."""
        if self._mic_base_image is not None:
            return

        try:
            icon_path = _get_mic_icon_path()
            if icon_path.exists():
                self._mic_base_image = Image.open(icon_path).convert("RGBA")
                logger.debug("Loaded mic icon from %s", icon_path)
            else:
                logger.warning("Mic icon not found at %s", icon_path)
        except Exception as e:
            logger.warning("Failed to load mic icon: %s", e)

    def _tint_image(self, image: Image.Image, color: str) -> Image.Image:
        """Tint a white image to the specified color."""
        # Parse hex color
        color = color.lstrip("#")
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)

        # Create tinted version
        data = image.getdata()
        new_data = []
        for item in data:
            # Replace white pixels with tint color, preserve alpha
            if item[3] > 0:  # Has some alpha
                # Blend based on original brightness
                brightness = item[0] / 255.0
                new_data.append((
                    int(r * brightness),
                    int(g * brightness),
                    int(b * brightness),
                    item[3]
                ))
            else:
                new_data.append(item)

        tinted = Image.new("RGBA", image.size)
        tinted.putdata(new_data)
        return tinted

    def _draw_tiny_mic(self):
        """Draw microphone icon using PNG with color tinting."""
        if not self._canvas:
            return

        self._canvas.delete("all")

        # Canvas dimensions
        w = 40
        h = self._tiny_height - 8
        cx = w // 2
        cy = h // 2

        # Color based on state - brighter idle icon
        colors = {
            "ready": self._mic_idle,  # Brighter gray (#999999)
            "recording": self._green,
            "transcribing": self._amber,
            "error": self._red,
        }
        color = colors.get(self._state, self._mic_idle)

        # Try to use PNG icon
        self._load_mic_icon()
        if self._mic_base_image is not None:
            try:
                # Resize to fit canvas (24x24 looks good)
                icon_size = 24
                resized = self._mic_base_image.resize((icon_size, icon_size), Image.Resampling.LANCZOS)

                # Tint to current state color
                tinted = self._tint_image(resized, color)

                # Convert to PhotoImage
                self._mic_photo = ImageTk.PhotoImage(tinted)

                # Draw centered
                self._canvas.create_image(cx, cy, image=self._mic_photo, anchor=tk.CENTER)

                # Pulsing glow effect for recording
                if self._state == "recording":
                    pulse = abs(math.sin(time.time() * 3)) * 0.4 + 0.6
                    glow_r = int(14 * pulse)
                    self._canvas.create_oval(
                        cx - glow_r, cy - glow_r,
                        cx + glow_r, cy + glow_r,
                        outline="#66ff66", width=2
                    )
                return
            except Exception as e:
                logger.warning("Failed to draw PNG mic: %s", e)

        # Fallback: draw mic using canvas primitives
        mic_w = 8
        mic_h = 12
        mic_top = cy - mic_h // 2 - 2

        self._canvas.create_oval(
            cx - mic_w // 2, mic_top,
            cx + mic_w // 2, mic_top + mic_w,
            fill=color, outline=""
        )
        self._canvas.create_rectangle(
            cx - mic_w // 2, mic_top + mic_w // 2,
            cx + mic_w // 2, mic_top + mic_h,
            fill=color, outline=""
        )
        self._canvas.create_oval(
            cx - mic_w // 2, mic_top + mic_h - mic_w,
            cx + mic_w // 2, mic_top + mic_h,
            fill=color, outline=""
        )

        arc_top = mic_top + mic_h - 1
        arc_r = 6
        self._canvas.create_arc(
            cx - arc_r, arc_top,
            cx + arc_r, arc_top + arc_r * 2,
            start=0, extent=180,
            style=tk.ARC, outline=color, width=2
        )

        stand_y = arc_top + arc_r + 1
        self._canvas.create_line(cx, stand_y, cx, h - 2, fill=color, width=2)
        self._canvas.create_line(cx - 4, h - 2, cx + 4, h - 2, fill=color, width=2)

        if self._state == "recording":
            pulse = abs(math.sin(time.time() * 3)) * 0.4 + 0.6
            glow_r = int(14 * pulse)
            self._canvas.create_oval(
                cx - glow_r, cy - glow_r,
                cx + glow_r, cy + glow_r,
                outline="#66ff66", width=2
            )

    def _draw_drag_handle(self):
        """Draw the drag handle (3 horizontal lines)."""
        if not self._drag_canvas:
            return

        self._drag_canvas.delete("all")

        w = 24
        h = self._tiny_height - 8
        line_w = 12
        line_gap = 5
        start_x = (w - line_w) // 2
        start_y = h // 2 - line_gap

        color = self._border_color

        for i in range(3):
            y = start_y + i * line_gap
            self._drag_canvas.create_line(
                start_x, y, start_x + line_w, y,
                fill=color, width=2
            )

    def _draw_menu_dots(self):
        """Draw menu dots (3 vertical dots) - Windows Voice Typing style."""
        if not self._drag_canvas:
            return

        self._drag_canvas.delete("all")

        w = 20
        h = self._tiny_height - 4
        cx = w // 2
        dot_r = 2
        dot_gap = 6
        start_y = h // 2 - dot_gap

        color = "#777777"  # Lighter dots

        for i in range(3):
            y = start_y + i * dot_gap
            self._drag_canvas.create_oval(
                cx - dot_r, y - dot_r,
                cx + dot_r, y + dot_r,
                fill=color, outline=""
            )

    def _save_position_and_clear_ui(self):
        """Save window position and destroy current UI elements."""
        self._pos_x = self._root.winfo_x()
        self._pos_y = self._root.winfo_y()

        if self._main_container:
            self._main_container.destroy()
            self._main_container = None
        self._canvas = None
        self._drag_canvas = None
        self._tiny_canvas = None
        self._tiny_gear = None
        self._timer_label = None
        self._status_label = None
        self._gear_btn = None
        self._separator_canvas = None

    def _animate_to_size(self, target_w: int, target_h: int, steps: int = 8, duration_ms: int = 120, callback=None):
        """Animate window resize from current size to target size.

        Args:
            target_w: Target width.
            target_h: Target height.
            steps: Number of animation steps.
            duration_ms: Total animation duration in milliseconds.
            callback: Function to call after animation completes.
        """
        if not self._root:
            if callback:
                callback()
            return

        current_w = self._root.winfo_width()
        current_h = self._root.winfo_height()

        # Calculate step deltas
        dw = (target_w - current_w) / steps
        dh = (target_h - current_h) / steps
        interval = duration_ms // steps

        def step(i):
            if not self._root or i >= steps:
                # Final position
                if self._root:
                    self._root.geometry(f"{target_w}x{target_h}+{self._pos_x}+{self._pos_y}")
                if callback:
                    callback()
                return

            # Interpolate size
            new_w = int(current_w + dw * (i + 1))
            new_h = int(current_h + dh * (i + 1))
            self._root.geometry(f"{new_w}x{new_h}+{self._pos_x}+{self._pos_y}")
            self._root.after(interval, lambda: step(i + 1))

        step(0)

    def _switch_to_tiny(self):
        """Switch to tiny mode with smooth animation."""
        if self._mode == self.MODE_TINY or self._mode_switching:
            return

        self._mode_switching = True
        self._mode = self.MODE_TINY
        self._save_position_and_clear_ui()

        # Callback to build UI and apply visual effects
        def after_anim():
            self._build_tiny_ui()
            self._root.update()
            self._apply_rounded_corners()
            self._enable_shadow()
            self._mode_switching = False

        # Animate to new size
        self._animate_to_size(self._tiny_width, self._tiny_height, callback=after_anim)

    def _switch_to_normal(self):
        """Switch to normal mode with smooth animation."""
        if self._mode == self.MODE_NORMAL or self._mode_switching:
            return

        self._mode_switching = True
        self._mode = self.MODE_NORMAL
        self._save_position_and_clear_ui()

        # Animate to new size, then build UI
        def after_anim():
            self._build_normal_ui()
            self._apply_state(self._state)
            self._mode_switching = False

        self._animate_to_size(self._normal_width, self._normal_height, callback=after_anim)

    def _on_gear_click(self, event):
        """Handle gear button click with debounce."""
        # Debounce rapid clicks (500ms)
        now = time.time()
        if now - self._last_gear_click < 0.5:
            return
        self._last_gear_click = now

        if self.on_settings:
            self.on_settings()

    def _start_drag(self, event):
        """Start dragging the window."""
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        """Handle window dragging."""
        x = self._root.winfo_x() + event.x - self._drag_x
        y = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _draw_waveform(self, idle: bool = False):
        """Draw audio waveform bars (normal mode only)."""
        if not self._canvas or self._mode == self.MODE_TINY:
            return

        self._canvas.delete("all")

        num_bars = 16
        bar_width = 6
        bar_gap = 4
        total_width = num_bars * bar_width + (num_bars - 1) * bar_gap
        start_x = (270 - total_width) // 2
        baseline_y = 28  # Bottom of waveform area
        max_height = 24

        for i in range(num_bars):
            if idle:
                height = 2  # Minimal height when idle
                color = self._bar_color_idle
            else:
                level = self._audio_levels[i]
                height = max(2, int(level * max_height))
                # Gradient color based on level: dim green -> bright green -> yellow-white
                if self._state == "recording":
                    # Interpolate from dim green (0x33, 0x99, 0x33) to bright green-yellow
                    intensity = min(1.0, level * 1.5)  # Boost for visibility
                    r = int(0x33 + (0xcc - 0x33) * intensity)
                    g = int(0x99 + (0xff - 0x99) * intensity)
                    b = int(0x33 + (0x66 - 0x33) * intensity)
                    color = f"#{r:02x}{g:02x}{b:02x}"
                else:
                    color = self._bar_color_active

            x = start_x + i * (bar_width + bar_gap)
            # Draw bar expanding upward from baseline
            self._canvas.create_rectangle(
                x,
                baseline_y - height,
                x + bar_width,
                baseline_y,
                fill=color,
                outline="",
            )

    def _update_timer(self):
        """Update the recording timer display."""
        if not self._timer_label:
            return

        if self._state == "recording" and self._record_start_time > 0:
            elapsed = time.time() - self._record_start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            tenths = int((elapsed % 1) * 10)
            self._timer_label.config(text=f"{mins:02d}:{secs:02d}.{tenths}")
        elif self._state == "transcribing":
            self._timer_label.config(text="...")
        else:
            self._timer_label.config(text="00:00.0")

    def _animate(self):
        """Animation loop for waveform."""
        if not self._running:
            return

        # Skip animation when idle - save CPU
        if self._state not in ("recording", "transcribing"):
            return

        if self._mode == self.MODE_TINY:
            # Tiny mode animation (redraw mic for pulse effect)
            if self._state in ("recording", "transcribing"):
                self._draw_tiny_mic()
                self._animation_id = self._root.after(50, self._animate)
            return

        if self._state == "recording":
            # Get real FFT spectrum bands from microphone
            spectrum = [0.0] * 16
            if self._get_audio_spectrum:
                try:
                    spectrum = self._get_audio_spectrum()
                except Exception:
                    pass

            # Update bars with real spectrum data - each bar is independent
            for i in range(16):
                # Smooth transition: 70% new, 30% old for responsive feel
                self._audio_levels[i] = 0.7 * spectrum[i] + 0.3 * self._audio_levels[i]
                # Clamp to valid range
                self._audio_levels[i] = max(0.03, min(1.0, self._audio_levels[i]))

            self._draw_waveform(idle=False)
            self._update_timer()
            self._animation_id = self._root.after(ANIMATION_FRAME_MS, self._animate)

        elif self._state == "transcribing":
            # Gentle pulsing for transcribing state
            t = time.time() * 1.5
            self._audio_levels = [
                0.25 + 0.25 * abs(math.sin(t + i * 0.2)) for i in range(16)
            ]
            self._draw_waveform(idle=False)
            self._update_timer()
            self._animation_id = self._root.after(50, self._animate)

        else:
            self._draw_waveform(idle=True)
            self._update_timer()

    def set_state(self, state: str):
        """Update the overlay state (thread-safe).

        Args:
            state: One of 'ready', 'recording', 'transcribing', 'error'
        """
        # Put state in queue - will be processed by main thread
        try:
            self._state_queue.put_nowait(state)
        except Exception:
            pass

    def process_queue(self):
        """Process pending state updates (call from main thread)."""
        try:
            while True:
                state = self._state_queue.get_nowait()
                self._apply_state(state)
        except queue.Empty:
            pass

    def _apply_state(self, state: str):
        """Apply state change (must be called from main thread)."""
        if not self._root:
            return

        prev_state = self._state
        self._state = state

        # Cancel any running animation
        if self._animation_id:
            self._root.after_cancel(self._animation_id)
            self._animation_id = None

        # Auto-expand from tiny mode when recording starts
        if state == "recording" and self._mode == self.MODE_TINY:
            self._switch_to_normal()

        if self._mode == self.MODE_TINY:
            # Just update the mic icon
            self._draw_tiny_mic()
            if state in ("recording", "transcribing"):
                self._animate()
            return

        if state == "recording":
            if prev_state != "recording":
                self._record_start_time = time.time()
            if self._status_label:
                self._status_label.config(text="Recording", fg=self._green)
            if self._timer_label:
                self._timer_label.config(fg="#ffffff")
            self._animate()

        elif state == "transcribing":
            if self._status_label:
                self._status_label.config(text="Transcribing", fg=self._amber)
            if self._timer_label:
                self._timer_label.config(fg=self._timer_color)
            self._animate()

        elif state == "error":
            if self._status_label:
                self._status_label.config(text="Error", fg=self._red)
            if self._timer_label:
                self._timer_label.config(fg=self._timer_color)
            self._draw_waveform(idle=True)
            self._update_timer()

        else:  # ready
            if self._status_label:
                self._status_label.config(text="Ready", fg=self._status_color)
            if self._timer_label:
                self._timer_label.config(fg=self._timer_color)
            self._record_start_time = 0
            self._draw_waveform(idle=True)
            self._update_timer()
            # Auto-collapse to tiny mode after 2 seconds in ready state
            if prev_state in ("recording", "transcribing") and self._mode == self.MODE_NORMAL:
                self._root.after(2000, self._auto_collapse_to_tiny)

    def _auto_collapse_to_tiny(self):
        """Auto-collapse to tiny mode if still in ready state."""
        if self._state == "ready" and self._mode == self.MODE_NORMAL:
            self._switch_to_tiny()

    def set_audio_level(self, level: float):
        """Set current audio level (0.0 to 1.0) for visualization."""
        if self._state == "recording":
            # Shift levels and add new one
            self._audio_levels = self._audio_levels[1:] + [level]

    def show(self):
        """Show and start the overlay (must be called from main thread)."""
        logger.info("Overlay.show() called")
        self._running = True
        self._create_window()
        logger.info("Overlay window created, root=%s", self._root)
        self.set_state("ready")
        # Start in tiny mode - will expand when recording starts
        self._root.after(100, self._switch_to_tiny)
        logger.info("Overlay show complete, scheduled tiny mode switch")

    def unhide(self):
        """Unhide a hidden overlay."""
        if self._root:
            self._root.deiconify()
            # Restore position on screen
            screen_w = self._root.winfo_screenwidth()
            x = max(0, min(self._pos_x, screen_w - 50))
            y = self._pos_y
            if self._mode == self.MODE_TINY:
                self._root.geometry(f"{self._tiny_width}x{self._tiny_height}+{x}+{y}")
            else:
                self._root.geometry(f"{self._normal_width}x{self._normal_height}+{x}+{y}")
            self._root.lift()

    def hide(self):
        """Hide the overlay by moving off-screen.

        Note: We don't use withdraw() because a withdrawn window doesn't pump
        Windows messages. Moving off-screen keeps the window 'visible' to Windows
        so it continues to process messages for dialogs.
        """
        if self._root:
            # Save current position before hiding
            self._pos_x = self._root.winfo_x()
            self._pos_y = self._root.winfo_y()
            # Move off-screen instead of withdraw (keeps message pump active)
            self._root.geometry("+32000+32000")

    def _close(self):
        """Close (minimize to tiny) the overlay.

        Note: We don't use withdraw() because a hidden window doesn't pump
        Windows messages, which breaks dialogs in windowed mode. Instead,
        we switch to tiny mode so there's still a visible window.
        """
        # Switch to tiny mode instead of hiding completely
        # This keeps a visible window for Windows message pumping
        if self._mode != self.MODE_TINY:
            self._switch_to_tiny()
        if self.on_close:
            self.on_close()

    def run(self):
        """Run the tkinter main loop."""
        if self._root:
            self._root.mainloop()

    def get_position(self) -> tuple[int, int]:
        """Get current window position."""
        if self._root:
            return (self._root.winfo_x(), self._root.winfo_y())
        return (0, 0)

    def is_tiny(self) -> bool:
        """Check if in tiny mode."""
        return self._mode == self.MODE_TINY


# For testing
if __name__ == "__main__":
    import sys

    def on_settings():
        print("Settings clicked!")

    overlay = STTOverlay(on_settings=on_settings)
    overlay.show()

    # Demo: cycle through states
    def demo_cycle():
        overlay.set_state("recording")
        overlay._root.after(5000, lambda: overlay.set_state("transcribing"))
        overlay._root.after(7000, lambda: overlay.set_state("ready"))
        overlay._root.after(9000, demo_cycle)

    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        overlay._root.after(500, demo_cycle)

    if len(sys.argv) > 1 and sys.argv[1] == "--tiny":
        overlay._root.after(500, overlay._switch_to_tiny)

    overlay.run()
