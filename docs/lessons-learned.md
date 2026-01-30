# CLD Migration Lessons Learned

## pywhispercpp API

### Translation vs Transcription
pywhispercpp defaults may translate to English. Always explicitly set:
```python
segments = model.transcribe(audio, translate=False, language="auto")
```
- `translate=False` - keeps original language (no English translation)
- `language="auto"` - enables automatic language detection

### Model Constructor
```python
Model(model_path, n_threads=N)  # n_threads parameter is correct
```

### Transcribe Return Value
Returns iterable of segments with `.text` attribute:
```python
text = " ".join(s.text.strip() for s in segments)
```

## GGML Model Management

### Single File Structure
GGML models are single `.bin` files, not directories:
```
%LOCALAPPDATA%\CLD\models\ggml-medium-q5_0.bin
```
Not like faster-whisper which has folders with model.bin, config.json, etc.

### Download URLs
Direct download from HuggingFace:
```
https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin
```

### Available Models
| Model | File | Size |
|-------|------|------|
| small | ggml-small.bin | 488MB |
| medium-q5_0 | ggml-medium-q5_0.bin | 539MB |
| medium | ggml-medium.bin | 1.5GB |

## UI/Config Integration

### Model Dialog Must Save Config
After successful download, save selected model to config:
```python
from cld.config import Config
config = Config.load()
config.engine.whisper_model = self._model_name
config.save()
```

### Daemon Must Reload After Dialog
After model setup dialog completes, reload config and reinitialize engine:
```python
if self._show_model_setup_dialog(model_manager):
    self.config = Config.load()
    model_name = self.config.engine.whisper_model
    self._engine = build_engine(self.config)
```

### Default Model Consistency
Ensure default model is consistent across:
- config.py (EngineConfig default)
- hardware.py (_get_recommendations fallback)
- model_dialog.py (_detect_hardware fallback)

All should use `"medium-q5_0"` as default.

## Thread Safety

### Double-Checked Locking for Model Loading
```python
def __init__(self):
    self._model_lock = threading.Lock()

def load_model(self):
    if self._model is not None:  # Fast path
        return True

    with self._model_lock:
        if self._model is not None:  # Check again inside lock
            return True
        # ... load model ...
```

## ModelManager Requirements

### Required Methods
ModelManager must implement `update_model()` for UI dialogs:
```python
def update_model(self, model_name, progress_callback=None):
    model_path = self._get_model_path(model_name)
    if model_path.exists():
        model_path.unlink()
    return self.download_model(model_name, progress_callback)
```

## Path Management

### Keep Original Paths
Don't change app data paths when forking - keeps compatibility:
- Config: `%LOCALAPPDATA%\CLD\settings.json`
- Models: `%LOCALAPPDATA%\CLD\models\`

### Centralize Path Logic
Both whisper.py and model_manager.py define `get_models_dir()` - keep them in sync.

## Build Considerations

### PyInstaller Hidden Imports
```
--hidden-import pywhispercpp
```

### CPU-Only Operation
pywhispercpp/whisper.cpp is CPU-only (no CUDA). Remove GPU/VRAM references from UI.

## GPU Support (Vulkan)

### GPU Device Enumeration
Enumerate all GPUs via Windows WMI (vendor-agnostic):
```python
def enumerate_gpus() -> List[GPUDeviceInfo]:
    result = subprocess.run(
        ["wmic", "path", "win32_VideoController", "get",
         "Name,AdapterRAM", "/format:csv"],
        capture_output=True, text=True, timeout=5,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    # Parse CSV: Node,AdapterRAM,Name
    # Works with NVIDIA, AMD, and Intel GPUs
```

Note: WMI is preferred over nvidia-smi because it works with all GPU vendors (NVIDIA, AMD, Intel) which is important since CLD uses Vulkan for universal GPU acceleration.

### Config Device Settings
```python
@dataclass
class EngineConfig:
    device: str = "auto"      # "auto", "cpu", or "gpu"
    gpu_device: int = -1      # -1=auto-select, 0=first GPU, 1=second GPU
```

### Settings Dialog GPU UI
- Force CPU Only checkbox disables GPU dropdown when checked
- GPU Device dropdown shows "Auto-select" + enumerated GPUs
- Restart warning appears when GPU settings change from original values
- Save both `device` and `gpu_device` to config

## Config File Robustness

### Retry Logic for Windows File Locking
Windows can lock files briefly during save operations. Use exponential backoff:
```python
max_attempts = 3
delays = [0.1, 0.2, 0.4]  # Exponential backoff
for attempt in range(max_attempts):
    try:
        os.replace(temp_file, config_path)
        return True
    except (PermissionError, OSError) as e:
        if attempt < max_attempts - 1:
            time.sleep(delays[attempt])
        else:
            raise
```

## PyInstaller Windowed Mode

### --version in Windowed Exe
Windowed mode has no console. Allocate one before printing:
```python
def _early_version_check():
    if "--version" in sys.argv:
        if getattr(sys, 'frozen', False) and sys.platform == 'win32':
            ctypes.windll.kernel32.AllocConsole()
            sys.stdout = open('CONOUT$', 'w', encoding='utf-8')
        print(__version__)
        sys.exit(0)
```
Call this BEFORE imports to ensure early exit.

### api-ms-win-crt DLLs
These Windows UCRT libraries (~2MB) are included by PyInstaller but already present on Windows 10+. Safe to ignore in UPX compression warnings.

## Transcription Robustness

### Timeout for Long Audio
Wrap transcription in ThreadPoolExecutor with timeout:
```python
with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(self._transcribe_internal, audio, sample_rate)
    result = future.result(timeout=self._timeout)  # Default 120s
```

### Feedback Sounds
Play appropriate sounds for ALL outcomes:
- Success: no sound (text appears)
- Output failed: error sound
- No speech detected: warning sound
- Recording too short: warning sound

## Code Quality Patterns

### Extract Magic Numbers
Replace magic numbers with named constants at module level:
```python
# In hotkey.py
TOGGLE_DEBOUNCE_SECONDS = 0.3

# In overlay.py
ANIMATION_FRAME_MS = 33  # ~30 FPS
```

### Stop Idle Animations
Animation loops should exit early when idle to save CPU:
```python
def _animate(self):
    # Skip animation when idle - save CPU
    if self._state not in ("recording", "transcribing"):
        return
    # ... animation logic ...
    self._root.after(ANIMATION_FRAME_MS, self._animate)
```
Animation restarts automatically when state changes (set_state calls _animate).

### Model Download Hash Verification
Verify SHA256 hash after download for security:
```python
MODEL_HASHES = {
    "small": "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
    # ... other models
}

def _verify_hash(self, file_path, model_name):
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest() == MODEL_HASHES.get(model_name)
```

### Exception Logging Levels
- DEBUG: Expected failures for optional features (GPU detection, window icon)
- WARNING: Degrades UX but doesn't break core (icon loading, focus fallback)
- ERROR: Prevents core functionality (model loading, config parsing)

### Thread-Safe Global Variables
For cross-thread communication (like audio level visualization):
```python
_current_level: float = 0.0
_level_lock = threading.Lock()

def callback():
    global _current_level
    with _level_lock:
        _current_level = new_value

def get_level():
    with _level_lock:
        return _current_level
```

## Pre-roll Buffer for Audio Recording

### Problem
When users press the hotkey and immediately start speaking, the first 50-100ms of audio is lost due to:
- Hotkey detection latency
- Audio stream initialization time
- First buffer fill delay

This causes the first 1-2 letters/syllables to be cut off (e.g., "НЕ подожди" → "е подожди").

### Solution
Implement a pre-roll buffer that continuously captures audio even before recording starts:

```python
# In RecorderConfig
preroll_ms: int = 300  # 300ms pre-roll buffer

# In AudioRecorder.__init__
preroll_chunks = int(preroll_ms * sample_rate / 1000 / blocksize)
self._preroll_buffer: Deque[np.ndarray] = deque(maxlen=preroll_chunks)

# prime() starts stream early, callback fills pre-roll when not recording
# start() copies pre-roll buffer to beginning of recording
# stop() keeps stream running for next pre-roll
# shutdown() fully stops stream
```

### Key Methods
- `prime()` - Call at daemon startup to start pre-roll capture
- `start()` - Includes pre-roll buffer in recording
- `stop()` - Returns audio but keeps stream running
- `shutdown()` - Fully stops stream (call on daemon exit)

## Clipboard Fallback When No Window Focused

### Problem
When no application window is focused (e.g., desktop active, all windows minimized), text injection fails silently because there's no target window.

### Root Cause
Windows `GetForegroundWindow()` returns a valid handle even for the desktop (Progman, WorkerW, Shell_TrayWnd). These windows exist and can receive focus, but they don't accept text input. So `window_info` was not None, but typing went nowhere.

### Solution - Part 1: Desktop Detection (window.py)
Detect desktop/shell windows and return None so clipboard fallback triggers:

```python
_DESKTOP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd"}

def _get_window_class(hwnd: int) -> Optional[str]:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value

def _is_desktop_window(hwnd: int) -> bool:
    return _get_window_class(hwnd) in _DESKTOP_CLASSES

def get_active_window() -> Optional[WindowInfo]:
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        if _is_desktop_window(hwnd):
            return None  # Triggers clipboard fallback
        return WindowInfo(window_id=str(hwnd))
```

### Solution - Part 2: Clipboard Check Fix (keyboard.py)
The `pyperclip.is_available()` check gives false negatives on Windows. Remove it:

```python
# BAD - gives false negatives on Windows
if hasattr(pyperclip, "is_available") and not pyperclip.is_available():
    return False  # This incorrectly fails on Windows!

# GOOD - just try to copy, let exception handler catch real failures
pyperclip.copy(text)
```

### Solution - Part 3: Explicit None Check (keyboard.py)
In `_output_via_injection()`, check for `window_info is None` BEFORE attempting to type:

```python
# If no window was captured, fall back to clipboard
if window_info is None:
    _logger.info("No target window captured; using clipboard")
    return _output_via_clipboard(text, config)

# Then check focus restore
if not restore_focus(window_info):
    _logger.warning("Focus restore failed; falling back to clipboard")
    return _output_via_clipboard(text, config)

# Only then type
kb.type(text)
```

## Translate to English Setting

### Implementation
Add `translate_to_english` boolean to EngineConfig, pass through engine_factory to WhisperEngine, use in transcribe():

```python
# config.py
translate_to_english: bool = False

# whisper.py
segments = self._model.transcribe(audio, translate=self.translate_to_english, language="auto")
```

### UI
Add checkbox in Settings dialog STT Engine section. Save to config on dialog close.

## Development Location

**CRITICAL**: All code changes must be made in `D:\claudecli-dictate2` ONLY. The OneDrive folder (`D:\OneDrive - NoWay Inc\APPS\claudecli-dictate\`) is a stale copy that causes confusion. Never modify code there.

## pywhispercpp Vulkan Build Infrastructure

### Source Location
All build files consolidated in `D:\claudecli-dictate2\`:
- `pywhispercpp-src/` - pywhispercpp source with GPU device selection modifications
- `build-scripts/build_vulkan_py312.bat` - Main Vulkan build script
- `build-scripts/patches/` - Documentation of source modifications

### Build Requirements
- Visual Studio 2022 Build Tools (C++ compiler and CMake)
- Python 3.12 (CRITICAL: exclude Python 3.14 from PATH - CMake finds wrong Python otherwise)
- Vulkan SDK (C:\VulkanSDK\1.4.x) - Required for compiling ggml-vulkan.dll with GPU shaders
- GPU drivers with Vulkan support

### Critical Build Lessons

**Python Version Mismatch**: CMake/pybind11 pick Python from Windows registry. If system has Python 3.14 but venv uses 3.12, build succeeds but runtime crashes silently. Solution:
```batch
set PATH=%VENV%\Scripts;C:\Program Files\Python312;%PATH%
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER
```

**Vulkan SDK is Required for Build**: Cannot build ggml-vulkan.dll without the SDK. CMake error: "Could NOT find Vulkan (missing: Vulkan_LIBRARY Vulkan_INCLUDE_DIR glslc)". The glslc shader compiler only comes from the SDK (~2GB from vulkan.lunarg.com).

**No Vulkan SDK for Runtime**: Once built, the DLLs only need standard GPU drivers with Vulkan support. Users don't need the SDK installed.

**GPU Device Selection Not in Upstream**: Standard pywhispercpp uses `whisper_init_from_file()` which doesn't expose GPU parameters. CLD modifications add `whisper_init_from_file_with_params_wrapper()` in `src/main.cpp` exposing `use_gpu` and `gpu_device`.

### Source Modifications (from upstream pywhispercpp)

**src/main.cpp** - Added after line 80:
```cpp
struct whisper_context_wrapper whisper_init_from_file_with_params_wrapper(
    const char * path_model,
    bool use_gpu,
    int gpu_device
){
    whisper_context_params params = whisper_context_default_params();
    params.use_gpu = use_gpu;
    params.gpu_device = gpu_device;
    struct whisper_context * ctx = whisper_init_from_file_with_params(path_model, params);
    struct whisper_context_wrapper ctw_w;
    ctw_w.ptr = ctx;
    return ctw_w;
}
```

**pywhispercpp/model.py** - Added parameters to `__init__`:
```python
def __init__(self, ..., use_gpu: bool = True, gpu_device: int = 0, ...):
    self.use_gpu = use_gpu
    self.gpu_device = gpu_device
```

Modified `_init_model()` to use new function:
```python
if hasattr(pw, 'whisper_init_from_file_with_params'):
    self._ctx = pw.whisper_init_from_file_with_params(
        self.model_path, self.use_gpu, self.gpu_device
    )
else:
    self._ctx = pw.whisper_init_from_file(self.model_path)
```

### Build Output Files
Key files in `.venv/Lib/site-packages/`:
- `_pywhispercpp.cp312-win_amd64.pyd` (~330KB) - Python extension with GPU params
- `ggml-vulkan.dll` (~55MB) - Vulkan compute backend with shaders
- `whisper.dll` (~1.3MB) - Core whisper.cpp library
- `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll` - Support libraries

### Known Build Issue: vulkan-shaders-gen Path Length

The Vulkan build may fail with error `C1083: Cannot open compiler generated file: ''` due to Windows path length limits. The nested CMake invocation for vulkan-shaders-gen creates extremely long paths that exceed Windows limits.

Affected path pattern:
```
D:\...\build\temp.win-amd64-cpython-312\Release\_pywhispercpp\whisper.cpp\ggml\src\ggml-vulkan\vulkan-shaders-gen-prefix\src\vulkan-shaders-gen-build\CMakeFiles\CMakeScratch\TryCompile-xxxxx\
```

**Solution**: Use `subst` to create a short drive letter mapping to the source folder:
```batch
subst X: D:\claudecli-dictate2\pywhispercpp-src
cd /d X:\
python -m pip install --no-cache-dir . --force-reinstall
subst X: /d  REM Remove mapping when done
```

The build script `build-scripts/build_vulkan_short_path.bat` automates this process.

### Parallel Compilation
Set `CMAKE_BUILD_PARALLEL_LEVEL` to use all CPU cores:
```batch
set CMAKE_BUILD_PARALLEL_LEVEL=16
```

### Why Vulkan Over CUDA
| Aspect | Vulkan | CUDA |
|--------|--------|------|
| GPU Support | NVIDIA, AMD, Intel (all) | NVIDIA only |
| Distribution Size | ~100-150 MB | ~600 MB per arch |
| Performance | 80-95% of CUDA | Fastest on NVIDIA |
| Architecture Builds | Single universal build | One per GPU family |

### Verifying Build Success
Check system info for Vulkan:
```python
import _pywhispercpp as pw
info = pw.whisper_print_system_info()
print("Vulkan" in info)  # Should be True
```

Check GPU device selection:
```python
has_gpu_params = hasattr(pw, 'whisper_init_from_file_with_params')
print(f"GPU device selection: {has_gpu_params}")
```

### n_threads Bug
CRITICAL: Always pass `n_threads` to Model constructor! Without it, whisper.cpp uses default thread count causing 2x slower CPU transcription:
```python
# BAD - n_threads not passed
self._model = Model(str(model_path), use_gpu=self.use_gpu)

# GOOD - n_threads explicitly passed
self._model = Model(str(model_path), n_threads=self.n_threads, use_gpu=self.use_gpu)
```

## Testing Checklist

1. Fresh install - model download dialog appears
2. Model selection saves to config
3. Multilingual transcription (Russian, German, etc.) - should NOT translate to English
4. Config migration from old format
5. Thread safety under concurrent transcribe calls
6. GPU selection UI - dropdown shows available GPUs
7. Force CPU Only checkbox disables GPU dropdown
8. Config saves correctly with retry on file lock
9. --version works in windowed exe (console allocated)
10. Long transcriptions timeout gracefully after 120s
11. Pre-roll buffer captures first syllables (test by speaking immediately after hotkey)
12. Clipboard fallback when no window focused (click desktop, record, check clipboard)
13. Translate to English checkbox works (enable, speak Russian, get English output)
