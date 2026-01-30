"""Runtime daemon service for CLD."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Optional

from cld.config import Config
from cld.engine_factory import build_engine
from cld.engines import STTEngine
from cld.errors import EngineError, HotkeyError, RecorderError
from cld.hotkey import HotkeyListener
from cld.keyboard import output_text
from cld.recorder import AudioRecorder, RecorderConfig
from cld.sounds import play_sound
from cld.window import get_active_window, WindowInfo
from cld.model_manager import ModelManager

import tkinter as tk

# Optional UI imports
try:
    from cld.ui.overlay import STTOverlay
    _OVERLAY_AVAILABLE = True
except ImportError:
    _OVERLAY_AVAILABLE = False

try:
    from cld.ui.tray import TrayIcon, is_tray_available
    _TRAY_AVAILABLE = is_tray_available()
except ImportError:
    _TRAY_AVAILABLE = False

try:
    from cld.ui.settings_popup import SettingsPopup
    from cld.ui.settings_dialog import SettingsDialog
    _SETTINGS_AVAILABLE = True
except ImportError:
    _SETTINGS_AVAILABLE = False

try:
    from cld.ui.model_dialog import ModelSetupDialog
    _MODEL_DIALOG_AVAILABLE = True
except ImportError:
    _MODEL_DIALOG_AVAILABLE = False


class STTDaemon:
    """Main daemon that coordinates all STT components."""

    def __init__(
        self,
        config: Optional[Config] = None,
        enable_overlay: bool = False,
        enable_tray: bool = True,
    ):
        """Initialize the daemon.

        Args:
            config: Configuration, or load from file if None.
            enable_overlay: Whether to show the GUI overlay.
            enable_tray: Whether to show the system tray icon.
        """
        self.config = (config or Config.load()).validate()
        self._running = False
        self._recording = False
        self._enable_overlay = enable_overlay and _OVERLAY_AVAILABLE
        self._enable_tray = enable_tray and _TRAY_AVAILABLE

        # Components
        self._recorder: Optional[AudioRecorder] = None
        self._engine: Optional[STTEngine] = None
        self._hotkey: Optional[HotkeyListener] = None
        self._overlay: Optional[STTOverlay] = None
        self._tray: Optional[TrayIcon] = None
        self._settings_popup: Optional[SettingsPopup] = None
        self._settings_dialog: Optional[SettingsDialog] = None

        # Recording state
        self._record_start_time: float = 0
        self._original_window: Optional[WindowInfo] = None

        # Threading - use RLock to avoid deadlocks in nested callbacks
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._is_transcribing: bool = False
        self._logger = logging.getLogger(__name__)

        # Queue for callbacks that must run in main thread (e.g., tkinter dialogs)
        self._main_thread_queue: queue.Queue[Callable[[], None]] = queue.Queue()

    def _init_components(self) -> bool:
        """Initialize all components.

        Returns:
            True if all components initialized successfully.
        """
        try:
            self._recorder = AudioRecorder(
                RecorderConfig(
                    sample_rate=self.config.sample_rate,
                    max_recording_seconds=self.config.max_recording_seconds,
                )
            )
            if not self._recorder.is_available():
                # Check for sounddevice import error
                from cld.recorder import get_sounddevice_import_error
                import_err = get_sounddevice_import_error()
                if import_err:
                    raise RecorderError(f"sounddevice import failed: {import_err}")
                raise RecorderError("No audio input device available")

            self._engine = build_engine(self.config)
            if not self._engine.is_available():
                raise EngineError(
                    "STT engine not available. Run setup to install dependencies."
                )

            self._hotkey = HotkeyListener(
                hotkey=self.config.hotkey,
                on_start=self._on_recording_start,
                on_stop=self._on_recording_stop,
                mode=self.config.mode,
            )
        except (RecorderError, EngineError, HotkeyError) as exc:
            self._logger.error("%s", exc)
            return False

        return True

    def _update_overlay(self, state: str) -> None:
        """Update the GUI overlay state."""
        if self._overlay:
            try:
                self._overlay.set_state(state)
            except Exception:
                self._logger.debug("Failed to update overlay state", exc_info=True)

    def get_audio_level(self) -> float:
        """Get current audio level (0.0-1.0) for visualization."""
        if self._recorder and self._recording:
            return self._recorder.get_current_level()
        return 0.0

    def get_audio_spectrum(self) -> list[float]:
        """Get current spectrum bands (16 floats, 0.0-1.0) for visualization."""
        if self._recorder and self._recording:
            return self._recorder.get_spectrum_bands()
        return [0.0] * 32

    def _update_tray(self, state: str) -> None:
        """Update the tray icon state."""
        if self._tray:
            try:
                # Map internal states to tray states
                tray_state_map = {
                    "ready": "ready",
                    "recording": "recording",
                    "transcribing": "processing",
                    "error": "ready",  # Fall back to ready for errors
                }
                self._tray.set_state(tray_state_map.get(state, "ready"))
            except Exception:
                self._logger.debug("Failed to update tray state", exc_info=True)

    def _update_state(self, state: str) -> None:
        """Update overlay and tray state."""
        self._update_overlay(state)
        self._update_tray(state)

    def _print_status(self, message: str = "", clear: bool = False) -> None:
        """Print status on a single line, overwriting previous."""
        output = "" if clear else message
        # Update UI state
        if "Recording" in message:
            self._update_state("recording")
        elif "Transcribing" in message:
            self._update_state("transcribing")
        elif "Ready" in message or "No speech" in message or "Too short" in message:
            self._update_state("ready")
        elif "failed" in message:
            self._update_state("error")
        elif clear:
            self._update_state("ready")

        # Print to console (with encoding fallback)
        try:
            print(f"\r{output:<60}\r", end="", flush=True)
        except UnicodeEncodeError:
            ascii_msg = output.encode("ascii", "replace").decode("ascii")
            print(f"\r{ascii_msg:<60}\r", end="", flush=True)

    def _on_recording_start(self):
        """Called when recording should start."""
        if self._is_transcribing:
            if self.config.sound_effects:
                play_sound("warning")
            return

        with self._lock:
            if self._recording:
                return

            self._recording = True
            self._record_start_time = time.time()

            # Capture the active window
            self._original_window = get_active_window()

            # Start recording
            if self._recorder and self._recorder.start():
                self._print_status("● Recording...")
                if self.config.sound_effects:
                    play_sound("start")
            else:
                self._logger.error("Audio recorder failed to start")
                self._recording = False
                if self.config.sound_effects:
                    play_sound("error")

    def _on_recording_stop(self):
        """Called when recording should stop."""
        audio = None
        window_info = None
        with self._lock:
            if not self._recording:
                return

            self._recording = False

            # Stop recording
            if self._recorder:
                audio = self._recorder.stop()
            window_info = self._original_window

            if self.config.sound_effects:
                play_sound("stop")

        # Check if we have audio to transcribe
        # Minimum 200ms recording to filter accidental taps (but allow short words)
        min_samples = int(0.2 * self.config.sample_rate)  # 200ms at 16kHz = 3200 samples

        if audio is not None and len(audio) >= min_samples:
            if self._is_transcribing:
                if self.config.sound_effects:
                    play_sound("warning")
                return

            self._is_transcribing = True
            self._print_status("◐ Transcribing...")
            threading.Thread(
                target=self._do_transcription,
                args=(audio, window_info),
                daemon=True,
            ).start()
        elif audio is not None and len(audio) > 0:
            # Too short - likely accidental tap
            self._logger.debug("Recording too short (%d samples, need %d)", len(audio), min_samples)
            self._print_status("○ Too short")
            if self.config.sound_effects:
                play_sound("warning")
        else:
            if self.config.sound_effects:
                play_sound("warning")
            self._print_status(clear=True)

    def _do_transcription(self, audio, window_info: Optional[WindowInfo]) -> None:
        """Perform transcription in background thread."""
        try:
            if not self._engine:
                return

            text = self._engine.transcribe(audio, self.config.sample_rate)
            text = text.strip()
            self._logger.debug("Raw transcription result: %r", text)

            # Filter out whisper artifacts that aren't real transcription
            # These are special tokens that whisper outputs for non-speech audio
            whisper_artifacts = [
                "[BLANK_AUDIO]", "[MUSIC]", "[APPLAUSE]", "[LAUGHTER]",
                "(BLANK_AUDIO)", "(MUSIC)", "(APPLAUSE)", "(LAUGHTER)",
                "[inaudible]", "(inaudible)", "[silence]", "(silence)",
            ]
            if text in whisper_artifacts or text.startswith("[") and text.endswith("]"):
                text = ""  # Treat as no speech detected

            if text:
                self._logger.info("Outputting text: %r to window: %s", text, window_info)
                if not output_text(text, window_info, self.config):
                    self._logger.warning("Failed to output transcription")
                    self._print_status("✗ Output failed")
                    if self.config.sound_effects:
                        play_sound("error")
                else:
                    self._print_status("✓ Ready")
            else:
                self._print_status("○ No speech detected")
                if self.config.sound_effects:
                    play_sound("warning")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self._logger.exception("Transcription failed")
            self._print_status(clear=True)
        finally:
            self._is_transcribing = False

    def _check_max_recording_time(self):
        """Check if max recording time has been reached."""
        if not self._recording:
            return

        elapsed = time.time() - self._record_start_time
        max_seconds = self.config.max_recording_seconds

        if max_seconds > 30:
            # Warning at 30 seconds before max
            if elapsed >= max_seconds - 30 and elapsed < max_seconds - 29:
                if self.config.sound_effects:
                    play_sound("warning")

        # Auto-stop at max
        if elapsed >= max_seconds:
            self._on_recording_stop()

    def _on_settings_click(self):
        """Called when overlay gear button is clicked."""
        if not _SETTINGS_AVAILABLE or not self._overlay or not self._overlay.has_window():
            return

        # Toggle popup visibility
        if self._settings_popup and self._settings_popup.is_visible():
            self._settings_popup.hide()
        else:
            self._settings_popup = SettingsPopup(
                parent=self._overlay.get_root(),
                config=self.config,
                on_settings_click=self._on_full_settings_click,
                on_change=self._on_config_change,
            )
            self._settings_popup.show()

    def _show_settings_dialog(self):
        """Show the full settings dialog (singleton - only one instance)."""
        self._logger.info("_show_settings_dialog called")
        if not _SETTINGS_AVAILABLE:
            self._logger.warning("Settings not available")
            return

        # Check if dialog already visible (singleton pattern)
        if self._settings_dialog and self._settings_dialog.is_visible():
            # Bring existing dialog to front
            self._logger.info("Settings dialog already open, bringing to front")
            if self._settings_dialog._window:
                self._settings_dialog._window.lift()
                self._settings_dialog._window.focus_force()
            return

        parent = self._overlay.get_root() if self._overlay else None
        self._logger.info("Creating SettingsDialog with parent=%s", parent)
        try:
            self._settings_dialog = SettingsDialog(
                parent=parent,
                config=self.config,
                on_save=self._on_config_change,
                on_hotkey_suppress=self._suppress_hotkey,
                on_hotkey_restore=self._restore_hotkey,
            )
            self._settings_dialog.show()
            self._logger.info("SettingsDialog shown")
        except Exception as e:
            self._logger.error("Failed to show settings dialog: %s", e, exc_info=True)

    def _suppress_hotkey(self):
        """Temporarily stop the hotkey listener (for key scanning)."""
        if self._hotkey and self._hotkey.is_running():
            self._logger.info("Suppressing hotkey listener for key scanning")
            self._hotkey.stop()

    def _restore_hotkey(self):
        """Restore the hotkey listener after key scanning."""
        if self._hotkey and not self._hotkey.is_running():
            self._logger.info("Restoring hotkey listener")
            self._hotkey.start()

    def _on_full_settings_click(self):
        """Called when 'All Settings' is clicked in popup."""
        self._show_settings_dialog()

    def _on_tray_settings_click(self):
        """Called when 'Settings' is clicked in tray menu."""
        # Schedule on main thread since tkinter requires main thread
        self._logger.info("Tray Settings clicked, queueing settings dialog")
        self._main_thread_queue.put(self._show_settings_dialog)
        self._logger.info("Settings dialog queued, queue size: %d", self._main_thread_queue.qsize())

    def _on_config_change(self, new_config: Config):
        """Called when configuration changes."""
        self._logger.info("Configuration changed, reloading...")
        self.config = new_config

        # Update hotkey if needed
        if self._hotkey:
            # Restart hotkey listener with new settings
            self._hotkey.stop()
            self._hotkey = HotkeyListener(
                hotkey=self.config.hotkey,
                on_start=self._on_recording_start,
                on_stop=self._on_recording_stop,
                mode=self.config.mode,
            )
            if self.config.activation.enabled:
                self._hotkey.start()

    def _on_tray_show_overlay(self):
        """Show the overlay from tray menu."""
        def do_show():
            if self._overlay:
                self._overlay._running = True  # Resume animation
                self._overlay.reset_position()  # Reset to center on show
                self._overlay.unhide()
                if self._tray:
                    self._tray.set_overlay_visible(True)
        self._main_thread_queue.put(do_show)

    def _on_tray_hide_overlay(self):
        """Hide the overlay from tray menu."""
        def do_hide():
            if self._overlay:
                self._overlay.hide()
                if self._tray:
                    self._tray.set_overlay_visible(False)
        self._main_thread_queue.put(do_hide)

    def _on_tray_exit(self):
        """Exit the application from tray menu."""
        self._running = False

    def _on_tray_about_click(self):
        """Called when 'About CLD' is clicked in tray menu."""
        self._logger.info("Tray About clicked, queueing about dialog")
        self._main_thread_queue.put(self._show_about_dialog)

    def _set_dark_title_bar(self, window) -> None:
        """Set dark title bar on Windows 10/11."""
        try:
            import ctypes
            from ctypes import wintypes

            window.update()  # Ensure HWND exists

            # Get the correct HWND (use GetAncestor for top-level window)
            GA_ROOT = 2
            GetAncestor = ctypes.windll.user32.GetAncestor
            GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
            GetAncestor.restype = wintypes.HWND
            hwnd = GetAncestor(window.winfo_id(), GA_ROOT)

            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value)
            )
        except Exception:
            pass  # Silently fail on non-Windows or older Windows

    def _show_about_dialog(self):
        """Show the about dialog (must run in main thread)."""
        self._logger.info("_show_about_dialog called")
        try:
            import webbrowser
            from PIL import Image, ImageTk
            from cld.ui import get_app_icon_path

            parent = self._overlay.get_root() if self._overlay else None

            # Colors (dark theme)
            bg = "#1a1a1a"
            text = "#ffffff"
            text_dim = "#888888"
            accent = "#4a9eff"

            # Create dialog as Toplevel (uses existing Tk root)
            # Need a valid parent for Toplevel to avoid orphan Tk() window
            temp_root = None
            if parent:
                dialog = tk.Toplevel(parent)
            else:
                # No parent - create hidden temp root
                temp_root = tk.Tk()
                temp_root.withdraw()
                dialog = tk.Toplevel(temp_root)

            dialog.title("About CLD")
            dialog.configure(bg=bg)
            dialog.resizable(False, False)

            # Size and center
            width, height = 360, 300
            x = (dialog.winfo_screenwidth() - width) // 2
            y = (dialog.winfo_screenheight() - height) // 2
            dialog.geometry(f"{width}x{height}+{x}+{y}")

            # Toolwindow style (no minimize/maximize)
            dialog.attributes("-toolwindow", True)
            dialog.attributes("-topmost", True)

            # Set dark title bar on Windows 10/11
            self._set_dark_title_bar(dialog)

            # Set window icon
            icon_path = get_app_icon_path()
            icon_photo = None
            logo_photo = None
            if icon_path.exists():
                try:
                    icon_img = Image.open(icon_path)
                    icon_photo = ImageTk.PhotoImage(icon_img)
                    dialog.iconphoto(True, icon_photo)

                    # Also prepare logo for display (64x64)
                    logo_img = icon_img.resize((64, 64), Image.Resampling.LANCZOS)
                    logo_photo = ImageTk.PhotoImage(logo_img)
                except Exception as e:
                    self._logger.warning("Failed to load icon: %s", e)

            # Content
            content = tk.Frame(dialog, bg=bg)
            content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

            # Display logo if available
            if logo_photo:
                logo_label = tk.Label(content, image=logo_photo, bg=bg)
                logo_label.image = logo_photo  # Keep reference
                logo_label.pack(pady=(0, 12))

            # Title
            tk.Label(
                content,
                text="ClaudeCli-Dictate (CLD)",
                font=("Segoe UI Semibold", 14),
                fg=text,
                bg=bg,
            ).pack(pady=(0, 8))

            # Version
            from cld import __version__
            tk.Label(
                content,
                text=f"Version {__version__}",
                font=("Segoe UI", 10),
                fg=text_dim,
                bg=bg,
            ).pack()

            # Description
            tk.Label(
                content,
                text="Local multilingual speech-to-text\nPowered by Whisper",
                font=("Segoe UI", 10),
                fg=text_dim,
                bg=bg,
                justify=tk.CENTER,
            ).pack(pady=(8, 12))

            # Author
            tk.Label(
                content,
                text="Author: MarvinFS (2026)",
                font=("Segoe UI", 10),
                fg=text,
                bg=bg,
            ).pack()

            # GitHub link - clickable "View on GitHub" text
            def open_github(event=None):
                """Open GitHub URL in browser."""
                try:
                    webbrowser.open("https://github.com/MarvinFS/claudecli-dictate")
                except Exception as ex:
                    self._logger.error("Failed to open URL: %s", ex)

            link = tk.Label(
                content,
                text="View on GitHub",
                font=("Segoe UI", 10, "underline"),
                fg=accent,
                bg=bg,
                cursor="hand2",
            )
            link.pack(pady=(4, 0))
            link.bind("<Button-1>", open_github)
            link.bind("<Enter>", lambda e: link.config(fg="#6cb5ff"))  # Lighter on hover
            link.bind("<Leave>", lambda e: link.config(fg=accent))

            # Close handler that cleans up temp_root
            def close_dialog():
                dialog.destroy()
                if temp_root:
                    temp_root.destroy()

            # Close on Escape
            dialog.bind("<Escape>", lambda e: close_dialog())
            dialog.protocol("WM_DELETE_WINDOW", close_dialog)

            # Focus the dialog
            dialog.focus_force()

            self._logger.info("About dialog shown")
        except Exception as e:
            self._logger.error("Failed to show about dialog: %s", e, exc_info=True)

    def _on_overlay_close(self):
        """Called when overlay is closed (hidden) by user."""
        # Overlay is just hidden, not destroyed - keep the reference
        if self._tray:
            self._tray.set_overlay_visible(False)

    def _show_model_setup_dialog(self, model_manager: ModelManager) -> bool:
        """Show model setup dialog.

        Args:
            model_manager: ModelManager instance.

        Returns:
            True if model is ready, False if user cancelled.
        """
        if not _MODEL_DIALOG_AVAILABLE:
            return False

        dialog = ModelSetupDialog(
            model_manager=model_manager,
            model_name=self.config.engine.whisper_model,
        )
        return dialog.show()

    def _print_manual_download_instructions(self, model_manager: ModelManager) -> None:
        """Print manual download instructions to console."""
        print("\n" + "=" * 60, flush=True)
        print("MODEL SETUP REQUIRED", flush=True)
        print("=" * 60, flush=True)
        print(f"\nModel '{self.config.engine.whisper_model}' is not installed.", flush=True)
        print("\nDownload manually from:", flush=True)
        for name, info in model_manager.get_all_models().items():
            url = model_manager.get_download_url(name)
            print(f"  {name} ({info['size']}): {url}", flush=True)
        print(f"\nModels are cached in: {model_manager._models_dir}", flush=True)
        print("=" * 60 + "\n", flush=True)

    def run(self):
        """Run the daemon main loop."""
        print(f"Hotkey: {self.config.hotkey}", flush=True)
        print(f"Engine: {self.config.engine.type}", flush=True)
        print(f"Mode: {self.config.mode}", flush=True)
        print(f"Overlay: {self._enable_overlay}", flush=True)
        print(f"Tray: {self._enable_tray}", flush=True)

        if not self._init_components():
            raise SystemExit(1)

        # Check model availability before loading
        model_manager = ModelManager()  # ModelManager.__init__ calls setup_model_cache()
        model_name = self.config.engine.whisper_model

        if not model_manager.is_model_available(model_name):
            print(f"Model '{model_name}' not found, showing setup dialog...", flush=True)

            # Try to show GUI dialog (even without --overlay flag)
            try:
                if self._show_model_setup_dialog(model_manager):
                    # Model downloaded successfully, reload config to get selected model
                    self.config = Config.load()
                    model_name = self.config.engine.whisper_model
                    # Reinitialize engine with new model
                    self._engine = build_engine(self.config)
                    print("Model setup complete.", flush=True)
                else:
                    # User chose to exit
                    print("Model setup cancelled by user.", flush=True)
                    raise SystemExit(1)
            except Exception as e:
                # GUI failed - show manual instructions in console
                self._logger.warning("Could not show model dialog: %s", e)
                self._print_manual_download_instructions(model_manager)
                raise SystemExit(1)

        # Load the model
        print("Loading STT model...", flush=True)
        if not self._engine.load_model():
            print("ERROR: Failed to load STT model", flush=True)
            raise SystemExit(1)

        print("Model loaded. Ready for voice input.", flush=True)

        # Prime the audio recorder for low-latency recording
        # This starts the pre-roll buffer to capture audio before hotkey press
        if self._recorder:
            if not self._recorder.prime():
                self._logger.warning("Failed to prime audio recorder; may miss first syllables")

        # Start hotkey listener
        if not self._hotkey.start():
            self._logger.error("Failed to start hotkey listener")
            raise SystemExit(1)

        self._running = True

        # Create tray icon if enabled
        if self._enable_tray:
            try:
                self._tray = TrayIcon(
                    on_show_overlay=self._on_tray_show_overlay,
                    on_hide_overlay=self._on_tray_hide_overlay,
                    on_settings=self._on_tray_settings_click,
                    on_exit=self._on_tray_exit,
                    on_about=self._on_tray_about_click,
                )
                self._tray.start()
            except Exception as e:
                self._logger.warning("Failed to create tray icon: %s", e)
                self._tray = None

        # Create overlay if enabled
        if self._enable_overlay:
            try:
                self._overlay = STTOverlay(
                    on_close=self._on_overlay_close,
                    on_settings=self._on_settings_click,
                    get_audio_level=self.get_audio_level,
                    get_audio_spectrum=self.get_audio_spectrum,
                    config=self.config,
                )
                self._overlay.show()
            except Exception as e:
                self._logger.warning("Failed to create overlay: %s", e)
                self._overlay = None

        # Handle shutdown signals
        def shutdown(signum, frame):
            self._logger.info("Shutting down...")
            self._running = False

        try:
            import signal

            signal.signal(signal.SIGINT, shutdown)
            signal.signal(signal.SIGTERM, shutdown)
        except Exception:
            self._logger.debug("Signal handlers unavailable", exc_info=True)

        # Main loop
        try:
            while self._running:
                self._check_max_recording_time()

                # Process main thread callbacks (e.g., settings dialogs from tray)
                while True:
                    try:
                        callback = self._main_thread_queue.get_nowait()
                        self._logger.info("Processing queued callback: %s", callback.__name__ if hasattr(callback, '__name__') else callback)
                        callback()
                        self._logger.info("Callback completed successfully")
                    except queue.Empty:
                        break
                    except Exception as e:
                        self._logger.error("Main thread callback failed: %s", e, exc_info=True)

                # Update overlay if active
                if self._overlay and self._overlay.has_window():
                    try:
                        self._overlay.process_queue()  # Process any pending state updates
                        root = self._overlay.get_root()
                        if root:
                            root.update()
                    except tk.TclError:
                        # Window was destroyed
                        self._overlay = None
                    except Exception:
                        self._logger.debug("Overlay update failed", exc_info=True)
                        self._overlay = None

                # Update settings dialog if active (has its own temp_root)
                if self._settings_dialog and self._settings_dialog.is_visible():
                    try:
                        if self._settings_dialog._temp_root:
                            self._settings_dialog._temp_root.update()
                        elif self._settings_dialog._window:
                            self._settings_dialog._window.update()
                    except tk.TclError:
                        self._settings_dialog = None
                    except Exception:
                        self._logger.debug("Settings dialog update failed", exc_info=True)

                time.sleep(0.016 if (self._overlay or self._settings_dialog) else 0.1)
        finally:
            self.stop()

    def stop(self):
        """Stop the daemon."""
        self._running = False
        self._stop_event.set()

        if self._recorder:
            if self._recording:
                self._recorder.stop()
            self._recorder.shutdown()  # Fully stop the primed audio stream

        if self._hotkey:
            self._hotkey.stop()

        if self._tray:
            self._tray.stop()

        self._logger.info("CLD daemon stopped.")
