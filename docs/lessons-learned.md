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
