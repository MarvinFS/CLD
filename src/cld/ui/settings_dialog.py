"""Full settings dialog for CLD."""

import ctypes
import logging
import platform
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from cld.config import Config
from cld.ui.hardware import get_available_models, detect_hardware, enumerate_gpus, GPUDeviceInfo
from cld.ui.key_scanner import KeyScanner, KeyCapture, KEY_DISPLAY_NAMES

logger = logging.getLogger(__name__)


def set_dark_title_bar(window) -> None:
    """Set dark title bar on Windows 10/11."""
    if platform.system() != "Windows":
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

        if hwnd:
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value)
            )
            if result != 0:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                    ctypes.byref(value), ctypes.sizeof(value)
                )

            SWP_FRAMECHANGED = 0x0020
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            ctypes.windll.user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
            )
    except Exception:
        pass


class SettingsDialog:
    """Full settings dialog with all configuration options."""

    def __init__(
        self,
        parent: Optional[tk.Tk] = None,
        config: Optional[Config] = None,
        on_save: Optional[Callable[[Config], None]] = None,
        on_hotkey_suppress: Optional[Callable[[], None]] = None,
        on_hotkey_restore: Optional[Callable[[], None]] = None,
    ):
        """Initialize the settings dialog.

        Args:
            parent: Parent window.
            config: Current configuration (loads from file if None).
            on_save: Callback when settings are saved.
            on_hotkey_suppress: Called to suppress global hotkey during key scanning.
            on_hotkey_restore: Called to restore global hotkey after key scanning.
        """
        self._parent = parent
        self._config = config or Config.load()
        self._on_save = on_save
        self._on_hotkey_suppress = on_hotkey_suppress
        self._on_hotkey_restore = on_hotkey_restore
        self._window: Optional[tk.Toplevel] = None
        self._temp_root: Optional[tk.Tk] = None  # Temp root if no parent

        # Canvas/scrollbar references for resize handling
        self._canvas: Optional[tk.Canvas] = None
        self._scrollbar: Optional[ttk.Scrollbar] = None
        self._content: Optional[tk.Frame] = None
        self._content_window: Optional[int] = None
        self._icon_photo = None  # Keep reference to prevent GC

        # Colors (dark theme)
        self._bg = "#1a1a1a"
        self._surface = "#242424"
        self._border = "#333333"
        self._text = "#ffffff"
        self._text_dim = "#888888"
        self._accent = "#4a9eff"
        self._green = "#66ff66"

        # Widgets that need updating
        self._key_label: Optional[tk.Label] = None
        self._engine_var: Optional[tk.StringVar] = None
        self._model_combo: Optional[ttk.Combobox] = None

        # Hardware section state
        self._force_cpu_var: Optional[tk.BooleanVar] = None
        self._gpu_device_var: Optional[tk.StringVar] = None
        self._gpu_combo: Optional[ttk.Combobox] = None
        self._gpu_devices: list[GPUDeviceInfo] = []
        self._restart_label: Optional[tk.Label] = None
        self._original_force_cpu: bool = False

        # Engine section state
        self._translate_var: Optional[tk.BooleanVar] = None
        self._original_gpu_device: int = -1
        self._hw_info: Optional[object] = None  # Cached hardware info

    def show(self):
        """Show the settings dialog."""
        if self._window:
            self._window.lift()
            self._window.focus_force()
            return

        # Create window - need a valid parent for Toplevel
        if self._parent:
            self._window = tk.Toplevel(self._parent)
        else:
            # No parent - create hidden temp root to avoid orphan Tk() window
            self._temp_root = tk.Tk()
            self._temp_root.withdraw()
            self._window = tk.Toplevel(self._temp_root)

        self._window.title("CLD Settings")
        self._window.configure(bg=self._bg)
        self._window.resizable(True, True)
        self._window.minsize(380, 350)

        # Size and position - always center on screen
        width, height = 420, 420
        if self._parent:
            # Temporarily disable parent topmost
            try:
                self._parent.attributes("-topmost", False)
            except Exception:
                pass

        # Center on screen for consistent positioning
        screen_w = self._window.winfo_screenwidth()
        screen_h = self._window.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2

        self._window.geometry(f"{width}x{height}+{x}+{y}")

        # Apply dark title bar
        set_dark_title_bar(self._window)

        # Set window icon for taskbar thumbnail
        self._set_window_icon()

        # Configure ttk styles
        self._configure_styles()

        # Main container
        container = tk.Frame(self._window, bg=self._bg)
        container.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        # Scrollable content
        self._canvas = tk.Canvas(container, bg=self._bg, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(
            container, orient="vertical", command=self._canvas.yview, style="Dark.Vertical.TScrollbar"
        )
        self._content = tk.Frame(self._canvas, bg=self._bg)

        self._content.bind(
            "<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._content_window = self._canvas.create_window((0, 0), window=self._content, anchor="nw", width=width - 56)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Scrollbar initially hidden - will show dynamically if needed
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._scrollbar.pack_forget()

        # Bind resize event for dynamic scrollbar
        self._window.bind("<Configure>", self._on_window_resize)

        content = self._content

        # Build sections
        self._build_activation_section(content)
        self._build_engine_section(content)
        self._build_hardware_section(content)
        self._build_output_section(content)
        self._build_recording_section(content)

        # Button bar
        btn_frame = tk.Frame(self._window, bg=self._bg)
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 16))

        cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            font=("Segoe UI", 10),
            bg=self._surface,
            fg=self._text,
            activebackground=self._border,
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._cancel,
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        save_btn = tk.Button(
            btn_frame,
            text="Save",
            font=("Segoe UI Semibold", 10),
            bg=self._accent,
            fg=self._text,
            activebackground="#3a8eef",
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._save,
        )
        save_btn.pack(side=tk.RIGHT)

        # Bindings
        self._window.bind("<Escape>", lambda e: self._cancel())
        self._window.protocol("WM_DELETE_WINDOW", self._cancel)

        # Force initial rendering before modal grab
        self._window.update_idletasks()
        self._window.update()

        # Modal behavior - only use transient if parent is visible
        if self._parent:
            try:
                # Only set transient if parent window exists and is mapped
                if self._parent.winfo_exists() and self._parent.winfo_viewable():
                    self._window.transient(self._parent)
            except tk.TclError:
                pass
        self._window.grab_set()
        self._window.focus_force()

        # Apply dark title bar again after window is fully shown
        self._window.after(50, lambda: set_dark_title_bar(self._window))

        # Initial scrollbar visibility check
        self._window.after(100, self._on_window_resize)

    def _set_window_icon(self) -> None:
        """Set the window icon for taskbar thumbnail."""
        try:
            from PIL import Image, ImageTk
            from cld.ui import get_app_icon_path
            icon_path = get_app_icon_path()
            if icon_path.exists():
                icon_img = Image.open(icon_path)
                self._icon_photo = ImageTk.PhotoImage(icon_img)
                self._window.iconphoto(True, self._icon_photo)
        except Exception as e:
            logger.debug("Failed to set window icon: %s", e)

    def _configure_styles(self):
        """Configure ttk styles for dark theme."""
        style = ttk.Style()

        # Use clam theme for better customization (Windows native theme ignores colors)
        style.theme_use("clam")

        # Combobox - dark theme
        style.configure(
            "Dark.TCombobox",
            fieldbackground=self._surface,
            background=self._surface,
            foreground=self._text,
            arrowcolor=self._text,
            selectbackground=self._accent,
            selectforeground=self._text,
            padding=4,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", self._surface), ("disabled", self._border)],
            selectbackground=[("readonly", self._accent)],
            selectforeground=[("readonly", self._text)],
            background=[("active", self._border), ("pressed", self._accent)],
        )

        # Combobox dropdown listbox (requires option_add)
        self._window.option_add("*TCombobox*Listbox.background", self._surface)
        self._window.option_add("*TCombobox*Listbox.foreground", self._text)
        self._window.option_add("*TCombobox*Listbox.selectBackground", self._accent)
        self._window.option_add("*TCombobox*Listbox.selectForeground", self._text)

        # Scrollbar - dark theme with accent
        style.configure(
            "Dark.Vertical.TScrollbar",
            background=self._accent,
            troughcolor=self._bg,
            bordercolor=self._bg,
            arrowcolor=self._text,
            gripcount=0,
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#5aaeef"), ("pressed", "#3a8eef")],
        )

        # Scale - dark theme
        style.configure(
            "Dark.Horizontal.TScale",
            background=self._bg,
            troughcolor=self._surface,
            sliderlength=20,
        )

        # Checkbutton (ttk version for consistency)
        style.configure(
            "Dark.TCheckbutton",
            background=self._surface,
            foreground=self._text,
            indicatorbackground=self._surface,
            indicatorforeground=self._accent,
        )
        style.map(
            "Dark.TCheckbutton",
            background=[("active", self._surface)],
            indicatorbackground=[("selected", self._accent), ("active", self._border)],
        )

    def _build_section(self, parent: tk.Frame, title: str) -> tk.Frame:
        """Build a section frame with title."""
        frame = tk.Frame(parent, bg=self._bg)
        frame.pack(fill=tk.X, pady=(0, 16))

        # Section title
        title_lbl = tk.Label(
            frame,
            text=title,
            font=("Segoe UI Semibold", 11),
            fg=self._accent,
            bg=self._bg,
            anchor="w",
        )
        title_lbl.pack(fill=tk.X, pady=(0, 8))

        # Content frame
        content = tk.Frame(frame, bg=self._surface)
        content.pack(fill=tk.X)

        return content

    def _build_activation_section(self, parent: tk.Frame):
        """Build the activation settings section."""
        section = self._build_section(parent, "Activation")

        # Key row
        key_row = tk.Frame(section, bg=self._surface)
        key_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            key_row,
            text="Activation Key",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        change_btn = tk.Button(
            key_row,
            text="Change",
            font=("Segoe UI", 9),
            bg=self._border,
            fg=self._text,
            activebackground=self._accent,
            activeforeground=self._text,
            bd=0,
            padx=10,
            pady=2,
            cursor="hand2",
            command=self._change_key,
        )
        change_btn.pack(side=tk.RIGHT)

        key_display = KEY_DISPLAY_NAMES.get(
            self._config.activation.key, self._config.activation.key
        )
        self._key_label = tk.Label(
            key_row,
            text=f"{key_display} ({self._config.activation.scancode})",
            font=("Consolas", 10),
            fg=self._green,
            bg=self._surface,
        )
        self._key_label.pack(side=tk.RIGHT, padx=(0, 12))

        # Modifiers row
        mod_row = tk.Frame(section, bg=self._surface)
        mod_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            mod_row,
            text="Modifiers",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        # Modifier checkboxes container (aligned right)
        mod_checks = tk.Frame(mod_row, bg=self._surface)
        mod_checks.pack(side=tk.RIGHT)

        current_mods = self._config.activation.modifiers or []
        self._ctrl_var = tk.BooleanVar(value="ctrl" in current_mods)
        self._shift_var = tk.BooleanVar(value="shift" in current_mods)
        self._alt_var = tk.BooleanVar(value="alt" in current_mods)

        for text, var in [("Ctrl", self._ctrl_var), ("Shift", self._shift_var), ("Alt", self._alt_var)]:
            cb = tk.Checkbutton(
                mod_checks,
                text=text,
                variable=var,
                bg=self._surface,
                fg=self._text,
                activebackground=self._surface,
                activeforeground=self._text,
                selectcolor=self._accent,
                highlightthickness=0,
                bd=0,
                font=("Segoe UI", 9),
            )
            cb.pack(side=tk.LEFT, padx=(4, 0))

        # Mode row
        mode_row = tk.Frame(section, bg=self._surface)
        mode_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            mode_row,
            text="Mode",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        self._mode_var = tk.StringVar(value=self._config.activation.mode)
        mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self._mode_var,
            values=["toggle", "push_to_talk"],
            state="readonly",
            width=15,
            style="Dark.TCombobox",
        )
        mode_combo.pack(side=tk.RIGHT)
        # Explicitly set selection
        mode_values = ["toggle", "push_to_talk"]
        if self._config.activation.mode in mode_values:
            mode_combo.current(mode_values.index(self._config.activation.mode))

        # Enabled row
        enabled_row = tk.Frame(section, bg=self._surface)
        enabled_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            enabled_row,
            text="Hotkey Enabled",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        self._enabled_var = tk.BooleanVar(value=self._config.activation.enabled)
        enabled_cb = tk.Checkbutton(
            enabled_row,
            variable=self._enabled_var,
            bg=self._surface,
            fg=self._text,
            activebackground=self._surface,
            activeforeground=self._text,
            selectcolor=self._accent,
            highlightthickness=0,
            bd=0,
        )
        enabled_cb.pack(side=tk.RIGHT)

    def _build_engine_section(self, parent: tk.Frame):
        """Build the engine settings section."""
        section = self._build_section(parent, "STT Engine")

        # Engine row
        engine_row = tk.Frame(section, bg=self._surface)
        engine_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            engine_row,
            text="Engine",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        # Whisper engine (multilingual support)
        self._engine_var = tk.StringVar(value="whisper")
        engine_label = tk.Label(
            engine_row,
            text="Whisper (multilingual)",
            font=("Segoe UI", 10),
            fg=self._green,
            bg=self._surface,
        )
        engine_label.pack(side=tk.RIGHT)

        # Model row
        model_row = tk.Frame(section, bg=self._surface)
        model_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            model_row,
            text="Model",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        current_model = self._get_model_for_engine(self._config.engine.type)
        self._model_var = tk.StringVar(value=current_model)
        self._model_combo = ttk.Combobox(
            model_row,
            textvariable=self._model_var,
            state="readonly",
            width=25,
            style="Dark.TCombobox",
        )
        self._model_combo.pack(side=tk.RIGHT)
        self._update_model_options()

        # Translate to English checkbox
        translate_row = tk.Frame(section, bg=self._surface)
        translate_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            translate_row,
            text="Translate to English",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        self._translate_var = tk.BooleanVar(value=self._config.engine.translate_to_english)
        translate_cb = tk.Checkbutton(
            translate_row,
            variable=self._translate_var,
            bg=self._surface,
            fg=self._text,
            activebackground=self._surface,
            activeforeground=self._text,
            selectcolor=self._accent,
            highlightthickness=0,
            bd=0,
        )
        translate_cb.pack(side=tk.RIGHT)

        # Hardware info row (shows specs when model selected)
        hw_row = tk.Frame(section, bg=self._surface)
        hw_row.pack(fill=tk.X, padx=12, pady=(0, 8))

        # Detect hardware once and cache
        try:
            if self._hw_info is None:
                self._hw_info = detect_hardware()
            hw_text = f"CPU: {self._hw_info.cpu_cores} cores | RAM: {self._hw_info.ram_gb:.1f} GB | Recommended: {self._hw_info.recommended_model}"
        except Exception:
            hw_text = ""

        self._hw_info_label = tk.Label(
            hw_row,
            text=hw_text,
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._surface,
        )
        self._hw_info_label.pack(side=tk.LEFT)

    def _build_hardware_section(self, parent: tk.Frame):
        """Build the hardware/GPU settings section."""
        section = self._build_section(parent, "Hardware")

        # Use cached hardware info, detect only if not already cached
        if self._hw_info is None:
            self._hw_info = detect_hardware()
        hw_info = self._hw_info
        self._gpu_devices = enumerate_gpus()

        # Store originals for restart detection
        self._original_force_cpu = self._config.engine.force_cpu
        self._original_gpu_device = self._config.engine.gpu_device

        # Force CPU Only checkbox
        cpu_row = tk.Frame(section, bg=self._surface)
        cpu_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            cpu_row,
            text="Force CPU Only",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        self._force_cpu_var = tk.BooleanVar(value=self._config.engine.force_cpu)
        cpu_cb = tk.Checkbutton(
            cpu_row,
            variable=self._force_cpu_var,
            command=self._on_force_cpu_change,
            bg=self._surface,
            fg=self._text,
            activebackground=self._surface,
            activeforeground=self._text,
            selectcolor=self._accent,
            highlightthickness=0,
            bd=0,
        )
        cpu_cb.pack(side=tk.RIGHT)

        # GPU Device dropdown (if GPUs detected or GPU backend available)
        if self._gpu_devices or hw_info.has_gpu:
            gpu_row = tk.Frame(section, bg=self._surface)
            gpu_row.pack(fill=tk.X, padx=12, pady=8)

            tk.Label(
                gpu_row,
                text="GPU Device",
                font=("Segoe UI", 10),
                fg=self._text,
                bg=self._surface,
            ).pack(side=tk.LEFT)

            # Build dropdown values with shortened GPU names
            values = ["Auto-select"]
            for dev in self._gpu_devices:
                short_name = self._shorten_gpu_name(dev.name)
                values.append(short_name)

            self._gpu_device_var = tk.StringVar()
            # Set current value
            if self._config.engine.gpu_device == -1:
                self._gpu_device_var.set("Auto-select")
            elif self._gpu_devices and 0 <= self._config.engine.gpu_device < len(self._gpu_devices):
                dev = self._gpu_devices[self._config.engine.gpu_device]
                self._gpu_device_var.set(self._shorten_gpu_name(dev.name))
            else:
                self._gpu_device_var.set("Auto-select")

            self._gpu_combo = ttk.Combobox(
                gpu_row,
                textvariable=self._gpu_device_var,
                values=values,
                state="readonly",
                width=30,  # Wider to fit GPU names better
                style="Dark.TCombobox",
            )
            self._gpu_combo.pack(side=tk.RIGHT)
            self._gpu_combo.bind("<<ComboboxSelected>>", self._on_gpu_change)

            # Disable if force CPU checked
            if self._force_cpu_var.get():
                self._gpu_combo.config(state="disabled")

        # GPU backend info display - shows currently SELECTED GPU
        backend = hw_info.gpu_backend or "CPU"
        info_row = tk.Frame(section, bg=self._surface)
        info_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        self._backend_info_label = tk.Label(
            info_row,
            text=self._get_backend_info_text(backend),
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._surface,
        )
        self._backend_info_label.pack(side=tk.LEFT)

        # Restart warning (hidden initially)
        self._restart_label = tk.Label(
            section,
            text="Restart required for GPU changes",
            font=("Segoe UI", 9),
            fg="#ffcc00",
            bg=self._surface,
        )
        # Don't pack initially - will be shown when settings change

    def _shorten_gpu_name(self, name: str) -> str:
        """Create a shortened GPU name for dropdown display.

        Args:
            name: Full GPU name from WMI.

        Returns:
            Shortened name like "RTX 4090" or "Radeon RX 7900".
        """
        short = name
        prefixes_to_remove = [
            "NVIDIA GeForce ", "NVIDIA ", "GeForce ",
            "AMD Radeon ", "AMD ", "Radeon ",
            "Intel(R) ", "Intel ",
            "(TM)", "(R)", " Graphics",
        ]
        for prefix in prefixes_to_remove:
            short = short.replace(prefix, "")
        return short.strip()

    def _get_backend_info_text(self, backend: str) -> str:
        """Get the backend info text based on current selection.

        Args:
            backend: The GPU backend name (Vulkan, CUDA, or CPU).

        Returns:
            Info text showing backend and selected GPU.
        """
        if self._force_cpu_var and self._force_cpu_var.get():
            return "Backend: CPU (forced)"

        gpu_idx = self._get_selected_gpu_index()
        if gpu_idx == -1:
            # Auto-select - show first discrete GPU if available
            if self._gpu_devices:
                gpu_name = self._gpu_devices[0].name
                return f"Backend: {backend} | {gpu_name} (auto)"
            return f"Backend: {backend}"
        elif 0 <= gpu_idx < len(self._gpu_devices):
            gpu_name = self._gpu_devices[gpu_idx].name
            return f"Backend: {backend} | {gpu_name}"
        return f"Backend: {backend}"

    def _on_force_cpu_change(self):
        """Handle Force CPU checkbox change."""
        if self._gpu_combo:
            state = "disabled" if self._force_cpu_var.get() else "readonly"
            self._gpu_combo.config(state=state)
        self._update_backend_info()
        self._check_restart_needed()

    def _on_gpu_change(self, event=None):
        """Handle GPU device dropdown change."""
        self._update_backend_info()
        self._check_restart_needed()

    def _update_backend_info(self):
        """Update the backend info label based on current selection."""
        if not hasattr(self, '_backend_info_label') or not self._backend_info_label:
            return
        # Use cached hardware info - don't call detect_hardware() on every dropdown change
        backend = self._hw_info.gpu_backend if self._hw_info else "CPU"
        self._backend_info_label.config(text=self._get_backend_info_text(backend))

    def _check_restart_needed(self):
        """Check if GPU settings changed and show/hide restart warning."""
        new_force_cpu = self._force_cpu_var.get()
        new_gpu_device = self._get_selected_gpu_index()

        changed = (new_force_cpu != self._original_force_cpu or
                   new_gpu_device != self._original_gpu_device)

        if changed and self._restart_label:
            self._restart_label.pack(fill=tk.X, padx=12, pady=(0, 8))
        elif self._restart_label:
            self._restart_label.pack_forget()

    def _get_selected_gpu_index(self) -> int:
        """Get the selected GPU index from dropdown (-1 for auto)."""
        if not self._gpu_device_var:
            return -1
        val = self._gpu_device_var.get()
        if val == "Auto-select":
            return -1
        # Find device by matching shortened display name, return its Vulkan index
        for dev in self._gpu_devices:
            if self._shorten_gpu_name(dev.name) == val:
                return dev.index  # Use actual Vulkan device index, not list position
        return -1

    def _build_output_section(self, parent: tk.Frame):
        """Build the output settings section."""
        section = self._build_section(parent, "Output")

        # Mode row
        mode_row = tk.Frame(section, bg=self._surface)
        mode_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            mode_row,
            text="Output Mode",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        self._output_mode_var = tk.StringVar(value=self._config.output.mode)
        mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self._output_mode_var,
            values=["auto", "injection", "clipboard"],
            state="readonly",
            width=15,
            style="Dark.TCombobox",
        )
        mode_combo.pack(side=tk.RIGHT)

        # Sound effects row
        sound_row = tk.Frame(section, bg=self._surface)
        sound_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            sound_row,
            text="Sound Effects",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        self._sound_var = tk.BooleanVar(value=self._config.output.sound_effects)
        sound_cb = tk.Checkbutton(
            sound_row,
            variable=self._sound_var,
            bg=self._surface,
            fg=self._text,
            activebackground=self._surface,
            activeforeground=self._text,
            selectcolor=self._accent,
            highlightthickness=0,
            bd=0,
        )
        sound_cb.pack(side=tk.RIGHT)

    def _build_recording_section(self, parent: tk.Frame):
        """Build the recording settings section."""
        section = self._build_section(parent, "Recording")

        # Max duration row
        dur_row = tk.Frame(section, bg=self._surface)
        dur_row.pack(fill=tk.X, padx=12, pady=8)

        tk.Label(
            dur_row,
            text="Max Duration",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        self._duration_var = tk.IntVar(value=self._config.recording.max_seconds)

        dur_label = tk.Label(
            dur_row,
            text=f"{self._config.recording.max_seconds}s",
            font=("Consolas", 10),
            fg=self._green,
            bg=self._surface,
            width=5,
        )
        dur_label.pack(side=tk.RIGHT)

        def update_dur_label(val):
            dur_label.config(text=f"{int(float(val))}s")
            self._duration_var.set(int(float(val)))

        dur_scale = ttk.Scale(
            dur_row,
            from_=10,
            to=600,
            variable=self._duration_var,
            orient="horizontal",
            length=150,
            command=update_dur_label,
            style="Dark.Horizontal.TScale",
        )
        dur_scale.pack(side=tk.RIGHT, padx=(0, 8))

    def _get_model_for_engine(self, engine: str) -> str:
        """Get the configured model name (Whisper only)."""
        return self._config.engine.whisper_model

    def _on_engine_change(self, event=None):
        """Handle engine selection change (kept for compatibility)."""
        self._update_model_options()

    def _update_model_options(self):
        """Update model dropdown - Whisper only (multilingual)."""
        if not self._model_combo:
            return

        # Only Whisper models (multilingual support)
        models = get_available_models("whisper")
        values = [m[0] for m in models]

        self._model_combo["values"] = values

        current = self._config.engine.whisper_model
        if current in values:
            self._model_var.set(current)
            self._model_combo.current(values.index(current))
        elif values:
            # Default to medium for best multilingual support
            default = "medium" if "medium" in values else values[0]
            self._model_var.set(default)
            self._model_combo.current(values.index(default))

    def _on_window_resize(self, event=None):
        """Handle window resize - update canvas and scrollbar visibility."""
        if not self._window or not self._canvas or not self._content:
            return

        # Update canvas window width to match window size
        new_width = self._window.winfo_width() - 56  # Account for padding + scrollbar
        if new_width > 0:
            self._canvas.itemconfig(self._content_window, width=new_width)

        # Update scroll region
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

        # Show/hide scrollbar based on content height vs canvas height
        content_height = self._content.winfo_reqheight()
        canvas_height = self._canvas.winfo_height()

        if content_height > canvas_height:
            self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        else:
            self._scrollbar.pack_forget()

    def _change_key(self):
        """Open key scanner to change activation key."""

        def on_capture(capture: Optional[KeyCapture]):
            if capture and self._key_label:
                self._config.activation.key = capture.key
                self._config.activation.scancode = capture.scancode
                self._key_label.config(
                    text=f"{capture.display_name} ({capture.scancode})"
                )

        scanner = KeyScanner(
            parent=self._window,
            on_capture=on_capture,
            on_cancel=lambda: None,
            on_scanning_start=self._on_hotkey_suppress,
            on_scanning_end=self._on_hotkey_restore,
        )
        scanner.show()

    def _save(self):
        """Save settings and close."""
        # Update config from UI
        self._config.activation.mode = self._mode_var.get()
        self._config.activation.enabled = self._enabled_var.get()

        # Build modifiers list from checkboxes
        modifiers = []
        if self._ctrl_var.get():
            modifiers.append("ctrl")
        if self._shift_var.get():
            modifiers.append("shift")
        if self._alt_var.get():
            modifiers.append("alt")
        self._config.activation.modifiers = modifiers

        # Always use Whisper (multilingual)
        self._config.engine.type = "whisper"
        self._config.engine.whisper_model = self._model_var.get()
        self._config.engine.translate_to_english = self._translate_var.get() if self._translate_var else False

        # Save GPU settings
        if self._force_cpu_var and self._force_cpu_var.get():
            self._config.engine.force_cpu = True
        else:
            self._config.engine.force_cpu = False
        self._config.engine.gpu_device = self._get_selected_gpu_index()

        self._config.output.mode = self._output_mode_var.get()
        self._config.output.sound_effects = self._sound_var.get()

        self._config.recording.max_seconds = self._duration_var.get()

        # Validate and save
        self._config.validate()
        self._config.save()

        # Notify and close
        if self._on_save:
            self._on_save(self._config)

        self._close()

    def _cancel(self):
        """Cancel and close without saving."""
        self._close()

    def _close(self):
        """Close the dialog."""
        if self._window:
            # Restore parent topmost
            if self._parent:
                try:
                    self._parent.attributes("-topmost", True)
                except Exception:
                    pass

            try:
                self._window.grab_release()
                self._window.destroy()
            except Exception:
                pass
            self._window = None

            # Destroy temp root if we created one
            if self._temp_root:
                try:
                    self._temp_root.destroy()
                except Exception:
                    pass
                self._temp_root = None

    def is_visible(self) -> bool:
        """Check if dialog is visible."""
        return self._window is not None


def show_settings(
    parent: Optional[tk.Tk] = None,
    config: Optional[Config] = None,
    on_save: Optional[Callable[[Config], None]] = None,
):
    """Convenience function to show settings dialog.

    Args:
        parent: Parent window.
        config: Current configuration.
        on_save: Callback when settings are saved.
    """
    dialog = SettingsDialog(parent=parent, config=config, on_save=on_save)
    dialog.show()
