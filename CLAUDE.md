# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

CLD is a Windows GUI speech-to-text application forked from claude-stt. Features:
- Enhanced overlay UI with multi-mode states (tiny, recording, processing)
- System tray integration via pystray
- Push-to-talk and toggle mode voice dictation
- Local transcription via pywhispercpp with multilingual support
- Configurable activation key with scancode detection
- Privacy: All processing is local, audio never sent to cloud
- GPU acceleration via Vulkan (universal) or CPU fallback using GGML models

## Commands

```bash
# Install dependencies (uv preferred)
uv sync --python 3.12 --extra dev

# Run CLD in foreground with overlay
uv run python -m cld.daemon run --overlay

# Run tests
uv run python -m unittest discover -s tests

# Run single test
uv run python -m unittest tests.test_config

# Lint (ruff) - ALWAYS run after code changes
uv run ruff check src/

# Build standalone exe with PyInstaller (from D:\claudecli-dictate2, not OneDrive)
# CRITICAL: Must use Python 3.12 from venv - pywhispercpp pyd is compiled for 3.12
cd D:\claudecli-dictate2
.venv\Scripts\python.exe -m PyInstaller -y --onedir --windowed --name CLD ^
    --icon cld_icon.ico ^
    --add-data "sounds;sounds" ^
    --add-data "cld_icon.png;." ^
    --add-data "mic_256.png;." ^
    --add-data "C:/Program Files/Python312/tcl/tcl8.6;tcl/tcl8.6" ^
    --add-data "C:/Program Files/Python312/tcl/tk8.6;tcl/tk8.6" ^
    --add-data ".venv/Lib/site-packages/_sounddevice_data;_sounddevice_data" ^
    --add-binary ".venv/Lib/site-packages/_pywhispercpp.cp312-win_amd64.pyd;." ^
    --add-binary ".venv/Lib/site-packages/whisper.dll;." ^
    --add-binary ".venv/Lib/site-packages/ggml.dll;." ^
    --add-binary ".venv/Lib/site-packages/ggml-base.dll;." ^
    --add-binary ".venv/Lib/site-packages/ggml-cpu.dll;." ^
    --add-binary ".venv/Lib/site-packages/ggml-vulkan.dll;." ^
    --runtime-hook pyi_rth_numpy.py ^
    --runtime-hook pyi_rth_tcltk.py ^
    --runtime-hook pyi_rth_pywhispercpp.py ^
    --hidden-import pywhispercpp ^
    --hidden-import pywhispercpp.model ^
    src/cld/cli.py

# Compress with UPX (reduces ~429MB to ~67MB)
powershell.exe -ExecutionPolicy Bypass -File compress_upx.ps1

# Run exe with --debug flag to show console window for troubleshooting
dist/CLD/CLD.exe --debug daemon run --overlay
```

## CLI Reference

### Global Options

- `--version`, `-V` - Print version and exit (works in windowed exe via console allocation)
- `--debug` - Show console window for debugging (Windows only, forces foreground mode)

### Commands

#### `cld` (no arguments)

Starts daemon in background with overlay. This is the default behavior when double-clicking the exe.

#### `cld daemon run [--overlay] [--log-level LEVEL]`

Run daemon in foreground (blocking). Useful for development and debugging.

Options:
- `--overlay` - Show floating overlay UI
- `--log-level` - Set log level (DEBUG, INFO, WARNING, ERROR)

#### `cld daemon start [--background] [--overlay] [--log-level LEVEL]`

Start daemon.

Options:
- `--background` - Run in background (detached process)
- `--overlay` - Show floating overlay UI
- `--log-level` - Set log level

#### `cld daemon stop`

Stop running daemon by killing the process referenced in the PID file.

#### `cld daemon status`

Show daemon status (running/stopped, PID).

#### `cld setup [options]`

Run first-time setup wizard.

Options:
- `--skip-model-download` - Skip model download step
- `--skip-audio-test` - Skip microphone test
- `--skip-hotkey-test` - Skip hotkey test
- `--no-start` - Don't start daemon after setup completes

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

Output: `dist/CLD/` folder (~67MB with UPX compression, ~429MB uncompressed) with `CLD.exe` and `_internal/` directory containing Vulkan DLLs (ggml-vulkan.dll is 55MB)

Note: The `api-ms-win-crt-*.dll` files in the output are Windows Universal C Runtime (UCRT) libraries included by PyInstaller. These are already present on Windows 10+ and can be safely ignored during UPX compression (they're skipped anyway). Including them doesn't cause harm but adds ~2MB.

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

## GPU Acceleration

CLD uses pywhispercpp with the Vulkan backend for universal GPU acceleration. See `docs/audio-gpu-implementation-plan.md` for full details.

### Why Vulkan Over CUDA

CLD chose Vulkan as the GPU backend for two key reasons:

1. Universal GPU Support: Vulkan works with all GPU vendors (NVIDIA, AMD, Intel) including integrated graphics. CUDA only supports NVIDIA GPUs and requires architecture-specific builds (one for RTX 40-series, another for RTX 30-series, etc.).

2. Distribution Size: Vulkan adds ~100-150MB to the build. CUDA adds ~600MB per GPU architecture family due to cuBLAS libraries (cublasLt64_13.dll alone is 449MB).

| Backend | Size Impact | GPU Support |
|---------|-------------|-------------|
| Vulkan | ~100-150 MB | NVIDIA, AMD, Intel (discrete + integrated) |
| CUDA | ~600 MB per arch | NVIDIA only (specific architecture) |

While CUDA may be slightly faster on NVIDIA GPUs, Vulkan provides 80-95% of that performance with universal hardware support at a fraction of the distribution size.

### Building pywhispercpp with Vulkan

All build files are consolidated in `D:\claudecli-dictate2\`:

| Folder | Contents |
|--------|----------|
| `pywhispercpp-src/` | pywhispercpp source code with modified main.cpp for GPU device selection |
| `build-scripts/` | Build scripts (`build_vulkan_py312.bat`) |
| `whisper-vulkan-prebuilt/` | Backup pre-built Vulkan DLLs from jerryshell/whisper.cpp-windows-vulkan-bin |
| `.venv/` | Python 3.12 venv with Vulkan-enabled pywhispercpp installed |

Build requirements:
- Visual Studio 2022 Build Tools (C++ compiler and CMake)
- Python 3.12 (must exclude Python 3.14 from PATH during build)
- Vulkan SDK (C:\VulkanSDK\1.4.x) - Required for compiling ggml-vulkan.dll with Vulkan shaders
- GPU drivers with Vulkan support (standard on all modern drivers)

Why Vulkan SDK is needed: The SDK provides the Vulkan headers and libraries needed to compile the ggml-vulkan.dll (55MB) which contains the GPU compute shaders. Without the SDK, you cannot build from source - you would need pre-built binaries.

Build script location: `D:\claudecli-dictate2\build-scripts\build_vulkan_py312.bat`

```batch
@echo off
REM Build pywhispercpp with Vulkan backend
REM Run from Developer Command Prompt with Visual Studio Build Tools

set VENV=D:\claudecli-dictate2\.venv
set PYWHISPERCPP_SRC=D:\claudecli-dictate2\pywhispercpp-src
set PATH=%VENV%\Scripts;C:\Program Files\Python312;%PATH%

cd /d %PYWHISPERCPP_SRC%
rmdir /s /q build 2>nul

set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER
python -m pip install --no-cache-dir . --force-reinstall

REM Copy Vulkan DLLs to venv
copy "%PYWHISPERCPP_SRC%\whisper.cpp\*.dll" "%VENV%\Lib\site-packages\"
```

Key files produced by the build:
- `_pywhispercpp.cp312-win_amd64.pyd` (330KB) - Python extension with GPU device selection
- `ggml-vulkan.dll` (55MB) - Vulkan compute backend with shaders
- `whisper.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll` - Core whisper.cpp libraries

The pywhispercpp source at `pywhispercpp-src/` includes a modified `src/main.cpp` that adds `whisper_init_from_file_with_params` function to expose GPU device selection via `use_gpu` and `gpu_device` parameters

### GPU Backend Detection

pywhispercpp uses GPU automatically when available. Detection:
```python
import _pywhispercpp as pw
info = pw.whisper_print_system_info()
has_vulkan = "Vulkan" in info  # Preferred (universal)
has_cuda = "CUDA" in info       # Fallback (NVIDIA-only)
```

### CUDA Build (Legacy/Optional)

For NVIDIA-only deployments requiring maximum performance, CUDA builds are still supported but not recommended for general distribution. See `docs/audio-gpu-implementation-plan.md` for CUDA build instructions.

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
- `hardware.py` - CPU/GPU detection for model recommendations and Vulkan/CUDA support
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
    "force_cpu": false,
    "gpu_device": -1
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

Engine settings:
- `force_cpu`: Set to `true` to disable GPU acceleration and use CPU only
- `gpu_device`: GPU index to use (-1 = auto-select, 0/1/2 = specific GPU)

CRITICAL: Passing `gpu_device=-1` directly to pywhispercpp falls back to CPU, not auto-select! The engine_factory.py handles this by mapping -1 to 0 when GPU is available:
```python
if gpu_device == -1 and is_gpu_supported():
    gpu_device = 0  # First discrete GPU in Vulkan order
```

### Whisper Models (GGML, CPU-only)

CLD uses pywhispercpp for speech recognition with full multilingual support. All models run on CPU using GGML format for efficient inference.

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

On first run or when the configured model is missing, CLD shows a model setup dialog. Models are stored in `%LOCALAPPDATA%\CLD\models\` as single GGML .bin files.

Startup flow:
1. Check if configured model exists in `%LOCALAPPDATA%\CLD\models\`
2. If missing, show ModelSetupDialog (GUI) with model selection and download
3. If GUI fails, print manual download instructions to console
4. User can download or exit - dialog cannot be dismissed without action

Model manager features:
- CPU capability detection (SSE4.1, AVX, AVX2) for compatibility warnings
- Hardware compatibility checks (RAM, CPU cores) with warnings for larger models
- Download progress tracking
- MD5 hash verification for file integrity (stored in `models.json`)
- Manual download URLs if automatic download fails

Model integrity verification:
- On download: MD5 hash computed and stored in `%LOCALAPPDATA%\CLD\models\models.json`
- On startup: File hash verified against stored hash to detect corruption
- No hardcoded hashes - works with any model version from HuggingFace

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
├── dist/                      # PyInstaller output (CLD.exe)
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
