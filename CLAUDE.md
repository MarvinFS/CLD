# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

CLD2 is a Windows GUI speech-to-text application forked from claude-stt. Features:
- Enhanced overlay UI with multi-mode states (tiny, recording, processing)
- System tray integration via pystray
- Push-to-talk and toggle mode voice dictation
- Local transcription via pywhispercpp with multilingual support
- Configurable activation key with scancode detection
- Privacy: All processing is local, audio never sent to cloud
- CPU-only inference using GGML models

## Commands

```bash
# Install dependencies (uv preferred)
uv sync --python 3.12 --extra dev

# Run CLD2 in foreground with overlay
uv run python -m cld.daemon run --overlay

# Run tests
uv run python -m unittest discover -s tests

# Run single test
uv run python -m unittest tests.test_config

# Lint (ruff) - ALWAYS run after code changes
uv run ruff check src/

# Build standalone exe with PyInstaller
# CRITICAL: Must use "uv run" to use Python 3.12 from venv - system Python won't work!
uv run pyinstaller -y --onedir --windowed --name CLD2 ^
    --icon cld_icon.ico ^
    --add-data "sounds;sounds" ^
    --add-data "cld_icon.png;." ^
    --add-data "mic_256.png;." ^
    --add-data "C:/Python314/tcl/tcl8.6;tcl/tcl8.6" ^
    --add-data "C:/Python314/tcl/tk8.6;tcl/tk8.6" ^
    --add-data ".venv/Lib/site-packages/_sounddevice_data;_sounddevice_data" ^
    --runtime-hook pyi_rth_numpy.py ^
    --runtime-hook pyi_rth_tcltk.py ^
    --hidden-import pywhispercpp ^
    src/cld/cli.py

# Run exe with --debug flag to show console window for troubleshooting
dist/CLD2/CLD2.exe --debug daemon run --overlay
```

## PyInstaller Build

The project includes runtime hooks for PyInstaller compilation:

- `pyi_rth_numpy.py` - Fixes numpy.fft circular import in frozen exe
- `pyi_rth_tcltk.py` - Sets TCL_LIBRARY/TK_LIBRARY paths for tkinter

Key considerations:
- Use `--onedir` not `--onefile` to avoid _MEI temp directory cleanup conflicts with daemon spawning
- MUST use `uv run pyinstaller` to use Python 3.12 from venv - pywhispercpp pyd is compiled for 3.12, system Python 3.14 won't work!
- CRITICAL: Build in D:\claudecli-dictate2 (not OneDrive folder) to avoid file locking during compilation
- Tcl/Tk data must be bundled separately with `--add-data`
- sounddevice requires `--add-data ".venv/Lib/site-packages/_sounddevice_data;_sounddevice_data"`
- frozen exe detection: `getattr(sys, 'frozen', False)` and `sys._MEIPASS`
- Subprocess spawning must use exe directly, not `python -m module`
- pystray callbacks run in background thread; queue tkinter operations via queue.Queue
- Sound/data files: use `Path(sys.executable).parent / "_internal" / "sounds"` in frozen exe
- --debug flag: allocate console with AllocConsole() BEFORE imports, redirect stdout to CONOUT$
- --debug mode forces foreground execution so console stays open

Output: `dist/CLD2/` folder (~80MB with UPX compression) with `CLD2.exe` and `_internal/` directory

### PyInstaller pywhispercpp Requirements

pywhispercpp has native C++ extensions that must be bundled:
- `_pywhispercpp.cp312-win_amd64.pyd` - Python extension module
- `whisper-*.dll` - whisper.cpp native library

These are in `.venv/Lib/site-packages/` and must be added to the spec file:
```python
binaries=[
    ('.venv/Lib/site-packages/_pywhispercpp.cp312-win_amd64.pyd', '.'),
    ('.venv/Lib/site-packages/whisper-*.dll', '.'),
],
```

CRITICAL: Python version must match between venv and PyInstaller. The pyd file is compiled for a specific Python version (e.g., cp312 = Python 3.12). If your venv uses Python 3.12 but system Python is 3.14, the exe will crash silently. Always run `uv run pyinstaller` to use the venv's Python.

Runtime hook `pyi_rth_pywhispercpp.py` adds DLL search directories so the native extension can find whisper.dll at runtime

## Architecture

Daemon-based design: A background process (STTDaemon) runs continuously, listening for hotkey events and coordinating audio capture, transcription, and text output.

### Core Components

- `daemon.py` - Process management (start/stop/status, PID file handling, background spawning)
- `daemon_service.py` - Runtime orchestration (STTDaemon class coordinates all components)
- `hotkey.py` - Global hotkey listener using pynput (supports toggle and push-to-talk modes)
- `recorder.py` - Audio capture via sounddevice
- `engines/` - STT engine implementations (Whisper for multilingual support)
- `keyboard.py` - Text output via keyboard injection or clipboard fallback
- `window.py` - Platform-specific window tracking to restore focus after transcription
- `config.py` - JSON-based config stored in %LOCALAPPDATA%\CLD\
- `model_manager.py` - Whisper model download, validation, and caching in %LOCALAPPDATA%\CLD\models\

### UI Components (src/cld/ui/)

- `overlay.py` - Multi-mode floating overlay (tiny, recording, processing states)
- `tray.py` - System tray integration with pystray
- `settings_popup.py` - Quick settings popup from overlay gear button
- `settings_dialog.py` - Full settings dialog from tray menu
- `key_scanner.py` - Activation key capture using keyboard library
- `hardware.py` - CPU detection for model recommendations
- `model_dialog.py` - Model download/setup dialog shown when model is missing

### Configuration

Settings stored in JSON format at `%LOCALAPPDATA%\CLD\settings.json`:

```json
{
  "version": 1,
  "activation": {
    "key": "alt_gr",
    "scancode": 541,
    "mode": "toggle",
    "enabled": true
  },
  "engine": {
    "type": "whisper",
    "whisper_model": "medium-q5_0",
    "device": "cpu"
  },
  "features": {
    "auto_punctuation": true,
    "filter_profanity": false,
    "voice_typing_launcher": true
  },
  "output": {
    "mode": "auto",
    "sound_effects": true
  },
  "recording": {
    "max_seconds": 300,
    "sample_rate": 16000
  },
  "ui": {
    "overlay_position": [960, 1000],
    "show_on_startup": true
  }
}
```

### Whisper Models (GGML, CPU-only)

CLD2 uses pywhispercpp for speech recognition with full multilingual support. All models run on CPU using GGML format for efficient inference.

CRITICAL: When calling transcribe(), always set `translate=False` and `language="auto"` to keep original language:
```python
segments = model.transcribe(audio, translate=False, language="auto")
```
Without `translate=False`, pywhispercpp may translate non-English speech to English instead of transcribing.

Model comparison - quantization explained:

| Model | Parameters | Precision | Size | RAM | Accuracy |
|-------|------------|-----------|------|-----|----------|
| small | 244M | FP16 (full) | 488MB | ~1GB | Good |
| medium-q5_0 | 769M | 5-bit (quantized) | 539MB | ~2GB | Very Good |
| medium | 769M | FP16 (full) | 1.5GB | ~3GB | Excellent |

Key insight: medium-q5_0 has 3x more parameters than small despite similar file size. Quantization compresses weights from 16-bit to 5-bit, dramatically reducing size while preserving most accuracy. medium-q5_0 is the best choice for most users.

Hardware detection runs automatically to recommend the best model for your system.

GGML model download URLs:
- https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
- https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium-q5_0.bin
- https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin

### Model Installation System

On first run or when the configured model is missing, CLD2 shows a model setup dialog. Models are stored in `%LOCALAPPDATA%\CLD\models\` as single GGML .bin files.

Startup flow:
1. Check if configured model exists in `%LOCALAPPDATA%\CLD\models\`
2. If missing, show ModelSetupDialog (GUI) with model selection and download
3. If GUI fails, print manual download instructions to console
4. User can download or exit - dialog cannot be dismissed without action

Model manager features:
- CPU capability detection (SSE4.1, AVX, AVX2) for compatibility warnings
- Hardware compatibility checks (RAM, CPU cores) with warnings for larger models
- Download progress tracking
- Model validation after download
- Manual download URLs if automatic download fails

The dialog shows:
- Model dropdown with size and requirements for each model
- Detected CPU features (SSE4.1, AVX, AVX2)
- Compatibility warnings if hardware may struggle with selected model
- Progress bar during download
- Manual download URLs on error

### Recording Flow

```
Hotkey press -> AudioRecorder.start() -> [user speaks] -> Hotkey release
    -> AudioRecorder.stop() -> Engine.transcribe() -> output_text()
```

### Threading Model

Transcription runs in a one-shot daemon thread spawned per recording. A simple `_is_transcribing` busy flag prevents concurrent transcriptions and blocks new recordings while transcription is in progress.

Toggle mode includes a 300ms debounce to prevent rapid key presses from triggering multiple start/stop cycles.

Critical threading patterns:
- tkinter must run in main thread for Windows mouse events
- pystray uses run_detached() so it doesn't block tkinter mainloop
- Queue-based state updates for thread-safe overlay communication
- RLock for nested callbacks to avoid deadlocks
- State updates use `queue.Queue` for thread-safe communication (not `after()`)
- Main loop calls `process_queue()` to apply pending state changes

### Overlay State Machine

```
TINY (idle) --[hotkey_press]--> RECORDING --[hotkey_release]--> PROCESSING --[complete]--> TINY
     |                              |
     |                              +--[no audio]---> TINY
     +--[gear_click]--> Settings popup (stays in TINY)
```

Overlay features:
- Floating dark-themed window with timer, waveform bars, status text
- Draggable (left-click), closeable (right-click)
- macOS-style animated waveform bars during recording
- States: ready, recording, transcribing, error

## Windows-Specific Patterns

Critical patterns from docs/windows-tray-app-patterns.md:

1. tkinter mainloop runs in main thread
2. pystray uses run_detached() for background operation
3. Modal dialogs temporarily disable parent's topmost
4. Config files use LOCALAPPDATA to avoid OneDrive sync issues
5. All UI updates happen via after() polling or Queue from main thread
6. Use RLock not Lock to avoid deadlocks in nested calls
7. Don't use DETACHED_PROCESS if you need pynput global hotkeys (no message pump)
8. Handle Unicode print errors with try/except and ASCII fallback
9. Handle Alt_Gr separately from Alt_L/Alt_R in hotkey normalization
10. Use hex colors, not platform-specific color names like "systemTransparent"
11. Dark title bars on Windows 10/11 require DwmSetWindowAttribute with DWMWA_USE_IMMERSIVE_DARK_MODE (20) - call after window.update() to ensure HWND exists, use GetAncestor(winfo_id(), GA_ROOT) for correct HWND
12. Use ttk style.theme_use("clam") for dark styling - Windows native theme ignores custom colors
13. For ttk.Combobox dropdown styling, use window.option_add("*TCombobox*Listbox.background", color)
14. PyInstaller: bundle Tcl/Tk data with --add-data and runtime hook for TCL_LIBRARY/TK_LIBRARY
15. PyInstaller: fix numpy circular import with runtime hook pre-importing numpy.fft._pocketfft_umath
16. PyInstaller: pystray callbacks run in background thread; queue tkinter operations via queue.Queue
17. PyInstaller: use --onedir not --onefile to avoid _MEI temp cleanup conflicts with daemon spawn
18. PyInstaller: MUST use "uv run pyinstaller" - venv is Python 3.12, pywhispercpp pyd won't load with system Python 3.14
19. PyInstaller: build on local drive (not OneDrive/synced folders) to avoid file locking
20. PyInstaller: sound/data files use Path(sys.executable).parent / "_internal" / "folder" for onedir
21. PyInstaller --debug: allocate console with AllocConsole() BEFORE imports, redirect stdout to CONOUT$
22. Don't create separate tk.Tk() in threads (causes freezes) - use Toplevel() with existing root
23. Map Windows VK codes to characters in pynput hotkey normalization (when Ctrl/Alt is held, pynput sends VK codes like <187> instead of characters like '=')
24. Don't use Shift modifier with symbol keys for hotkeys (Shift changes the character: Shift+= sends '+'); use Ctrl/Alt instead
25. Modal dialogs with grab_set() have issues with BooleanVar checkboxes - move such controls to normal Toplevel windows
26. Overlay state mapping: when _print_status() maps messages to overlay states, ensure ALL status messages have corresponding state transitions (e.g., "Too short" must map to "ready" state or UI appears stuck)
27. Specific alt key support: key_scanner preserves alt_gr/alt_l/alt_r variants; hotkey.py uses _use_specific_alt flag to only normalize when config uses generic "alt"
28. pynput global hotkey receives ALL keyboard events by design - don't log individual keystrokes for privacy; Windows RegisterHotKey() can't handle modifier-only hotkeys like "Alt Gr"
29. Overlay mode switching protection: use _mode_switching flag to prevent concurrent animations corrupting UI from rapid clicks
30. UI button debounce: add timestamp check (e.g., 500ms) to prevent rapid clicks creating multiple dialogs/popups

### Windows-Specific Issues (from claude-stt)

- pynput global hotkeys require a message pump; `DETACHED_PROCESS` has none, so hotkeys won't work without a GUI or visible console
- Alt_Gr key needs explicit handling in `_normalize_key()` separate from alt_l/alt_r
- Unicode symbols fail on Windows cp1251 encoding; write status files BEFORE print and use ASCII fallback
- Color name `"systemTransparent"` is macOS-only; use hex colors
- When overlay is enabled, `DETACHED_PROCESS` is not used (tkinter provides message pump for pynput)

## File Structure

```
D:\claudecli-dictate2\
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── pyi_rth_numpy.py           # PyInstaller runtime hook for numpy
├── pyi_rth_tcltk.py           # PyInstaller runtime hook for Tcl/Tk
├── sounds/                    # Sound effects
├── dist/                      # PyInstaller output (CLD2.exe)
├── docs/
│   ├── original-plugin-analysis.md
│   ├── phase2-implementation-plan.md
│   └── windows-tray-app-patterns.md  # Essential Windows GUI patterns
├── src/cld/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py              # JSON config + LOCALAPPDATA
│   ├── daemon.py
│   ├── daemon_service.py
│   ├── errors.py
│   ├── hotkey.py
│   ├── keyboard.py
│   ├── recorder.py
│   ├── sounds.py
│   ├── window.py
│   ├── engine_factory.py
│   ├── model_manager.py       # Model download/validation/caching
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── moonshine.py
│   │   └── whisper.py
│   └── ui/
│       ├── __init__.py
│       ├── overlay.py         # Multi-mode overlay
│       ├── tray.py            # System tray integration
│       ├── settings_popup.py  # Quick settings popup
│       ├── settings_dialog.py # Full settings dialog
│       ├── model_dialog.py    # Model setup/download dialog
│       ├── key_scanner.py     # Activation key capture
│       └── hardware.py        # CPU capability detection
└── tests/
```

## Troubleshooting

- Model not found on startup: The model setup dialog will appear. Select a model and click Download, or download manually from the GGML URLs shown.
- Download fails: Check internet connection. Manual download URLs are shown in the dialog. Download the .bin file to `%LOCALAPPDATA%\CLD\models\`
- Model too slow: Check CPU features in the dialog. AVX2 is recommended for medium models. Try the small model if AVX2 is missing.
- Out of memory: Try a smaller model. medium-q5_0 needs ~1.5GB RAM, medium needs ~3GB.
- Text not appearing: Plugin may fall back to clipboard mode on Windows. Check output.mode in config.
- Wrong window receives text: Ensure target window is focused before pressing hotkey.
- Hotkey conflict: Change activation key via settings if alt_gr conflicts with another app.

Exe-specific issues:
- Overlay not showing in exe: Tcl/Tk data files missing. Rebuild with --add-data for tcl8.6/tk8.6 and runtime hook.
- Settings button does nothing: pystray callbacks run in background thread. Check queue-based callback pattern in daemon_service.py.
- Exe does nothing when double-clicked: Check cli.py auto-start logic. Should run `daemon start --background` with no args.
- Background spawn fails: Frozen exe can't use `python -m module`. Check daemon.py for `getattr(sys, 'frozen', False)` detection.
- Sounds not playing: Check sounds.py path resolution - must use `Path(sys.executable).parent / "_internal" / "sounds"` for frozen exe.
- _MEI temp directory warning: Using --onefile causes cleanup conflicts. Switch to --onedir.
- Debug console empty/closes: Must allocate console BEFORE imports with AllocConsole() and redirect stdout to CONOUT$.
- Dialogs freeze app: Don't create separate tk.Tk() in background threads. Use Toplevel() with main root instead.

## Version Bumps

Update version in:
- `pyproject.toml`
- `src/cld/__init__.py`

## Origin

Forked from [jarrodwatts/claude-stt](https://github.com/jarrodwatts/claude-stt) - a Claude Code plugin for speech-to-text input.
