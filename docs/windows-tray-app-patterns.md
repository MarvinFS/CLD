# Windows Tray App Patterns: tkinter + pystray

This document captures lessons learned from building Windows system tray applications using tkinter and pystray. These patterns solve common issues encountered during development.

## Threading Architecture

The threading model is critical for responsive Windows tray applications. Getting this wrong causes various issues including unresponsive buttons, frozen UIs, and crashes.

### Required Thread Layout

```
Main Thread:    tkinter mainloop (REQUIRED on Windows for mouse events)
Background:     pystray tray icon (via start_detached())
Background:     Data refresh loop
Background:     Network requests / API calls
```

### The Problem

Windows requires tkinter to run in the main thread for mouse events to work properly. If tkinter runs in a background thread, button clicks may not register, dialogs may not appear, and the UI becomes unresponsive.

### The Solution

Create a hidden `tk.Tk()` root window in the main thread and run `mainloop()` there. Use pystray's `start_detached()` method to run the tray icon in a background thread.

```python
def main():
    # Create hidden tkinter root in main thread
    root = tk.Tk()
    root.withdraw()  # Hide the root window

    # Initialize your popup window (uses Toplevel)
    popup = ClaudeBarWindow(...)

    # Create tray icon
    icon = pystray.Icon("MyApp", image, "Tooltip", menu)

    # Start tray in background thread
    icon.run_detached()

    # Run tkinter mainloop in main thread
    root.mainloop()
```

### Why This Works

1. tkinter runs in main thread, so all mouse/keyboard events work
2. pystray runs detached, so it doesn't block
3. Popup windows use `Toplevel()` parented to the hidden root
4. Data refresh and network calls run in background threads

## Settings Dialog Z-Order

Modal dialogs opened from a topmost window often appear behind the parent, making them inaccessible.

### The Problem

When your main popup has `-topmost` set to True and you open a settings dialog, the dialog may appear behind the parent window even though it should be modal.

### The Solution

Temporarily disable the parent's topmost attribute, configure the dialog properly, then restore topmost on close.

```python
class SettingsDialog:
    def __init__(self, parent, config, on_save, on_close=None):
        self.parent = parent
        self.on_close = on_close

        # Temporarily lower parent's topmost
        try:
            parent.attributes('-topmost', False)
        except tk.TclError:
            pass

        # Create dialog
        self.dialog = tk.Toplevel(parent)
        self.dialog.transient(parent)     # Associate with parent
        self.dialog.grab_set()            # Make modal
        self.dialog.attributes('-topmost', True)  # Dialog on top

        # Force focus
        self.dialog.lift()
        self.dialog.focus_force()
        self.dialog.focus_set()

        # Handle close
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_dialog_close)

    def _restore_parent(self):
        """Restore parent window's topmost state."""
        try:
            self.parent.attributes('-topmost', True)
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

    def _on_dialog_close(self):
        self._restore_parent()
        self.dialog.destroy()
```

### Key Methods

The combination of `transient()`, `grab_set()`, `lift()`, and `focus_force()` ensures proper modal behavior on Windows.

## Progress Bar Animation

Progress bars that animate via `after()` may not complete their animation if the mainloop isn't actively processing events.

### The Problem

When updating a progress bar from a background thread, calling `set_value(percent)` with animation enabled may result in incomplete or missing animations because the mainloop isn't processing the `after()` callbacks quickly enough.

### The Solution

Use `animate=False` for immediate updates from background threads.

```python
class ModernProgressBar(tk.Canvas):
    def set_value(self, percent, animate=True):
        self._target_value = max(0, min(100, percent))
        if animate:
            if self._animation_id is None:
                self._animate_step()
        else:
            # Immediate update for background thread calls
            self._value = self._target_value
            self._redraw()
```

When updating from a background thread or when data refresh completes, always use `animate=False` to ensure the progress bar reflects the actual value immediately.

## Config Storage Location

Storing config files in the home directory causes sync issues with OneDrive.

### The Problem

Files in `%USERPROFILE%` or `~` may be synced to OneDrive, causing conflicts, sync errors, or data loss when the app runs on multiple machines.

### The Solution

Use `LOCALAPPDATA` for app-specific configuration and data files.

```python
import os
from pathlib import Path

def get_config_dir() -> Path:
    """Get app config directory in LOCALAPPDATA."""
    local_app_data = os.environ.get('LOCALAPPDATA')
    if local_app_data:
        config_dir = Path(local_app_data) / "MyAppName"
    else:
        # Fallback for non-Windows
        config_dir = Path.home() / ".myappname"

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_config_path() -> Path:
    return get_config_dir() / "config.json"
```

This results in paths like `C:\Users\<user>\AppData\Local\MyAppName\config.json`, which is excluded from OneDrive sync by default.

### Create on First Run

Create the config directory and populate with defaults on first run to avoid missing file errors.

## Thread-Safe UI Updates

Updating tkinter widgets from background threads causes crashes or corrupted state.

### The Problem

tkinter is not thread-safe. Calling widget methods like `config()`, `pack()`, or `destroy()` from a background thread can crash the application or leave widgets in an inconsistent state.

### The Solution

Queue pending updates and apply them from the main tkinter thread using `after()` polling.

```python
class ClaudeBarWindow:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending_snapshot = None  # Thread-safe pending update

    def update(self, snapshot):
        """Queue snapshot update (thread-safe, can be called from any thread)."""
        with self._lock:
            self._pending_snapshot = snapshot

    def _apply_snapshot_update(self):
        """Apply pending snapshot update (must be called from main thread)."""
        snapshot = None
        with self._lock:
            if self._pending_snapshot:
                snapshot = self._pending_snapshot
                self._snapshot = snapshot
                self._pending_snapshot = None

        if not snapshot:
            return

        # Safe to update widgets here - we're in main thread
        self._update_ui_from_snapshot(snapshot)

    def _start_update_loop(self):
        """Process tkinter events and check for pending updates."""
        if not self._window:
            return

        try:
            if not self._window.winfo_exists():
                return

            # Apply any pending data updates
            self._apply_snapshot_update()

            # Continue loop
            self._window.after(50, self._start_update_loop)
        except tk.TclError:
            pass  # Window was destroyed
```

### Key Points

1. Use a lock to protect shared state
2. Store pending updates in a variable
3. Poll for updates using `after()` from the main thread
4. Only modify widgets from the polling callback

### Use RLock to Avoid Deadlocks

When the update loop acquires a lock and then calls a method that also tries to acquire the same lock, a deadlock occurs because Python's `threading.Lock()` is not reentrant.

**The Problem:**

```python
def _start_update_loop(self):
    with self._lock:  # Lock acquired here
        if self._status_needs_update:
            self._update_status_display()  # Calls method below

def _update_status_display(self):
    with self._lock:  # DEADLOCK - same thread waiting for itself!
        oauth_error = self._oauth_error
```

**The Solution:**

Use `threading.RLock()` (reentrant lock) instead of `threading.Lock()`. An RLock allows the same thread to acquire it multiple times without blocking.

```python
class ClaudeBarWindow:
    def __init__(self):
        self._lock = threading.RLock()  # NOT Lock()!
        self._pending_snapshot = None
```

This is a subtle but critical bug that causes the entire UI to freeze with no error message. Always use RLock when callbacks or nested method calls might need the same lock.

## OAuth API Pattern for CLI Credentials

Reading OAuth tokens from CLI credential files allows sharing authentication with existing tools.

### The Pattern

1. Read tokens from CLI credential files at well-known paths
2. Check token expiration before use
3. Return valid data objects even on error (with error field set)

```python
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from datetime import datetime, timedelta
import json

@dataclass
class OAuthUsageData:
    session_percent: float = 0.0
    weekly_percent: float = 0.0
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None

def load_credentials() -> Optional[dict]:
    """Load OAuth token from CLI credentials."""
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if not creds_path.exists():
        return None

    try:
        with open(creds_path) as f:
            data = json.load(f)

        # Check expiration
        expires_at = data.get("expiresAt")
        if expires_at:
            exp_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(exp_time.tzinfo) >= exp_time:
                return None  # Token expired

        return data
    except (json.JSONDecodeError, KeyError):
        return None

def fetch_oauth_usage() -> OAuthUsageData:
    """Fetch usage from OAuth API."""
    creds = load_credentials()
    if not creds:
        return OAuthUsageData(error="No valid credentials")

    token = creds.get("accessToken")
    if not token:
        return OAuthUsageData(error="No access token")

    try:
        # Make API call
        response = requests.get(
            "https://api.example.com/usage",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        data = response.json()

        return OAuthUsageData(
            session_percent=data.get("session_percent", 0),
            weekly_percent=data.get("weekly_percent", 0)
        )
    except Exception as e:
        return OAuthUsageData(error=str(e))
```

### Key Points

1. Always return a valid object, even on error
2. Use `is_valid` property to check success
3. Check token expiration before making API calls
4. Handle missing files gracefully
5. Never store credentials yourself - read from the CLI's file

## External Links from Topmost Windows

Opening URLs from a topmost window can cause focus issues where the browser window appears but is immediately obscured.

### The Problem

When using `webbrowser.open()` from a topmost tkinter window, the browser may open but immediately lose focus back to your app, requiring the user to manually switch windows.

### The Solution

Use subprocess to call the Windows `start` command directly, and set a flag to prevent FocusOut handlers from interfering.

```python
import subprocess

class MyWindow:
    def __init__(self):
        self._opening_link = False

    def _on_github_click(self, event):
        """Handle link click."""
        # Set flag to prevent FocusOut from hiding window
        self._opening_link = True

        # Use subprocess for reliable URL opening
        try:
            subprocess.Popen(
                ['cmd', '/c', 'start', '', URL],
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            pass

        # Reset flag after a short delay
        if self._window:
            self._window.after(500, self._reset_link_flag)

    def _reset_link_flag(self):
        self._opening_link = False

    def _on_focus_out(self, event):
        # Don't hide if we're opening a link
        if self._opening_link:
            return
        # ... normal focus out handling
```

This approach avoids the focus fighting that can occur with `webbrowser.open()` on Windows.

## Global Hotkeys with pynput

pynput requires a Windows message pump to receive keyboard events. This creates issues when running Python as a detached background process.

### The Problem

When spawning a Python daemon with `subprocess.DETACHED_PROCESS`, the process has no console and no message pump. pynput's keyboard listener relies on Windows hooks that require message processing, so hotkeys simply don't work in a detached process.

### The Solution

If you need global hotkeys with pynput, don't use `DETACHED_PROCESS`. Either keep a visible console window, or use a hidden tkinter window that provides a message pump.

```python
# In daemon spawning code
if os.name == "nt":
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if not enable_overlay:
        # Only detach if we don't need hotkeys or have a GUI providing message pump
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
```

When a tkinter overlay is enabled, it provides the message pump via its mainloop, so pynput works correctly. Without tkinter, keep the console visible.

### Alt_Gr Key Handling

Windows treats Alt_Gr differently from regular Alt keys. When normalizing key names for hotkey matching, handle `alt_gr` explicitly.

```python
def _normalize_key(self, key):
    """Normalize key to a consistent form."""
    # Keep alt_gr as-is so it matches <alt_gr> hotkey config
    if hasattr(keyboard.Key, "alt_gr") and key == keyboard.Key.alt_gr:
        return keyboard.Key.alt_gr

    # Normalize other alt/ctrl/shift variants
    if hasattr(key, 'name'):
        name = key.name
        if name in ('alt_l', 'alt_r'):
            return keyboard.Key.alt
        # ... etc
```

Without this, `<alt_gr>` in config would never match because `alt_r` was being normalized to `alt`.

### Windows Virtual Key Codes with Modifiers

When Ctrl or Alt is held, pynput receives Windows Virtual Key (VK) codes instead of characters. This breaks hotkey matching.

**The Problem:**

Hotkey is configured as `Ctrl+=`, which parses to `{<Key.ctrl>, '='}`. But when user presses Ctrl+=:
- pynput receives VK code `<187>` instead of character `'='`
- Pressed keys become `{<Key.ctrl>, <187>}`
- Hotkey matching fails because `{<Key.ctrl>, '='}` != `{<Key.ctrl>, <187>}`

**The Solution:**

Map Windows VK codes to characters in the key normalization function:

```python
# Windows virtual key codes to character mapping
# When Ctrl/Alt is held, pynput returns VK codes instead of characters
_VK_TO_CHAR = {
    186: ";", 187: "=", 188: ",", 189: "-", 190: ".", 191: "/",
    192: "`", 219: "[", 220: "\\", 221: "]", 222: "'",
}

def _normalize_key(self, key) -> Optional[object]:
    """Normalize a key to a comparable form."""
    # Handle character keys
    if hasattr(key, "char") and key.char:
        if key.char == " ":
            return keyboard.Key.space
        return keyboard.KeyCode.from_char(key.char.lower())

    # Handle virtual key codes (sent when Ctrl/Alt is held)
    if hasattr(key, "vk") and key.vk:
        vk = key.vk
        # Map VK codes to characters
        if vk in self._VK_TO_CHAR:
            return keyboard.KeyCode.from_char(self._VK_TO_CHAR[vk])
        # Letters A-Z (VK 65-90)
        if 65 <= vk <= 90:
            return keyboard.KeyCode.from_char(chr(vk).lower())
        # Numbers 0-9 (VK 48-57)
        if 48 <= vk <= 57:
            return keyboard.KeyCode.from_char(chr(vk))

    # Handle modifier variants...
    return key
```

This ensures `Ctrl+=` matches whether the key comes as character `'='` or VK code `<187>`.

### Shift Modifier Changes Characters

The Shift modifier fundamentally changes the character produced by a key, making it unsuitable for symbol key hotkeys.

**The Problem:**

- Hotkey configured as `Shift+=` expects `{<Key.shift>, '='}`
- But pressing Shift+= sends `{<Key.shift>, '+'}` (the shifted character)
- Hotkey never matches

This is not a bug - it's how keyboards work. Shift+1 produces `!`, Shift+= produces `+`, etc.

**The Solution:**

1. Use Ctrl or Alt as modifiers for symbol keys (they don't change the character)
2. Use Shift only with:
   - Letter keys (a-z) - Shift+A still normalizes to 'a' for matching
   - Function keys (F1-F12) - Shift+F1 works correctly
   - Special keys like Space, Enter, Tab

**Alternative:** Create a shifted-to-unshifted mapping, but this is keyboard-layout dependent and fragile:

```python
# NOT RECOMMENDED - layout dependent
SHIFTED_TO_UNSHIFTED = {
    '+': '=', '!': '1', '@': '2', '#': '3', '$': '4',
    '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
}
```

Better to document that Shift+symbol hotkeys won't work and recommend Ctrl/Alt instead.

## Windows Console Encoding

Windows console encoding (cp1251, cp1252, etc.) doesn't support many Unicode symbols that work fine on Linux/macOS.

### The Problem

Printing Unicode status symbols like `●`, `◐`, `✓`, `✗` raises `UnicodeEncodeError` on Windows, potentially crashing the application or preventing code after the print from executing.

### The Solution

Wrap print statements in try/except and provide ASCII fallback.

```python
def _print_status(self, message: str = "") -> None:
    """Print status with encoding fallback."""
    # Do critical operations BEFORE print (in case print fails)
    self._write_status_file(state)

    # Print with encoding fallback
    try:
        print(f"\r{message:<60}\r", end="", flush=True)
    except UnicodeEncodeError:
        ascii_msg = message.encode('ascii', 'replace').decode('ascii')
        print(f"\r{ascii_msg:<60}\r", end="", flush=True)
```

Always perform critical operations like writing status files BEFORE print statements that might fail.

## Cross-Thread tkinter Updates via Queue

While `after()` is commonly recommended for cross-thread tkinter updates, it's not always reliable for state changes from hotkey callbacks.

### The Problem

Using `root.after(0, callback)` from a background thread to update tkinter widgets can fail silently or result in missed updates, especially when the main thread is busy with animations.

### The Solution

Use `queue.Queue` for thread-safe state updates, with explicit polling from the main thread.

```python
import queue

class STTOverlay:
    def __init__(self):
        self._state_queue = queue.Queue()
        self._root = None

    def set_state(self, state: str):
        """Update state (thread-safe, called from any thread)."""
        try:
            self._state_queue.put_nowait(state)
        except Exception:
            pass

    def process_queue(self):
        """Process pending updates (call from main thread)."""
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
        # Update widgets here - safe because we're in main thread
        self._status_label.config(text=state)
```

Call `process_queue()` from the main loop:

```python
while self._running:
    if self._overlay and self._overlay._root:
        try:
            self._overlay.process_queue()
            self._overlay._root.update()
        except Exception:
            self._overlay = None
    time.sleep(0.016)  # ~60fps for smooth animation
```

This pattern is more reliable than `after()` for inter-thread communication because it explicitly processes the queue in the main thread context.

## Platform-Specific Color Names

Some tkinter color names are platform-specific and will raise errors on other platforms.

### The Problem

Colors like `"systemTransparent"` work on macOS but raise `_tkinter.TclError` on Windows.

### The Solution

Avoid platform-specific color names. Use hex colors or standard named colors that work everywhere.

```python
# Bad - macOS only
self._root.configure(bg="systemTransparent")

# Good - works everywhere
self._root.configure(bg="#1a1a1a")
```

## Dark Theme Widgets on Windows

Windows native theming overrides ttk widget styling, making it difficult to create consistent dark-themed UIs.

### The Problem

ttk.Combobox and other ttk widgets on Windows ignore `fieldbackground` and similar styling because the native Windows theme takes precedence. Even after setting styles like:

```python
style.configure("Dark.TCombobox", fieldbackground="#242424", foreground="#ffffff")
```

The combobox input area remains white because Windows draws it using system theme colors.

### The Solution

Replace ttk widgets with custom tk-based alternatives that respect styling.

For dropdowns, use `tk.Menubutton` with a `tk.Menu`:

```python
# Create dark dropdown using Menubutton (ttk.Combobox has white bg on Windows)
self._model_var = tk.StringVar(value=default_value)

dropdown_frame = tk.Frame(parent, bg=border_color, bd=0)
dropdown_frame.pack(side=tk.RIGHT)

dropdown = tk.Menubutton(
    dropdown_frame,
    textvariable=self._model_var,
    font=("Segoe UI", 10),
    fg=text_color,
    bg=surface_color,
    activebackground=accent_color,
    activeforeground=text_color,
    bd=0,
    padx=12,
    pady=6,
    width=32,
    anchor="w",
    indicatoron=True,
    relief="flat",
    highlightthickness=1,
    highlightbackground=border_color,
    highlightcolor=accent_color,
)
dropdown.pack(padx=1, pady=1)

menu = tk.Menu(
    dropdown,
    tearoff=0,
    bg=surface_color,
    fg=text_color,
    activebackground=accent_color,
    activeforeground=text_color,
    bd=0,
    relief="flat",
)
dropdown["menu"] = menu

for item in items:
    menu.add_command(label=item, command=lambda i=item: select_item(i))
```

### Dark Title Bar on Windows 10/11

Windows title bars are white by default. Use the DWM API to enable dark mode:

```python
import ctypes
import platform

def set_dark_title_bar(window) -> None:
    """Set dark title bar on Windows 10/11."""
    if platform.system() != "Windows":
        return
    try:
        window.update_idletasks()
        window.update()

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # For older Windows 10 builds
        GA_ROOT = 2
        value = ctypes.c_int(1)

        # Get HWND using GetAncestor (works for both Tk and Toplevel)
        hwnd = ctypes.windll.user32.GetAncestor(window.winfo_id(), GA_ROOT)
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
```

Call after window creation. For modal dialogs, also call after the window is fully shown:
```python
self._window.after(50, lambda: set_dark_title_bar(self._window))
```

Note: Dark title bars can be unreliable with tkinter Toplevel windows. The DWM API sometimes doesn't apply correctly depending on timing and window type.

### ttk Theme for Dark Styling

The default Windows ttk theme ignores custom colors. Use the "clam" theme for proper dark styling:

```python
def _configure_styles(self):
    style = ttk.Style()

    # Use clam theme - Windows native theme ignores colors
    style.theme_use("clam")

    style.configure(
        "Dark.TCombobox",
        fieldbackground="#242424",
        background="#242424",
        foreground="#ffffff",
        arrowcolor="#ffffff",
        selectbackground="#4a9eff",
        padding=4,
    )

    # Combobox dropdown listbox colors
    self._window.option_add("*TCombobox*Listbox.background", "#242424")
    self._window.option_add("*TCombobox*Listbox.foreground", "#ffffff")
    self._window.option_add("*TCombobox*Listbox.selectBackground", "#4a9eff")

    style.configure(
        "Dark.Horizontal.TProgressbar",
        troughcolor="#242424",
        background="#4a9eff",
        lightcolor="#4a9eff",
        darkcolor="#4a9eff",
    )
```

### Tool Window Style

To remove the minimize button and create a dialog-like appearance:

```python
window.attributes("-toolwindow", True)
```

This creates a smaller title bar without minimize/maximize buttons.

## PyInstaller Compilation

Compiling tkinter+pystray applications with PyInstaller requires special handling for several issues.

### Tcl/Tk Data Files

tkinter requires Tcl/Tk library files at runtime. PyInstaller doesn't always bundle these correctly.

**The Problem:**

When running the compiled exe, tkinter fails with:

```
_tkinter.TclError: Can't find a usable init.tcl in the following directories
```

**The Solution:**

1. Add Tcl/Tk data directories to PyInstaller with `--add-data`:

```bash
pyinstaller --onefile --windowed \
    --add-data "C:/Python314/tcl/tcl8.6;_tcl_data/tcl8.6" \
    --add-data "C:/Python314/tcl/tk8.6;_tcl_data/tk8.6" \
    --runtime-hook pyi_rth_tcltk.py \
    your_app.py
```

2. Create a runtime hook `pyi_rth_tcltk.py` to set environment variables:

```python
# PyInstaller runtime hook to set Tcl/Tk library paths
import os
import sys

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    tcl_path = os.path.join(base_path, '_tcl_data', 'tcl8.6')
    tk_path = os.path.join(base_path, '_tcl_data', 'tk8.6')

    if os.path.exists(tcl_path):
        os.environ['TCL_LIBRARY'] = tcl_path
    if os.path.exists(tk_path):
        os.environ['TK_LIBRARY'] = tk_path
```

The runtime hook runs before your application code, ensuring the paths are set before tkinter imports.

### numpy Circular Import

numpy versions with certain PyInstaller configurations can fail with circular import errors.

**The Problem:**

```
ImportError: cannot import name '_pocketfft_umath' from partially initialized module
```

**The Solution:**

Create a runtime hook `pyi_rth_numpy.py` that pre-imports the problematic modules:

```python
# PyInstaller runtime hook for numpy circular import fix
import numpy.fft._pocketfft_umath  # noqa: F401
import numpy.fft._pocketfft  # noqa: F401
import numpy.fft  # noqa: F401
```

Add to PyInstaller command:

```bash
pyinstaller --runtime-hook pyi_rth_numpy.py ...
```

### Frozen Exe Detection for Subprocess

When spawning child processes from a frozen exe, you can't use `python -m module` syntax.

**The Problem:**

Code that spawns a daemon with `[sys.executable, "-m", "myapp.daemon"]` fails in a frozen exe because `sys.executable` is the exe, not Python.

**The Solution:**

Detect frozen mode and adjust the command:

```python
import sys
import subprocess

def spawn_daemon():
    if getattr(sys, 'frozen', False):
        # Running as frozen exe - use exe directly
        cmd = [sys.executable, "daemon", "run"]
    else:
        # Running as Python script
        cmd = [sys.executable, "-m", "myapp.daemon", "run"]

    subprocess.Popen(cmd, ...)
```

The frozen exe receives command-line arguments directly, so you need to handle them in your CLI entry point.

### pystray Callbacks Run in Background Thread

pystray menu callbacks execute in a background thread, not the main thread. This causes issues with tkinter.

**The Problem:**

Clicking "Settings" in the tray menu causes:

```
RuntimeError: main thread is not in main loop
```

This happens because pystray runs menu callbacks in its own background thread, but tkinter dialogs must be created in the main thread.

**The Solution:**

Queue callbacks for execution in the main thread:

```python
import queue
from typing import Callable

class DaemonService:
    def __init__(self):
        self._main_thread_queue: queue.Queue[Callable[[], None]] = queue.Queue()

    def _on_tray_settings_click(self):
        """Tray callback (runs in background thread)."""
        # Queue the dialog creation for main thread
        self._main_thread_queue.put(self._show_settings_dialog)

    def _show_settings_dialog(self):
        """Create settings dialog (must run in main thread)."""
        dialog = SettingsDialog(self._overlay._root, ...)
        dialog.show()

    def _main_loop(self):
        """Main event loop."""
        while self._running:
            # Process queued callbacks in main thread
            while True:
                try:
                    callback = self._main_thread_queue.get_nowait()
                    callback()
                except queue.Empty:
                    break

            # Update tkinter
            if self._overlay and self._overlay._root:
                self._overlay._root.update()

            time.sleep(0.016)
```

Pass `_on_tray_settings_click` to pystray, and it will queue the real work for the main thread.

### Console Window Behavior

For debugging, you may want a console window. For production, hide it.

**The Solution:**

Use `--windowed` for production builds (no console). For debugging, omit it to see stdout/stderr:

```bash
# Production (no console)
pyinstaller --onefile --windowed app.py

# Debug (with console)
pyinstaller --onefile app.py
```

Or control programmatically:

```python
# In your app, detect if console should be hidden
if not DEBUG_MODE and sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(
        ctypes.windll.kernel32.GetConsoleWindow(), 0
    )
```

## Window Visibility and Message Pump

The Windows message pump is critical for tkinter dialog functionality. Hiding windows incorrectly can break dialogs.

### The Problem

When using `window.withdraw()` to hide a tkinter window, Windows considers it "not visible" and stops pumping messages for it. This causes modal dialogs (like Settings) opened from tray callbacks to freeze or show empty content.

### The Solution

Instead of `withdraw()`, move the window off-screen to keep it "visible" to Windows:

```python
def hide(self):
    """Hide the overlay by moving off-screen (preserves message pump)."""
    if self._root:
        # Save current position for restore
        self._pos_x = self._root.winfo_x()
        self._pos_y = self._root.winfo_y()
        # Move way off-screen instead of withdraw()
        self._root.geometry("+32000+32000")

def unhide(self):
    """Restore the overlay to its saved position."""
    if self._root:
        self._root.geometry(f"+{self._pos_x}+{self._pos_y}")
```

This keeps the window "visible" to Windows (just off-screen), so it continues to process messages for dialogs.

### Alternative: Switch to Minimal Mode

Instead of hiding completely, switch to a minimal/tiny mode that's still visible:

```python
def _close(self):
    """Close (minimize to tiny mode) the overlay."""
    # Switch to tiny mode instead of hiding completely
    if self._mode != self.MODE_TINY:
        self._switch_to_tiny()
```

This is often better UX anyway - the user can see the app is still running.

## Icon Quality with PNG and PIL

Drawing icons with tkinter canvas primitives often produces crude results. Use PNG images with PIL for quality icons.

### The Problem

Canvas primitives like `create_arc`, `create_oval`, and `create_line` produce low-quality icons. Outline-style icons drawn with arcs can look like unintended shapes (faces, smileys). Complex SVG paths are nearly impossible to replicate accurately.

### The Solution

Use pre-made PNG icons and tint them with PIL based on state:

```python
from PIL import Image, ImageTk

class Overlay:
    def __init__(self):
        self._mic_photo = None  # Keep reference to prevent garbage collection
        self._mic_base_image = None

    def _load_mic_icon(self):
        """Load the base white mic icon."""
        if self._mic_base_image is not None:
            return

        try:
            icon_path = self._get_icon_path()
            if icon_path.exists():
                self._mic_base_image = Image.open(icon_path).convert("RGBA")
        except Exception:
            pass

    def _tint_image(self, image: Image.Image, color: str) -> Image.Image:
        """Tint a white image to the specified color."""
        color = color.lstrip("#")
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)

        data = image.getdata()
        new_data = []
        for item in data:
            if item[3] > 0:  # Has alpha
                brightness = item[0] / 255.0  # Original white brightness
                new_data.append((
                    int(r * brightness),
                    int(g * brightness),
                    int(b * brightness),
                    item[3]  # Preserve alpha
                ))
            else:
                new_data.append(item)

        tinted = Image.new("RGBA", image.size)
        tinted.putdata(new_data)
        return tinted

    def _draw_icon(self, color: str):
        """Draw tinted icon on canvas."""
        self._load_mic_icon()
        if self._mic_base_image:
            # Resize to fit canvas
            resized = self._mic_base_image.resize((24, 24), Image.Resampling.LANCZOS)
            tinted = self._tint_image(resized, color)
            self._mic_photo = ImageTk.PhotoImage(tinted)  # Keep reference!
            self._canvas.create_image(cx, cy, image=self._mic_photo, anchor=tk.CENTER)
```

**Critical:** Keep a reference to `ImageTk.PhotoImage` objects (e.g., `self._mic_photo`). If the reference is lost, Python garbage collects the image and it disappears from the canvas.

### PyInstaller: Bundle PNG Icons

Add PNG icons to PyInstaller build:

```bash
pyinstaller --add-data "mic_256.png;." ...
```

In code, detect frozen exe and adjust path:

```python
def _get_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        # Frozen exe: icon in _internal folder
        return Path(sys.executable).parent / "_internal" / "mic_256.png"
    else:
        # Dev: icon in project root
        return Path(__file__).parent.parent.parent.parent / "mic_256.png"
```

## Microsoft-Style UI Patterns

Microsoft's modern UI (like Voice Typing) uses subtle visual cues instead of hard borders.

### Pattern: Lighter Background, No Border

Instead of adding visible borders for contrast on dark taskbars, use a slightly lighter background color:

```python
# Instead of border
self._bg_color = "#1a1a1a"
self._border_color = "#333333"
container = tk.Frame(root, bg=self._bg_color, highlightbackground=self._border_color, highlightthickness=1)

# Microsoft style - lighter background, no border
self._bg_color = "#2d2d2d"  # Slightly lighter
container = tk.Frame(root, bg=self._bg_color, highlightthickness=0)
```

The #2d2d2d background is visible against both dark (#1a1a1a) and black (#000000) taskbars without needing an explicit border.

### Pattern: Shadow Effect

tkinter doesn't support true shadows, but you can simulate depth with a darker frame behind:

```python
# Shadow simulation (pseudo-code)
shadow_frame = tk.Frame(root, bg="#0a0a0a")  # Darker shadow
shadow_frame.place(x=2, y=2, width=w, height=h)  # Offset
main_frame = tk.Frame(root, bg="#2d2d2d")
main_frame.place(x=0, y=0, width=w, height=h)
```

## Rounded Corners on Windows 11

Windows 11 introduces rounded corners via DWM. You can apply them to tkinter windows for a modern look.

### Using DWM API for Rounded Corners

```python
import ctypes
import sys

def apply_rounded_corners(window, radius: int = 2):
    """Apply rounded corners to a tkinter window using Win32 DWM API.

    Args:
        window: tkinter Tk or Toplevel window
        radius: 1=small, 2=medium (default), 3=round
    """
    if sys.platform != "win32":
        return

    try:
        window.update()  # Ensure HWND exists

        # DWMWA_WINDOW_CORNER_PREFERENCE = 33 (Windows 11+)
        DWMWA_WINDOW_CORNER_PREFERENCE = 33

        # Corner values: 0=default, 1=don't round, 2=round, 3=round small
        value = ctypes.c_int(radius)

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass  # Fails silently on older Windows
```

Call after window creation and after any geometry changes.

## Drop Shadows on Windows

Enable DWM shadows for floating windows.

### Using DWM API for Shadows

```python
def enable_shadow(window):
    """Enable drop shadow using DWM non-client rendering.

    Works best with borderless windows that still need depth cues.
    """
    if sys.platform != "win32":
        return

    try:
        window.update()

        # DWMWA_NCRENDERING_POLICY = 2
        DWMWA_NCRENDERING_POLICY = 2
        value = ctypes.c_int(2)  # DWMNCRP_ENABLED

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_NCRENDERING_POLICY,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass
```

Note: Shadow visibility depends on window attributes and DWM composition state.

## Singleton Dialog Pattern

Prevent multiple instances of the same dialog from opening.

### The Problem

Clicking "Settings" multiple times in the tray menu creates multiple overlapping dialogs.

### The Solution

Track the dialog instance and check visibility before creating new ones:

```python
class DaemonService:
    def __init__(self):
        self._settings_dialog = None

    def _show_settings_dialog(self):
        """Show settings, reusing existing dialog if visible."""
        # Check if dialog already visible
        if self._settings_dialog and self._settings_dialog.is_visible():
            # Bring existing dialog to front
            if self._settings_dialog._window:
                self._settings_dialog._window.lift()
                self._settings_dialog._window.focus_force()
            return

        # Create new dialog
        self._settings_dialog = SettingsDialog(
            parent=self._root,
            config=self.config,
            on_save=self._on_config_change,
        )
        self._settings_dialog.show()
```

The dialog class needs an `is_visible()` method:

```python
class SettingsDialog:
    def is_visible(self) -> bool:
        """Check if dialog window exists and is visible."""
        try:
            return self._window and self._window.winfo_exists()
        except tk.TclError:
            return False
```

## Dynamic Scrollbar Visibility

Show scrollbars only when content exceeds the visible area.

### The Pattern

Bind to window resize events and toggle scrollbar visibility based on content height:

```python
class SettingsDialog:
    def _setup_scrollable_content(self):
        """Create scrollable frame with dynamic scrollbar."""
        # Container
        container = tk.Frame(self._window, bg=self._bg)
        container.pack(fill=tk.BOTH, expand=True)

        # Canvas for scrolling
        self._canvas = tk.Canvas(container, bg=self._bg, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(container, orient="vertical",
                                         command=self._canvas.yview)

        # Content frame
        self._content = tk.Frame(self._canvas, bg=self._bg)
        self._content_window = self._canvas.create_window(
            (0, 0), window=self._content, anchor="nw"
        )

        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind resize events
        self._window.bind("<Configure>", self._on_window_resize)
        self._content.bind("<Configure>", self._on_content_resize)

    def _on_window_resize(self, event=None):
        """Handle window resize - update canvas width."""
        if not self._window:
            return

        # Update canvas window width to match
        new_width = self._window.winfo_width() - 40  # Padding
        self._canvas.itemconfig(self._content_window, width=new_width)
        self._update_scrollbar_visibility()

    def _on_content_resize(self, event=None):
        """Handle content resize - update scroll region."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._update_scrollbar_visibility()

    def _update_scrollbar_visibility(self):
        """Show/hide scrollbar based on content vs canvas height."""
        content_height = self._content.winfo_reqheight()
        canvas_height = self._canvas.winfo_height()

        if content_height > canvas_height:
            self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        else:
            self._scrollbar.pack_forget()
```

Key points:
1. Use `winfo_reqheight()` for content's required height
2. Use `winfo_height()` for canvas's actual height
3. Pack/pack_forget scrollbar instead of configuring visibility

## Debug-Only Logging Pattern

Only create log files when running in debug mode.

### The Problem

Log files created during normal operation fill up disk space and cause issues with cloud sync.

### The Solution

Use an environment variable to control logging behavior:

```python
# In cli.py - set flag before daemon spawn
if args.debug:
    os.environ["CLD_DEBUG_MODE"] = "1"

# In daemon.py - check flag in logging setup
def setup_logging(level: str) -> None:
    """Configure logging - only in debug mode."""
    debug_mode = os.environ.get("CLD_DEBUG_MODE") == "1"

    if debug_mode:
        logging.basicConfig(
            level="DEBUG",
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    # In normal mode: no basicConfig = minimal logging, no log file

# In daemon.py - spawn without log file redirect
def _spawn_background():
    """Spawn background daemon without log files."""
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
```

This prevents `daemon.log` from being created during normal use.

## Shared Utility for Icon Paths

When multiple modules need the same icon file, centralize the path resolution.

### The Problem

Multiple files (tray.py, model_dialog.py, settings_dialog.py, daemon_service.py) each implement their own `_get_app_icon_path()` method, violating DRY.

### The Solution

Create a shared utility in a common module:

```python
# In ui/__init__.py
import sys
from pathlib import Path

def get_app_icon_path() -> Path:
    """Get path to app icon for all UI components.

    Returns:
        Path to icon in project root (source) or _internal (frozen exe).
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent / "_internal"
    else:
        base = Path(__file__).parent.parent.parent  # Adjust for your structure
    return base / "app_icon.png"

# In each module that needs it
from myapp.ui import get_app_icon_path

icon_path = get_app_icon_path()
if icon_path.exists():
    img = Image.open(icon_path)
```

Benefits:
1. Single source of truth for path logic
2. Frozen exe detection in one place
3. Easy to update path structure

## Audio Spectrum Visualization

Real-time audio visualization requires careful frequency band selection for voice applications.

### Voice Frequency Focus

Don't visualize the full audio spectrum (20Hz-20kHz). Voice content lives in a narrow range:

| Component | Range | Visual Feedback |
|-----------|-------|-----------------|
| Fundamentals | 85-255 Hz | Low bars |
| Formants | 300-3400 Hz | Middle bars |
| Consonants | 2000-4000 Hz | High bars |

For 16-bar visualization, focus on 200-4000 Hz:

```python
min_freq, max_freq = 200, 4000
for i in range(16):
    f_low = min_freq * (max_freq / min_freq) ** (i / 16)
    f_high = min_freq * (max_freq / min_freq) ** ((i + 1) / 16)
    bin_low = int(f_low * n_bins * 2 / sample_rate)
    bin_high = int(f_high * n_bins * 2 / sample_rate)
    band_mag = np.mean(magnitudes[bin_low:bin_high])
```

### Failed Approach: Fake Bass

Synthesizing bass response from overall volume level produces unnatural results:

```python
# DON'T DO THIS - bass bars are constantly maxed out
for i in range(8):
    noise = random.uniform(0.8, 1.2)
    bands[i] = level * bass_weight * noise  # Fake, not real FFT
```

Problems:
- Left bars maxed out regardless of voice content
- Random variation looks artificial
- Right bars don't respond to actual consonants

### Recommended Approach: Pure FFT

Let FFT show real frequency content without artificial enhancement:

```python
# Normalize to peak magnitude, scale by level
max_mag = max(bands) if bands else 1.0
if max_mag > 0:
    bands = [min(1.0, (b / max_mag) * level * 3.0) for b in bands]
```

All 16 bars respond naturally to voice content when focused on the voice frequency range.

## GPU Device Selection for Whisper.cpp

When using pywhispercpp with Vulkan backend, GPU device selection has important gotchas.

### Auto-Select Doesn't Work with gpu_device=-1

Passing `gpu_device=-1` to pywhispercpp Model doesn't auto-select the best GPU. Whisper.cpp interprets -1 as "no specific device" which falls back to CPU. Fix: explicitly use `gpu_device=0` for auto-select.

```python
# BAD: -1 causes CPU fallback
gpu_device = config.engine.gpu_device  # -1 for "Auto-select"
engine = WhisperEngine(gpu_device=gpu_device)  # Uses CPU!

# GOOD: Map -1 to 0 when GPU is available
gpu_device = config.engine.gpu_device
if gpu_device == -1 and is_gpu_supported():
    gpu_device = 0  # First discrete GPU in Vulkan order
engine = WhisperEngine(gpu_device=gpu_device)  # Uses GPU!
```

### Vulkan vs Windows GPU Order

Windows Task Manager shows GPUs in its own order (often integrated first). Vulkan enumerates discrete GPUs before integrated:

| Windows Task Manager | Vulkan Order |
|---------------------|--------------|
| GPU 0: AMD Radeon (integrated) | Device 0: RTX 4090 (discrete) |
| GPU 1: RTX 4090 (discrete) | Device 1: AMD Radeon (integrated) |

When WMI fallback is used for GPU enumeration, reorder to match Vulkan's expected order: NVIDIA discrete first, then AMD discrete, then integrated.

### Cache Hardware Detection

Hardware detection is slow (WMI queries, Vulkan probing). Cache the result instead of detecting repeatedly:

```python
class SettingsDialog:
    def __init__(self):
        self._hw_info = None  # Cached hardware info

    def _build_engine_section(self, parent):
        if self._hw_info is None:
            self._hw_info = detect_hardware()  # Detect once
        # Use self._hw_info

    def _build_hardware_section(self, parent):
        # Reuse cached result
        hw_info = self._hw_info

    def _on_gpu_change(self, event=None):
        # DON'T call detect_hardware() here - causes UI hang
        # Use cached self._hw_info instead
        backend = self._hw_info.gpu_backend if self._hw_info else "CPU"
```

Calling `detect_hardware()` on every dropdown change causes UI freeze and duplicate log lines.

## Summary Checklist

When building a Windows tray app with tkinter and pystray, verify:

1. tkinter mainloop runs in main thread
2. pystray uses `start_detached()` for background operation
3. Modal dialogs temporarily disable parent's topmost
4. Progress bars use `animate=False` for background updates
5. Config files use LOCALAPPDATA, not home directory
6. All UI updates happen via `after()` polling or queue.Queue from main thread
7. Use `RLock()` not `Lock()` to avoid deadlocks in nested calls
8. OAuth token expiration is checked before API calls
9. External link opening uses subprocess and flag protection
10. Don't use DETACHED_PROCESS if you need pynput global hotkeys
11. Handle Unicode print errors with try/except and ASCII fallback
12. Handle Alt_Gr separately from Alt_L/Alt_R in hotkey normalization
13. Map Windows VK codes to characters in hotkey normalization (Ctrl/Alt held = VK codes, not chars)
14. Don't use Shift modifier with symbol keys (Shift changes the character: Shift+= sends '+', not '=')
13. Use hex colors, not platform-specific color names like "systemTransparent"
14. Use tk.Menubutton+Menu instead of ttk.Combobox for dark-themed dropdowns
15. Use DWM API with DWMWA_USE_IMMERSIVE_DARK_MODE (20) for dark title bars
16. Use `-toolwindow` attribute for dialog-style windows without minimize button

**PyInstaller-specific:**

17. Bundle Tcl/Tk data with `--add-data` and runtime hook setting TCL_LIBRARY/TK_LIBRARY
18. Fix numpy circular imports with runtime hook pre-importing `numpy.fft._pocketfft_umath`
19. Detect frozen exe with `getattr(sys, 'frozen', False)` and use `sys._MEIPASS` for bundled paths
20. Adjust subprocess commands for frozen exe (can't use `python -m module`)
21. Queue pystray menu callbacks for main thread execution (they run in background thread)
22. Use `uv run pyinstaller` when dependencies are only in .venv, not system Python
23. Build on local drive (not OneDrive) to avoid file locking issues during compilation
24. For --debug console: allocate console early with `AllocConsole()` BEFORE imports, redirect stdout to `CONOUT$`
25. --debug mode must force foreground execution (not background spawn) to keep console open
26. Sound/data file paths: use `Path(sys.executable).parent / "_internal" / "sounds"` for onedir builds
27. Don't create separate `tk.Tk()` instances in threads - causes freezes; use `Toplevel()` with existing root
28. Intel Fortran/MKL crash on console close: set `FOR_DISABLE_CONSOLE_CTRL_HANDLER=1` env var BEFORE imports
29. Subprocess console appearing with overlay: use `CREATE_NO_WINDOW` (0x08000000) flag, not just omit DETACHED_PROCESS
30. PyInstaller must use `--onedir` not `--onefile` to avoid _MEI temp directory cleanup conflicts with daemon spawning
31. Bundle mic/icon PNGs with `--add-data "mic_256.png;."` - they go to `_internal/` folder in onedir builds

**Modern Windows 11 styling:**

32. Rounded corners: Use DWM API with `DWMWA_WINDOW_CORNER_PREFERENCE` (33) and value 2 for medium rounding
33. Drop shadows: Use DWM API with `DWMWA_NCRENDERING_POLICY` (2) and value 2 (DWMNCRP_ENABLED)
34. Singleton dialogs: Track instance and check `is_visible()` before creating new ones; use `lift()` and `focus_force()` for existing
35. Dynamic scrollbar: Compare `winfo_reqheight()` vs `winfo_height()`, use `pack/pack_forget` to toggle visibility
36. Debug-only logging: Use environment variable to control logging setup, spawn with `subprocess.DEVNULL`
37. Shared utilities: Centralize frozen exe path logic in one module to avoid duplication (DRY)
38. Modal dark title bar: Call `set_dark_title_bar()` via `window.after(50, ...)` after `grab_set()` for reliability

## Intel MKL / Fortran Runtime Crash

When using libraries that depend on Intel MKL (numpy, faster-whisper), closing a console window causes a fatal crash.

### The Problem

```
Intel(r) Visual Fortran run-time error
forrtl: error (200): program aborting due to window-CLOSE event
```

This happens because Intel's Fortran runtime installs its own console control handler that aborts on `CTRL_CLOSE_EVENT`.

### The Solution

Set the environment variable to disable Intel's handler BEFORE any imports:

```python
"""CLI entry point."""
import os
import sys

# Disable Intel Fortran console handler BEFORE any imports
# Prevents "forrtl: error (200)" crash when console window is closed
os.environ.setdefault("FOR_DISABLE_CONSOLE_CTRL_HANDLER", "1")

# Now safe to import numpy, faster-whisper, etc.
import numpy
```

This must be at the very top of your entry point, before any library imports.

## Subprocess Console Window Prevention

When spawning a background process that uses a GUI overlay, you need to prevent console windows from appearing.

### The Problem

Using `subprocess.CREATE_NEW_PROCESS_GROUP` without `DETACHED_PROCESS` can still create a console window on some systems, even when the parent is a windowed application.

### The Solution

Use `CREATE_NO_WINDOW` flag when spawning GUI processes:

```python
import subprocess

def spawn_background_with_overlay():
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    if enable_overlay:
        # Use CREATE_NO_WINDOW to prevent console but keep window station for pynput
        CREATE_NO_WINDOW = 0x08000000
        creationflags |= CREATE_NO_WINDOW
    else:
        # Fully detach when no GUI needed
        creationflags |= subprocess.DETACHED_PROCESS

    subprocess.Popen(cmd, creationflags=creationflags, ...)
```

Key differences:
- `DETACHED_PROCESS`: No console, no window station (breaks pynput hotkeys)
- `CREATE_NO_WINDOW`: No console, but keeps window station (pynput works)

## Overlay State Update Consistency

When using a status message pattern to update overlay state, ensure ALL possible messages are mapped to state transitions.

### The Problem

A `_print_status()` function that maps message content to overlay states can miss cases:

```python
def _print_status(self, message: str = "", clear: bool = False) -> None:
    if "Recording" in message:
        self._write_status_file("recording")
    elif "Transcribing" in message:
        self._write_status_file("transcribing")
    elif "Ready" in message or "No speech" in message:
        self._write_status_file("ready")
    elif "failed" in message:
        self._write_status_file("error")
    elif clear:
        self._write_status_file("ready")
    # BUG: "Too short" message doesn't match any condition!
```

When `_print_status("○ Too short")` is called, none of the conditions match, so the overlay never updates from "recording" to "ready" state. The UI appears stuck.

### The Solution

Ensure all possible status messages map to state updates:

```python
def _print_status(self, message: str = "", clear: bool = False) -> None:
    if "Recording" in message:
        self._write_status_file("recording")
    elif "Transcribing" in message:
        self._write_status_file("transcribing")
    elif "Ready" in message or "No speech" in message or "Too short" in message:
        self._write_status_file("ready")  # Added "Too short"
    elif "failed" in message:
        self._write_status_file("error")
    elif clear:
        self._write_status_file("ready")
```

Better approach: explicitly map ALL message types:

```python
def _print_status(self, message: str = "", clear: bool = False) -> None:
    # Map all messages to states explicitly
    state_map = {
        "Recording": "recording",
        "Transcribing": "transcribing",
        "Ready": "ready",
        "No speech": "ready",
        "Too short": "ready",  # Short recordings return to ready
        "failed": "error",
        "Output failed": "error",
    }

    state = "ready" if clear else None
    for pattern, s in state_map.items():
        if pattern in message:
            state = s
            break

    if state:
        self._write_status_file(state)
```

### Debugging Tips

When overlay appears stuck:
1. Check if the state queue is receiving updates (`set_state()` being called)
2. Check if `process_queue()` is being called from main loop
3. Check if the status message matches any condition in `_print_status()`
4. Add logging to trace the full flow: message → status file → overlay state

## Complete PyInstaller Build Command

For CLD-style apps with tkinter, pystray, sounddevice, and faster-whisper:

```bash
# Step 1: Sync to local drive (avoid OneDrive file locking)
robocopy "D:\OneDrive\MyApp" "D:\MyApp" /MIR /XD .venv dist build __pycache__ .git

# Step 2: Setup venv with correct Python version
cd D:\MyApp && uv sync --python 3.12 --extra dev && uv pip install pyinstaller pyinstaller-hooks-contrib

# Step 3: Build
uv run pyinstaller -y --onedir --windowed --name MyApp \
    --add-data "sounds;sounds" \
    --add-data "mic_256.png;." \
    --add-data "C:/Python314/tcl/tcl8.6;tcl/tcl8.6" \
    --add-data "C:/Python314/tcl/tk8.6;tcl/tk8.6" \
    --add-data ".venv/Lib/site-packages/_sounddevice_data;_sounddevice_data" \
    --runtime-hook pyi_rth_numpy.py \
    --runtime-hook pyi_rth_tcltk.py \
    --hidden-import faster_whisper \
    --hidden-import sounddevice \
    --hidden-import _sounddevice \
    --exclude-module pytest \
    --exclude-module iniconfig \
    src/myapp/cli.py
```

**Critical points:**
- MUST build on local drive, not OneDrive (file locking during compilation)
- MUST use `uv run pyinstaller` to include venv dependencies
- MUST use `--onedir` not `--onefile` (avoids _MEI cleanup conflicts)
- MUST include sounddevice hidden imports AND _sounddevice_data folder
- Runtime hooks fix numpy circular import and Tcl/Tk paths

## Creating Windows Installers with Inno Setup

After building your exe, create a proper Windows installer for distribution.

### Why Use an Installer

A PyInstaller `--onedir` build creates a folder with hundreds of files (~365MB for a typical ML app). Distributing this folder directly has issues:

1. Users must manually extract and find the exe
2. No Start Menu or Desktop shortcuts
3. No proper uninstall mechanism
4. No Program Files integration
5. No startup-with-Windows option

Inno Setup creates a professional installer that handles all of this.

### Installing Inno Setup

Download from https://jrsoftware.org/isdl.php and install. The compiler (`ISCC.exe`) is typically at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`.

### Basic Installer Script

Create an `installer.iss` file:

```iss
; MyApp Installer Script for Inno Setup
#define MyAppName "MyApp"
#define MyAppFullName "My Application"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Your Name"
#define MyAppURL "https://github.com/yourname/myapp"
#define MyAppExeName "MyApp.exe"
#define MySourceDir "D:\myapp\dist\MyApp"

[Setup]
AppId={{GENERATE-A-GUID-HERE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppFullName}
AllowNoIcons=yes
OutputDir=D:\myapp\installer_output
OutputBaseFilename=MyApp-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=D:\myapp\app_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "startupicon"; Description: "Start automatically when Windows starts"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppFullName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppFullName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppFullName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppFullName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppFullName}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
var ResultCode: Integer;
begin
  Result := True;
  Exec('taskkill', '/F /IM MyApp.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ResultCode: Integer;
begin
  if CurStep = ssInstall then
    Exec('taskkill', '/F /IM MyApp.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
```

Generate a unique GUID for `AppId` using PowerShell:
```powershell
[guid]::NewGuid().ToString().ToUpper()
```

### Building the Installer

```powershell
# Command line
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" installer.iss

# Or open installer.iss in Inno Setup GUI and press Ctrl+F9
```

Output: `installer_output\MyApp-Setup-0.1.0.exe`

## Code Signing

Windows SmartScreen warns users about unsigned executables. Code signing establishes trust.

### Creating a Self-Signed Certificate

For development/internal use, create a self-signed certificate:

```powershell
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
    -Subject 'CN=MyApp Developer' `
    -KeyUsage DigitalSignature -KeySpec Signature -KeyLength 2048 `
    -KeyExportPolicy Exportable -CertStoreLocation 'Cert:\CurrentUser\My' `
    -NotAfter (Get-Date).AddYears(5)

# Note the thumbprint for later use
Write-Host "Thumbprint: $($cert.Thumbprint)"

# Optional: Export to PFX for backup
$password = ConvertTo-SecureString -String 'YourPassword' -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath 'codesign.pfx' -Password $password
```

Self-signed certificates show "Unknown Publisher" in SmartScreen, but the signature is valid and consistent.

### Signing Executables

```powershell
# Find your certificate
$thumbprint = 'YOUR-CERT-THUMBPRINT'
$cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object { $_.Thumbprint -eq $thumbprint }

# Sign the exe (with timestamp for long-term validity)
Set-AuthenticodeSignature -FilePath 'dist\MyApp\MyApp.exe' -Certificate $cert -TimestampServer 'http://timestamp.digicert.com'

# Verify
Get-AuthenticodeSignature -FilePath 'dist\MyApp\MyApp.exe'
```

### Complete Sign-and-Package Script

```powershell
# sign-and-package.ps1
$thumbprint = 'YOUR-CERT-THUMBPRINT'
$cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object { $_.Thumbprint -eq $thumbprint }

if (-not $cert) {
    Write-Error "Certificate not found"
    exit 1
}

$exePath = 'D:\myapp\dist\MyApp\MyApp.exe'
$installerOutput = 'D:\myapp\installer_output'

# Step 1: Sign the main exe
Write-Host "Signing MyApp.exe..."
$sig = Set-AuthenticodeSignature -FilePath $exePath -Certificate $cert -TimestampServer 'http://timestamp.digicert.com'
if ($sig.Status -ne 'Valid') {
    Write-Error "Signing failed: $($sig.Status)"
    exit 1
}

# Step 2: Build installer
Write-Host "Building installer..."
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
& $iscc 'D:\myapp\installer.iss'
if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup failed"
    exit 1
}

# Step 3: Sign the installer
$setupExe = Get-ChildItem "$installerOutput\MyApp-Setup-*.exe" | Select-Object -First 1
if ($setupExe) {
    Write-Host "Signing installer..."
    Set-AuthenticodeSignature -FilePath $setupExe.FullName -Certificate $cert -TimestampServer 'http://timestamp.digicert.com'
}

Write-Host "Done: $($setupExe.FullName)" -ForegroundColor Green
```

### Production Code Signing

For public distribution, purchase a code signing certificate from DigiCert, Sectigo, or Comodo. These certificates are recognized by Windows SmartScreen and don't show "Unknown Publisher" warnings.

## Nuitka vs PyInstaller

Both tools compile Python to standalone executables, but they handle complex dependencies differently.

### When to Use PyInstaller

Choose PyInstaller for apps that use:

- Audio/video processing (av, PyAV)
- Speech recognition (faster-whisper, whisper)
- Neural networks (ctranslate2, torch)
- Any package with complex C extensions or dynamic imports

PyInstaller uses a hook system that handles these packages automatically.

### When Nuitka Fails

Nuitka compiles Python to C for better performance, but struggles with:

1. Packages that use `importlib` for dynamic loading
2. C extensions with complex initialization (ctranslate2)
3. Packages that introspect their own module structure

Example failures with Nuitka:
- `ModuleNotFoundError: av.sidedata.encparams` - even with `--include-package=av`
- `AttributeError: __spec__` - ctranslate2 module initialization issues
- Missing cython modules despite explicit includes

### Nuitka Frozen Detection

If you do use Nuitka, note the different detection pattern:

```python
def _is_frozen() -> bool:
    """Check if running as frozen exe (PyInstaller or Nuitka)."""
    # PyInstaller
    if getattr(sys, "frozen", False):
        return True
    # Nuitka
    main_mod = sys.modules.get("__main__", object())
    return "__compiled__" in dir(main_mod)
```

Also note that in Nuitka, `sys.executable` points to the embedded Python interpreter, not your exe. Use `sys.argv[0]` instead:

```python
if _is_frozen():
    main_mod = sys.modules.get("__main__", None)
    if main_mod and hasattr(main_mod, "__compiled__"):
        # Nuitka: use sys.argv[0] for exe path
        exe_path = Path(sys.argv[0]).resolve()
    else:
        # PyInstaller: sys.executable is the exe
        exe_path = sys.executable
```

## Complete Build Workflow

### Directory Setup

```
D:\myapp\                        # Build directory (local, not OneDrive)
├── src/                         # Synced from OneDrive
├── sounds/                      # Audio assets
├── dist/MyApp/                  # PyInstaller output
│   ├── MyApp.exe
│   └── _internal/
├── installer_output/            # Inno Setup output
├── build-pyinstaller.ps1
├── sign-and-package.ps1
├── installer.iss
├── pyi_rth_numpy.py            # Runtime hooks
└── pyi_rth_tcltk.py
```

### Build Steps

```powershell
# 1. Sync source from OneDrive to local build folder
robocopy "D:\OneDrive\MyApp" "D:\myapp" /MIR /XD .venv dist build __pycache__ .git

# 2. Build exe
cd D:\myapp
.\build-pyinstaller.ps1

# 3. Test the exe
.\dist\MyApp\MyApp.exe --debug

# 4. Sign and create installer
.\sign-and-package.ps1

# 5. Test the installer
.\installer_output\MyApp-Setup-0.1.0.exe
```

### Version Bumps

Update version in three places:
1. `pyproject.toml` - `version = "0.1.0"`
2. `src/myapp/__init__.py` - `__version__ = "0.1.0"`
3. `installer.iss` - `#define MyAppVersion "0.1.0"`
