"""Model setup dialog for CLD - download and configure Whisper models."""

import ctypes
import logging
import platform
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from cld.model_manager import ModelManager, WHISPER_MODELS

logger = logging.getLogger(__name__)


def set_dark_title_bar(window) -> None:
    """Set dark title bar on Windows 10/11."""
    if platform.system() != "Windows":
        return
    try:
        # Ensure window is realized
        window.update_idletasks()
        window.update()

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # For older Windows 10 builds
        value = ctypes.c_int(1)

        # Get HWND - try multiple methods
        hwnd = None

        # Method 1: GetAncestor with GA_ROOT
        GA_ROOT = 2
        hwnd = ctypes.windll.user32.GetAncestor(window.winfo_id(), GA_ROOT)

        # Method 2: GetParent (fallback)
        if not hwnd:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())

        if hwnd:
            # Try attribute 20 first (newer Windows), then 19 (older builds)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value)
            )
            if result != 0:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                    ctypes.byref(value), ctypes.sizeof(value)
                )

            # Force redraw of title bar
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


class ModelSetupDialog:
    """Dialog for model download and setup."""

    def __init__(
        self,
        model_manager: ModelManager,
        model_name: str,
        parent: Optional[tk.Tk] = None,
        on_success: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ):
        self._manager = model_manager
        self._model_name = model_name
        self._parent = parent
        self._on_success = on_success
        self._on_exit = on_exit

        self._window: Optional[tk.Tk] = None
        self._root: Optional[tk.Tk] = None
        self._download_thread: Optional[threading.Thread] = None
        self._result: Optional[bool] = None
        self._hw_info: Optional[dict] = None

        # Colors (dark theme)
        self._bg = "#1a1a1a"
        self._surface = "#242424"
        self._border = "#333333"
        self._text = "#ffffff"
        self._text_dim = "#888888"
        self._accent = "#4a9eff"
        self._green = "#66ff66"
        self._red = "#ff6666"
        self._yellow = "#ffcc00"

        # UI elements
        self._container: Optional[tk.Frame] = None
        self._hw_label: Optional[tk.Label] = None
        self._icon_photo = None  # Keep reference to prevent GC
        self._progress_frame: Optional[tk.Frame] = None
        self._progress_bar: Optional[ttk.Progressbar] = None
        self._progress_label: Optional[tk.Label] = None
        self._model_dropdown: Optional[tk.Menubutton] = None
        self._model_menu: Optional[tk.Menu] = None
        self._model_var: Optional[tk.StringVar] = None
        self._info_label: Optional[tk.Label] = None
        self._download_btn: Optional[tk.Button] = None
        self._manual_btn: Optional[tk.Button] = None
        self._exit_btn: Optional[tk.Button] = None
        self._url_label: Optional[tk.Label] = None
        self._is_downloading: bool = False

    def show(self) -> bool:
        """Show the dialog and block until resolved."""
        # Detect hardware first
        self._detect_hardware()

        # Create main window
        if self._parent is None:
            self._root = tk.Tk()
            self._window = self._root
        else:
            self._root = None
            self._window = tk.Toplevel(self._parent)
            self._window.transient(self._parent)

        self._window.title("CLD - Model Setup")
        self._window.configure(bg=self._bg)
        self._window.resizable(False, False)
        self._window.attributes("-toolwindow", True)

        # Size and center
        width, height = 540, 560
        screen_w = self._window.winfo_screenwidth()
        screen_h = self._window.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self._window.geometry(f"{width}x{height}+{x}+{y}")

        set_dark_title_bar(self._window)
        self._set_window_icon()
        self._configure_styles()
        self._build_ui()

        self._window.protocol("WM_DELETE_WINDOW", self._on_exit_click)
        self._window.bind("<Escape>", lambda e: self._on_exit_click())

        self._window.deiconify()
        self._window.lift()
        self._window.attributes("-topmost", True)
        self._window.update()
        self._window.attributes("-topmost", False)
        self._window.grab_set()
        self._window.focus_force()

        if self._root:
            self._root.mainloop()
        else:
            self._window.wait_window()

        return self._result is True

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

    def _detect_hardware(self) -> None:
        """Detect hardware and set recommended model."""
        try:
            from cld.ui.hardware import detect_hardware
            hw = detect_hardware()
            self._model_name = hw.recommended_model
            self._hw_info = {
                "has_cuda": hw.has_cuda,
                "gpu_name": hw.gpu_name,
                "vram_gb": hw.vram_gb,
                "ram_gb": hw.ram_gb,
                "cpu_cores": hw.cpu_cores,
                "recommended": hw.recommended_model,
                "summary": hw.summary,
            }
        except Exception as e:
            logger.warning("Hardware detection failed: %s", e)
            self._model_name = "medium-q5_0"
            import os
            self._hw_info = {
                "has_cuda": False,
                "gpu_name": None,
                "vram_gb": None,
                "ram_gb": None,
                "cpu_cores": os.cpu_count() or 1,
                "recommended": "medium-q5_0",
                "summary": f"CPU ({os.cpu_count() or 1} cores)",
            }

    def _configure_styles(self):
        """Configure ttk styles for dark theme."""
        style = ttk.Style()

        # Use clam theme which allows customization (default Windows theme ignores colors)
        style.theme_use("clam")

        style.configure(
            "Dark.Horizontal.TProgressbar",
            troughcolor=self._surface,
            background=self._accent,
            bordercolor=self._border,
            lightcolor=self._accent,
            darkcolor=self._accent,
            thickness=8,
        )

    def _build_ui(self):
        """Build the dialog UI."""
        self._container = tk.Frame(self._window, bg=self._bg)
        self._container.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)

        # Title
        tk.Label(
            self._container,
            text="Welcome to CLD",
            font=("Segoe UI Semibold", 16),
            fg=self._text,
            bg=self._bg,
        ).pack(anchor="w", pady=(0, 12))

        # Description
        tk.Label(
            self._container,
            text="An AI-powered Speech-to-Text application running entirely on your device.\n"
                 "Your voice data stays private - no cloud services.\n\n"
                 "A speech recognition model must be downloaded to get started.",
            font=("Segoe UI", 10),
            fg=self._text_dim,
            bg=self._bg,
            justify="left",
            wraplength=490,
        ).pack(anchor="w", pady=(0, 8))

        # Works in any app text
        tk.Label(
            self._container,
            text="Works in any focused app for text entry - type anywhere with your voice.",
            font=("Segoe UI", 10),
            fg=self._text_dim,
            bg=self._bg,
            justify="left",
            wraplength=490,
        ).pack(anchor="w", pady=(0, 16))

        # Hardware info section
        hw_frame = tk.Frame(self._container, bg=self._surface)
        hw_frame.pack(fill=tk.X, pady=(0, 16))

        hw_inner = tk.Frame(hw_frame, bg=self._surface)
        hw_inner.pack(fill=tk.X, padx=16, pady=12)

        tk.Label(
            hw_inner,
            text="Your Hardware",
            font=("Segoe UI Semibold", 10),
            fg=self._accent,
            bg=self._surface,
        ).pack(anchor="w", pady=(0, 6))

        # Build hardware info lines (CPU-only)
        hw_lines = []
        hw_lines.append(f"CPU: {self._hw_info['cpu_cores']} cores")
        if self._hw_info.get("ram_gb"):
            hw_lines.append(f"RAM: {self._hw_info['ram_gb']:.1f} GB")

        tk.Label(
            hw_inner,
            text="\n".join(hw_lines),
            font=("Segoe UI", 9),
            fg=self._text,
            bg=self._surface,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            hw_inner,
            text=f"Recommended model: {self._hw_info['recommended']}",
            font=("Segoe UI Semibold", 9),
            fg=self._green,
            bg=self._surface,
        ).pack(anchor="w")

        # Model selection section
        model_frame = tk.Frame(self._container, bg=self._surface)
        model_frame.pack(fill=tk.X, pady=(0, 16))

        model_inner = tk.Frame(model_frame, bg=self._surface)
        model_inner.pack(fill=tk.X, padx=16, pady=12)

        tk.Label(
            model_inner,
            text="Select Model",
            font=("Segoe UI Semibold", 10),
            fg=self._accent,
            bg=self._surface,
        ).pack(anchor="w", pady=(0, 8))

        combo_row = tk.Frame(model_inner, bg=self._surface)
        combo_row.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            combo_row,
            text="Model:",
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
        ).pack(side=tk.LEFT)

        # Custom dark dropdown using Menubutton (ttk.Combobox has white bg on Windows)
        self._model_var = tk.StringVar(value=self._model_name)

        dropdown_frame = tk.Frame(combo_row, bg=self._border, bd=0)
        dropdown_frame.pack(side=tk.RIGHT)

        self._model_dropdown = tk.Menubutton(
            dropdown_frame,
            textvariable=self._model_var,
            font=("Segoe UI", 10),
            fg=self._text,
            bg=self._surface,
            activebackground=self._accent,
            activeforeground=self._text,
            bd=0,
            padx=12,
            pady=6,
            width=32,
            anchor="w",
            indicatoron=True,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self._border,
            highlightcolor=self._accent,
        )
        self._model_dropdown.pack(padx=1, pady=1)

        self._model_menu = tk.Menu(
            self._model_dropdown,
            tearoff=0,
            bg=self._surface,
            fg=self._text,
            activebackground=self._accent,
            activeforeground=self._text,
            bd=0,
            relief="flat",
        )
        self._model_dropdown["menu"] = self._model_menu

        # Populate models
        model_names = list(WHISPER_MODELS.keys())
        for name in model_names:
            self._model_menu.add_command(
                label=name,
                command=lambda n=name: self._select_model(n),
            )

        if self._model_name not in model_names and model_names:
            self._model_name = model_names[0]
            self._model_var.set(self._model_name)

        self._info_label = tk.Label(
            model_inner,
            text="",
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._surface,
            wraplength=470,
            justify="left",
        )
        self._info_label.pack(anchor="w")
        self._update_model_info()

        # Progress section (hidden initially)
        self._progress_frame = tk.Frame(self._container, bg=self._bg)

        self._progress_bar = ttk.Progressbar(
            self._progress_frame,
            mode="indeterminate",
            style="Dark.Horizontal.TProgressbar",
            length=490,
        )
        self._progress_bar.pack(fill=tk.X, pady=(0, 4))

        self._progress_label = tk.Label(
            self._progress_frame,
            text="",
            font=("Consolas", 9),
            fg=self._text_dim,
            bg=self._bg,
        )
        self._progress_label.pack(anchor="w")

        # Buttons
        self._btn_frame = tk.Frame(self._container, bg=self._bg)
        self._btn_frame.pack(fill=tk.X, pady=(16, 0))

        self._exit_btn = tk.Button(
            self._btn_frame,
            text="Exit",
            font=("Segoe UI", 10),
            bg=self._surface,
            fg=self._text,
            activebackground=self._border,
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._on_exit_click,
        )
        self._exit_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self._manual_btn = tk.Button(
            self._btn_frame,
            text="Manual Download",
            font=("Segoe UI", 10),
            bg=self._surface,
            fg=self._text,
            activebackground=self._border,
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._on_manual_click,
        )
        self._manual_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self._download_btn = tk.Button(
            self._btn_frame,
            text="Download Now",
            font=("Segoe UI Semibold", 10),
            bg=self._accent,
            fg=self._text,
            activebackground="#3a8eef",
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._on_download_click,
        )
        self._download_btn.pack(side=tk.RIGHT)

    def _update_model_info(self):
        """Update model info display."""
        model_name = self._model_var.get() if self._model_var else self._model_name
        info = WHISPER_MODELS.get(model_name)

        if info:
            _compatible, warning = self._manager.check_hardware_compatibility(model_name)

            text = f"{info['description']}\n"
            text += f"Size: {info['size']} | RAM: {info['ram']} | CPU: {info['cores']}+ cores"

            if warning:
                text += f"\n{warning}"

            if self._info_label:
                self._info_label.config(text=text)

        # Update URL
        if self._url_label:
            url = self._manager.get_download_url(model_name)
            if url:
                self._url_label.config(text=url)

    def _select_model(self, model_name: str):
        """Select a model from dropdown."""
        self._model_var.set(model_name)
        self._model_name = model_name
        self._update_model_info()

    def _on_model_change(self, event=None):
        """Handle model selection change."""
        self._model_name = self._model_var.get()
        self._update_model_info()

    def _on_download_click(self):
        """Handle download button click."""
        if self._is_downloading:
            return

        self._model_name = self._model_var.get()
        self._is_downloading = True

        # Show progress
        self._progress_frame.pack(fill=tk.X, pady=(0, 16), before=self._btn_frame)
        self._progress_bar.config(mode="indeterminate")
        self._progress_bar.start(10)
        self._progress_label.config(text="Starting download...", fg=self._text_dim)

        self._download_btn.config(state=tk.DISABLED, text="Downloading...")
        self._manual_btn.config(state=tk.DISABLED)
        self._model_dropdown.config(state=tk.DISABLED)

        def download():
            def progress_callback(downloaded, total, speed):
                if total > 0:
                    pct = (downloaded / total) * 100
                    text = f"{downloaded / (1024*1024):.1f} / {total / (1024*1024):.1f} MB ({pct:.0f}%) - {speed:.1f} MB/s"
                else:
                    text = f"{downloaded / (1024*1024):.1f} MB downloaded"
                self._window.after(0, lambda: self._update_progress(pct if total > 0 else -1, text))

            success, error = self._manager.download_model(self._model_name, progress_callback)
            self._window.after(0, lambda: self._on_download_complete(success, error))

        self._download_thread = threading.Thread(target=download, daemon=True)
        self._download_thread.start()

    def _update_progress(self, percent: float, text: str):
        """Update progress display."""
        if percent >= 0:
            self._progress_bar.stop()
            self._progress_bar.config(mode="determinate", value=percent)
        self._progress_label.config(text=text)

    def _on_download_complete(self, success: bool, error: str):
        """Handle download completion."""
        self._is_downloading = False
        self._progress_bar.stop()

        if success:
            valid, verr = self._manager.validate_model(self._model_name)
            if valid:
                self._progress_bar.config(mode="determinate", value=100)
                self._progress_label.config(text="Download complete!", fg=self._green)
                # Save selected model to config
                try:
                    from cld.config import Config
                    config = Config.load()
                    config.engine.whisper_model = self._model_name
                    config.save()
                    logger.info("Saved selected model to config: %s", self._model_name)
                except Exception as e:
                    logger.warning("Failed to save model selection: %s", e)
                self._result = True
                self._window.after(500, self._close)
                return
            error = verr or "Validation failed"

        self._progress_label.config(text=f"Error: {error}", fg=self._red)
        self._download_btn.config(state=tk.NORMAL, text="Retry")
        self._manual_btn.config(state=tk.NORMAL)
        self._model_dropdown.config(state=tk.NORMAL)

    def _on_manual_click(self):
        """Open manual download window with step-by-step instructions."""
        # Create new window
        manual_win = tk.Toplevel(self._window)
        manual_win.title("Manual Download Instructions")
        manual_win.configure(bg=self._bg)
        manual_win.resizable(False, False)
        manual_win.attributes("-toolwindow", True)

        # Size and center relative to parent
        width, height = 560, 520
        parent_x = self._window.winfo_x()
        parent_y = self._window.winfo_y()
        parent_w = self._window.winfo_width()
        x = parent_x + (parent_w - width) // 2
        y = parent_y + 30
        manual_win.geometry(f"{width}x{height}+{x}+{y}")

        set_dark_title_bar(manual_win)

        # Make modal
        manual_win.transient(self._window)
        manual_win.grab_set()

        # Re-apply dark title bar after modal setup
        manual_win.after(50, lambda: set_dark_title_bar(manual_win))

        container = tk.Frame(manual_win, bg=self._bg)
        container.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)

        tk.Label(
            container,
            text="Manual Download Instructions",
            font=("Segoe UI Semibold", 14),
            fg=self._text,
            bg=self._bg,
        ).pack(anchor="w", pady=(0, 12))

        # Step 1: URL
        step1_frame = tk.Frame(container, bg=self._surface)
        step1_frame.pack(fill=tk.X, pady=(0, 12))
        step1_inner = tk.Frame(step1_frame, bg=self._surface)
        step1_inner.pack(fill=tk.X, padx=16, pady=12)

        tk.Label(
            step1_inner,
            text="Step 1: Download from HuggingFace",
            font=("Segoe UI Semibold", 10),
            fg=self._accent,
            bg=self._surface,
        ).pack(anchor="w", pady=(0, 6))

        url = self._manager.get_download_url(self._model_name) or ""
        url_label = tk.Label(
            step1_inner,
            text=url,
            font=("Consolas", 9),
            fg=self._accent,
            bg=self._surface,
            cursor="hand2",
        )
        url_label.pack(anchor="w", pady=(0, 6))

        def copy_url():
            manual_win.clipboard_clear()
            manual_win.clipboard_append(url)
            manual_win.update()
            url_label.config(text="Copied to clipboard!")
            manual_win.after(1500, lambda: url_label.config(text=url))

        url_label.bind("<Button-1>", lambda e: copy_url())

        tk.Button(
            step1_inner,
            text="Copy URL",
            font=("Segoe UI", 9),
            bg=self._border,
            fg=self._text,
            activebackground=self._accent,
            activeforeground=self._text,
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=copy_url,
        ).pack(anchor="w")

        # Step 2: Download files
        step2_frame = tk.Frame(container, bg=self._surface)
        step2_frame.pack(fill=tk.X, pady=(0, 12))
        step2_inner = tk.Frame(step2_frame, bg=self._surface)
        step2_inner.pack(fill=tk.X, padx=16, pady=12)

        tk.Label(
            step2_inner,
            text="Step 2: Download the model file",
            font=("Segoe UI Semibold", 10),
            fg=self._accent,
            bg=self._surface,
        ).pack(anchor="w", pady=(0, 6))

        model_info = WHISPER_MODELS.get(self._model_name, {})
        model_file = model_info.get("file", f"ggml-{self._model_name}.bin")
        tk.Label(
            step2_inner,
            text=f"Click the URL above to download the single .bin file:\n"
                 f"  - {model_file}",
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._surface,
            justify="left",
        ).pack(anchor="w")

        # Step 3: Copy to folder
        step3_frame = tk.Frame(container, bg=self._surface)
        step3_frame.pack(fill=tk.X, pady=(0, 12))
        step3_inner = tk.Frame(step3_frame, bg=self._surface)
        step3_inner.pack(fill=tk.X, padx=16, pady=12)

        tk.Label(
            step3_inner,
            text="Step 3: Copy file to models folder",
            font=("Segoe UI Semibold", 10),
            fg=self._accent,
            bg=self._surface,
        ).pack(anchor="w", pady=(0, 6))

        # GGML models are single .bin files stored flat in the models directory
        target_dir = self._manager._models_dir

        tk.Label(
            step3_inner,
            text="Copy the downloaded .bin file to:",
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._surface,
        ).pack(anchor="w", pady=(0, 4))

        folder_path = str(target_dir)
        folder_label = tk.Label(
            step3_inner,
            text=folder_path,
            font=("Consolas", 8),
            fg=self._yellow,
            bg=self._surface,
            wraplength=480,
            justify="left",
        )
        folder_label.pack(anchor="w", pady=(0, 6))

        def copy_path():
            manual_win.clipboard_clear()
            manual_win.clipboard_append(folder_path)
            manual_win.update()
            folder_label.config(text="Copied to clipboard!")
            manual_win.after(1500, lambda: folder_label.config(text=folder_path))

        folder_label.bind("<Button-1>", lambda e: copy_path())

        tk.Button(
            step3_inner,
            text="Copy Path",
            font=("Segoe UI", 9),
            bg=self._border,
            fg=self._text,
            activebackground=self._accent,
            activeforeground=self._text,
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=copy_path,
        ).pack(anchor="w")

        # Note
        tk.Label(
            container,
            text="Note: Create the folder if it doesn't exist. Keep the original filename.",
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._bg,
        ).pack(anchor="w", pady=(0, 12))

        # Close button
        tk.Button(
            container,
            text="Close",
            font=("Segoe UI", 10),
            bg=self._surface,
            fg=self._text,
            activebackground=self._border,
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=manual_win.destroy,
        ).pack(side=tk.RIGHT)

    def _on_exit_click(self):
        """Handle exit."""
        self._result = False
        self._close()
        if self._on_exit:
            self._on_exit()

    def _close(self):
        """Close dialog."""
        if self._window:
            try:
                self._window.grab_release()
                self._window.destroy()
            except Exception:
                pass
            self._window = None

        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass
            self._root = None

        if self._result is True and self._on_success:
            self._on_success()


def show_model_setup(model_manager: ModelManager, model_name: str, parent: Optional[tk.Tk] = None) -> bool:
    """Show the model setup dialog."""
    return ModelSetupDialog(model_manager, model_name, parent).show()


class ModelUpdateDialog:
    """Dialog to prompt user for model update."""

    def __init__(
        self,
        model_manager: ModelManager,
        model_name: str,
        local_version: str,
        remote_version: str,
    ):
        self._manager = model_manager
        self._model_name = model_name
        self._local_version = local_version
        self._remote_version = remote_version

        self._window: Optional[tk.Tk] = None
        self._root: Optional[tk.Tk] = None
        self._result: Optional[bool] = None
        self._download_thread: Optional[threading.Thread] = None

        # Colors (dark theme)
        self._bg = "#1a1a1a"
        self._surface = "#242424"
        self._border = "#333333"
        self._text = "#ffffff"
        self._text_dim = "#888888"
        self._accent = "#4a9eff"
        self._green = "#66ff66"
        self._red = "#ff6666"
        self._yellow = "#ffcc00"

        # UI elements
        self._progress_frame: Optional[tk.Frame] = None
        self._progress_bar: Optional[ttk.Progressbar] = None
        self._progress_label: Optional[tk.Label] = None
        self._update_btn: Optional[tk.Button] = None
        self._skip_btn: Optional[tk.Button] = None
        self._is_downloading: bool = False

    def show(self) -> bool:
        """Show the update prompt dialog.

        Returns:
            True if update was successful, False if skipped/cancelled.
        """
        self._root = tk.Tk()
        self._window = self._root
        self._window.title("Model Update Available")
        self._window.configure(bg=self._bg)
        self._window.resizable(False, False)
        self._window.attributes("-toolwindow", True)

        # Size and center
        width, height = 450, 320
        screen_w = self._window.winfo_screenwidth()
        screen_h = self._window.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self._window.geometry(f"{width}x{height}+{x}+{y}")

        set_dark_title_bar(self._window)
        self._configure_styles()
        self._build_ui()

        # Close = skip update
        self._window.protocol("WM_DELETE_WINDOW", self._on_skip)
        self._window.bind("<Escape>", lambda e: self._on_skip())

        self._window.deiconify()
        self._window.lift()
        self._window.attributes("-topmost", True)
        self._window.update()
        self._window.attributes("-topmost", False)
        self._window.grab_set()
        self._window.focus_force()

        self._root.mainloop()
        return self._result is True

    def _configure_styles(self):
        """Configure ttk styles."""
        style = ttk.Style()
        style.configure(
            "Dark.Horizontal.TProgressbar",
            troughcolor=self._surface,
            background=self._accent,
            bordercolor=self._border,
            thickness=8,
        )

    def _build_ui(self):
        """Build the dialog UI."""
        container = tk.Frame(self._window, bg=self._bg)
        container.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)

        # Title
        tk.Label(
            container,
            text="Model Update Available",
            font=("Segoe UI Semibold", 14),
            fg=self._text,
            bg=self._bg,
        ).pack(anchor="w", pady=(0, 16))

        # Info
        model_info = WHISPER_MODELS.get(self._model_name, {})
        tk.Label(
            container,
            text=f"A new version of the {self._model_name} model is available.",
            font=("Segoe UI", 10),
            fg=self._text_dim,
            bg=self._bg,
        ).pack(anchor="w", pady=(0, 8))

        # Version info
        version_frame = tk.Frame(container, bg=self._surface)
        version_frame.pack(fill=tk.X, pady=(0, 16))
        version_inner = tk.Frame(version_frame, bg=self._surface)
        version_inner.pack(fill=tk.X, padx=16, pady=12)

        tk.Label(
            version_inner,
            text=f"Current: {self._local_version}  →  New: {self._remote_version}",
            font=("Consolas", 10),
            fg=self._yellow,
            bg=self._surface,
        ).pack(anchor="w")

        tk.Label(
            version_inner,
            text=f"Size: ~{model_info.get('size', 'unknown')}",
            font=("Segoe UI", 9),
            fg=self._text_dim,
            bg=self._surface,
        ).pack(anchor="w", pady=(4, 0))

        # Progress (hidden initially)
        self._progress_frame = tk.Frame(container, bg=self._bg)

        self._progress_bar = ttk.Progressbar(
            self._progress_frame,
            mode="indeterminate",
            style="Dark.Horizontal.TProgressbar",
            length=400,
        )
        self._progress_bar.pack(fill=tk.X, pady=(0, 4))

        self._progress_label = tk.Label(
            self._progress_frame,
            text="",
            font=("Consolas", 9),
            fg=self._text_dim,
            bg=self._bg,
        )
        self._progress_label.pack(anchor="w")

        # Spacer
        tk.Frame(container, bg=self._bg).pack(fill=tk.BOTH, expand=True)

        # Buttons
        btn_frame = tk.Frame(container, bg=self._bg)
        btn_frame.pack(fill=tk.X, pady=(16, 0))

        self._skip_btn = tk.Button(
            btn_frame,
            text="Skip",
            font=("Segoe UI", 10),
            bg=self._surface,
            fg=self._text,
            activebackground=self._border,
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._on_skip,
        )
        self._skip_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self._update_btn = tk.Button(
            btn_frame,
            text="Update Now",
            font=("Segoe UI Semibold", 10),
            bg=self._accent,
            fg=self._text,
            activebackground="#3a8eef",
            activeforeground=self._text,
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=self._on_update,
        )
        self._update_btn.pack(side=tk.RIGHT)

    def _on_update(self):
        """Handle update button click."""
        if self._is_downloading:
            return

        self._is_downloading = True
        self._progress_frame.pack(fill=tk.X, pady=(0, 16))
        self._progress_bar.config(mode="indeterminate")
        self._progress_bar.start(10)
        self._progress_label.config(text="Downloading update...", fg=self._text_dim)

        self._update_btn.config(state=tk.DISABLED, text="Updating...")
        self._skip_btn.config(state=tk.DISABLED)

        def download():
            def progress_callback(downloaded, total, speed):
                if total > 0:
                    pct = (downloaded / total) * 100
                    text = f"{downloaded / (1024*1024):.1f} / {total / (1024*1024):.1f} MB ({pct:.0f}%)"
                else:
                    text = f"{downloaded / (1024*1024):.1f} MB downloaded"
                self._window.after(0, lambda: self._update_progress(pct if total > 0 else -1, text))

            success, error = self._manager.update_model(self._model_name, progress_callback)
            self._window.after(0, lambda: self._on_download_complete(success, error))

        self._download_thread = threading.Thread(target=download, daemon=True)
        self._download_thread.start()

    def _update_progress(self, percent: float, text: str):
        """Update progress display."""
        if percent >= 0:
            self._progress_bar.stop()
            self._progress_bar.config(mode="determinate", value=percent)
        self._progress_label.config(text=text)

    def _on_download_complete(self, success: bool, error: str):
        """Handle download completion."""
        self._is_downloading = False
        self._progress_bar.stop()

        if success:
            self._progress_bar.config(mode="determinate", value=100)
            self._progress_label.config(text="Update complete!", fg=self._green)
            self._result = True
            self._window.after(500, self._close)
        else:
            self._progress_label.config(text=f"Error: {error}", fg=self._red)
            self._update_btn.config(state=tk.NORMAL, text="Retry")
            self._skip_btn.config(state=tk.NORMAL)

    def _on_skip(self):
        """Handle skip button click."""
        if self._is_downloading:
            return
        self._result = False
        self._close()

    def _close(self):
        """Close dialog."""
        if self._window:
            try:
                self._window.grab_release()
                self._window.destroy()
            except Exception:
                pass
            self._window = None

        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass
            self._root = None


def show_model_update(
    model_manager: ModelManager,
    model_name: str,
    local_version: str,
    remote_version: str,
) -> bool:
    """Show the model update dialog.

    Returns:
        True if update was applied, False if skipped.
    """
    return ModelUpdateDialog(model_manager, model_name, local_version, remote_version).show()
