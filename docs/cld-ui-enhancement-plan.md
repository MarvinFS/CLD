# CLD UI Enhancement Plan - 11 Features

## Summary

This plan implements 11 UI/UX improvements for ClaudeCli-Dictate (CLD):

1. Add "works in any focused app" text to model setup dialog
2. Remove GPU detection from hardware.py
3. Fix white title bar on Manual Download window
4. Debug-only daemon.log (only create/write when --debug flag used)
5. Tiny overlay design matching Windows Voice Typing (darker drag bar, rounded corners, brighter icons, shadow)
6. Prevent multiple settings windows from opening
7. (skipped)
8. (skipped)
9. Resizable settings window with dynamic scrollbar
10. Remove hardware detection from settings dialog
11. Use cld_icon.png for About window, tray icon, and app thumbnail

## Critical Files to Modify

| File | Changes |
|------|---------|
| `src/cld/ui/model_dialog.py` | Add text line, remove GPU display, fix manual download dark title bar |
| `src/cld/ui/hardware.py` | Remove GPU/CUDA detection code |
| `src/cld/ui/settings_dialog.py` | Remove hardware section, add resizable + dynamic scrollbar, singleton pattern |
| `src/cld/ui/overlay.py` | Update tiny mode colors, add rounded corners, shadow, brighter icons |
| `src/cld/ui/tray.py` | Load and use cld_icon.png instead of generated icon |
| `src/cld/daemon_service.py` | Add icon to About dialog, singleton for settings dialog |
| `src/cld/daemon.py` | Conditional logging based on debug mode |
| `src/cld/cli.py` | Pass debug flag to daemon for conditional logging |

## Implementation Details

### Feature 1: Model Setup Dialog - Add Text Line

**File:** `src/cld/ui/model_dialog.py` (lines 232-243)

Add a new line after the privacy description: "Works in any focused app for text entry - type anywhere with your voice."

```python
# After line 237 (privacy text), add:
tk.Label(
    self._container,
    text="Works in any focused app for text entry - type anywhere with your voice.",
    font=("Segoe UI", 10),
    fg=self._text_dim,
    bg=self._bg,
    justify="left",
    wraplength=490,
).pack(anchor="w", pady=(0, 16))
```

### Feature 2: Remove GPU Detection from Hardware

**File:** `src/cld/ui/hardware.py`

Remove lines 80-99 (torch/CUDA detection block). The `has_cuda`, `gpu_name`, `vram_gb` fields will remain in dataclass but always be default (False/None).

Update `_get_recommendations()` (lines 107-149) to only use CPU-based recommendations:

```python
def _get_recommendations(info: HardwareInfo) -> tuple[str, str]:
    """Determine recommended Whisper model based on CPU cores."""
    # CPU-only recommendations
    if info.cpu_cores >= 8:
        return ("whisper", "medium")
    elif info.cpu_cores >= 4:
        return ("whisper", "small")
    else:
        return ("whisper", "base")
```

Update `HardwareInfo.summary` property to remove GPU text - just show "CPU (N cores)".

**File:** `src/cld/ui/model_dialog.py` (lines 260-271)

Remove GPU display lines. Simplify hardware info to show only:
- CPU: N cores
- RAM: N.N GB
- Recommended model: X

### Feature 3: Fix Manual Download Window Dark Title Bar

**File:** `src/cld/ui/model_dialog.py` (lines 547-570)

The dark title bar is applied at line 565, but it may not persist after modal setup. Add a second call after `grab_set()`:

```python
# After line 569 (manual_win.grab_set()), add:
manual_win.after(50, lambda: set_dark_title_bar(manual_win))
```

### Feature 4: Debug-Only Daemon Logging

**Files:** `src/cld/daemon.py`, `src/cld/cli.py`

**Approach:** Only configure logging and redirect to daemon.log when debug mode is active.

**cli.py changes:**
- Set environment variable `CLD_DEBUG_MODE=1` when `args.debug` is True (line 117)

**daemon.py changes:**
- Check `CLD_DEBUG_MODE` env var in `setup_logging()`
- Only call `logging.basicConfig()` if debug mode is on
- Only redirect stdout/stderr to daemon.log in `_spawn_background()` if NOT in debug mode (normal mode doesn't need log file)

```python
# In setup_logging():
def setup_logging(level: str) -> None:
    debug_mode = os.environ.get("CLD_DEBUG_MODE") == "1"
    if debug_mode:
        logging.basicConfig(
            level="DEBUG",
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    # In normal mode, no logging config = WARNING level only, no daemon.log
```

**daemon.py _spawn_background():**
- Remove log file redirect - background daemon doesn't need logging in normal mode
- The daemon.log file won't be created in normal mode

### Feature 5: Tiny Overlay Design (Windows Voice Typing Style)

**File:** `src/cld/ui/overlay.py`

Based on the screenshot comparison, implement:

**a) Darker drag bar area (line 273-287):**
```python
# Change drag handle background to slightly darker
self._drag_canvas.configure(bg="#1f1f1f")  # Darker than main bg
```

**b) Rounded corners (requires Win32 API):**
```python
def _apply_rounded_corners(self, radius: int = 8):
    """Apply rounded corners to window using Win32 API."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
        # DWM_WINDOW_CORNER_PREFERENCE = 5, DWMWCP_ROUND = 2
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        value = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass
```
Call after window creation in `_create_window()` and after switching to tiny mode.

**c) Brighter icons (line 349):**
```python
# Change idle mic color from #666666 to #999999 (brighter)
colors = {
    "ready": "#999999",  # Brighter gray
    "recording": self._green,
    "transcribing": self._amber,
    "error": self._red,
}
```

**d) Shadow effect (Win32 DWM):**
```python
def _enable_shadow(self):
    """Enable drop shadow using DWM."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
        # Enable non-client rendering to get shadow
        DWMWA_NCRENDERING_POLICY = 2
        value = ctypes.c_int(2)  # DWMNCRP_ENABLED
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_NCRENDERING_POLICY,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass
```

### Feature 6: Prevent Multiple Settings Windows

**File:** `src/cld/daemon_service.py`

The `_settings_dialog` instance variable already exists (line 84), but new dialogs are created each time. Fix by checking if existing dialog is visible:

```python
def _show_settings_dialog(self):
    """Show the full settings dialog."""
    if not _SETTINGS_AVAILABLE:
        return

    # Check if dialog already visible
    if self._settings_dialog and self._settings_dialog.is_visible():
        # Bring existing dialog to front
        if self._settings_dialog._window:
            self._settings_dialog._window.lift()
            self._settings_dialog._window.focus_force()
        return

    # Create new dialog
    parent = self._overlay.get_root() if self._overlay else None
    self._settings_dialog = SettingsDialog(
        parent=parent,
        config=self.config,
        on_save=self._on_config_change,
    )
    self._settings_dialog.show()
```

### Feature 9: Resizable Settings with Dynamic Scrollbar

**File:** `src/cld/ui/settings_dialog.py`

**a) Enable resizing (line 113):**
```python
self._window.resizable(True, True)
```

**b) Set minimum size:**
```python
self._window.minsize(380, 350)
```

**c) Dynamic scrollbar visibility and canvas width (lines 142-156):**
```python
def _on_window_resize(self, event=None):
    """Handle window resize - update canvas and scrollbar visibility."""
    if not self._window or not hasattr(self, '_canvas'):
        return

    # Update canvas window width
    new_width = self._window.winfo_width() - 56  # Account for padding + scrollbar
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

# Store references for resize handler
self._canvas = canvas
self._scrollbar = scrollbar
self._content = content
self._content_window = canvas.create_window(...)

# Bind resize event
self._window.bind("<Configure>", self._on_window_resize)
```

### Feature 10: Remove Hardware Detection from Settings

**File:** `src/cld/ui/settings_dialog.py`

Remove the hardware detection row in `_build_engine_section()` (lines 463-498):
- Remove the `hw_row` frame
- Remove the `_hw_label`
- Remove the `Detect` button
- Remove `_detect_hardware()` call on window open (line 223)
- Remove `_detect_hardware()` method (lines 626-638)

### Feature 11: Use cld_icon.png for About, Tray, and Thumbnail

**a) Tray icon - File:** `src/cld/ui/tray.py`

Replace programmatic icon generation with loading cld_icon.png:

```python
def _get_app_icon_path(self) -> Path:
    """Get path to app icon file."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent / "_internal"
    else:
        base = Path(__file__).parent.parent.parent.parent
    return base / "cld_icon.png"

def _load_app_icon(self) -> "Image.Image":
    """Load the app icon."""
    icon_path = self._get_app_icon_path()
    if icon_path.exists():
        img = Image.open(icon_path)
        # Resize to 32x32 for tray
        return img.resize((32, 32), Image.Resampling.LANCZOS)
    # Fallback to generated icon
    return self._create_icon_image(self._state)

# In _get_icon(), use static icon for all states:
def _get_icon(self, state: str) -> "Image.Image":
    if "app" not in self._icons:
        self._icons["app"] = self._load_app_icon()
    return self._icons["app"]
```

**b) About dialog icon - File:** `src/cld/daemon_service.py`

In `_show_about_dialog()`, add window icon and display logo:

```python
# After dialog creation, set window icon:
def _get_app_icon_path(self) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent / "_internal"
    else:
        base = Path(__file__).parent.parent.parent
    return base / "cld_icon.png"

icon_path = self._get_app_icon_path()
if icon_path.exists():
    from PIL import Image, ImageTk
    icon_img = Image.open(icon_path)
    icon_photo = ImageTk.PhotoImage(icon_img)
    dialog.iconphoto(True, icon_photo)

    # Also display in dialog content (64x64)
    logo_img = icon_img.resize((64, 64), Image.Resampling.LANCZOS)
    logo_photo = ImageTk.PhotoImage(logo_img)
    logo_label = tk.Label(content, image=logo_photo, bg=bg)
    logo_label.image = logo_photo  # Keep reference
    logo_label.pack(pady=(0, 12))
```

**c) App thumbnail (taskbar) - Files:** All dialog classes

Add `iconphoto()` call to model_dialog.py and settings_dialog.py after window creation:

```python
# In each dialog's show() method, after window creation:
icon_path = Path(__file__).parent.parent.parent.parent / "cld_icon.png"
if getattr(sys, "frozen", False):
    icon_path = Path(sys.executable).parent / "_internal" / "cld_icon.png"
if icon_path.exists():
    from PIL import Image, ImageTk
    icon_img = Image.open(icon_path)
    icon_photo = ImageTk.PhotoImage(icon_img)
    self._window.iconphoto(True, icon_photo)
    self._icon_photo = icon_photo  # Keep reference
```

## Testing Plan

### Pre-Implementation Baseline
- Run CLD.exe normally and document current behavior
- Take screenshots of current overlay, dialogs, tray

### Feature-by-Feature Testing

| Feature | Test Steps | Expected Result |
|---------|------------|-----------------|
| 1. Model setup text | Delete model, restart CLD | New line visible: "Works in any focused app..." |
| 2. No GPU detection | Open model setup dialog | No "GPU: Not detected" line, only CPU/RAM |
| 3. Manual download dark title | Click Manual Download button | Dark title bar (not white) |
| 4. Debug-only logging | Run CLD.exe normally, check %LOCALAPPDATA%\CLD | No daemon.log created |
| 4b. Debug logging | Run CLD.exe --debug | Console shows logs, no daemon.log |
| 5a. Darker drag bar | View tiny overlay | Drag handle area slightly darker |
| 5b. Rounded corners | View tiny overlay | Subtle rounded corners visible |
| 5c. Brighter icons | View tiny overlay in idle state | Mic icon brighter gray (#999 vs #666) |
| 5d. Shadow | View tiny overlay | Subtle drop shadow visible |
| 6. Single settings | Click Settings multiple times from tray | Only one window opens, subsequent clicks focus existing |
| 9a. Resizable settings | Drag settings window corner | Window resizes, content adjusts |
| 9b. Dynamic scrollbar | Make settings window very small | Scrollbar appears |
| 9c. No scrollbar when fits | Make settings window large | Scrollbar disappears |
| 10. No hardware in settings | Open Settings dialog | No "Hardware" row with "Detect" button |
| 11a. Tray icon | Look at system tray | CLD gradient icon visible |
| 11b. About icon | Click About CLD from tray | Dialog shows CLD icon in title bar and content |
| 11c. Taskbar thumbnail | Hover over CLD in taskbar | CLD icon visible |

### Integration Testing
1. Full workflow: Start CLD fresh, trigger model download, use dictation, check settings
2. Multiple sessions: Start/stop CLD multiple times, verify no daemon.log accumulation
3. State transitions: Record -> transcribe -> ready, verify overlay animations

## Implementation Order

Execute in this order to minimize conflicts:

1. **hardware.py** - Remove GPU detection (foundational change)
2. **model_dialog.py** - Add text, remove GPU display, fix dark title bar
3. **daemon.py + cli.py** - Debug-only logging
4. **settings_dialog.py** - Remove hardware, add resizable + scrollbar
5. **daemon_service.py** - Singleton settings, About dialog icon
6. **overlay.py** - Tiny mode design improvements
7. **tray.py** - Use cld_icon.png

## PyInstaller Considerations

After implementation, ensure `cld_icon.png` is bundled:

```
--add-data "cld_icon.png;."
```

Or copy to `_internal` folder in build script.

## Files to Copy for Icon

The `cld_icon.png` file needs to be accessible at runtime. Currently it's in the project root. For consistency with other assets:

- Keep in project root for source runs
- Bundle to `_internal/` for frozen exe (already handled by --add-data pattern)
