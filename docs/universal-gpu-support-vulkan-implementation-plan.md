# Vulkan GPU Support for CLD - Implementation Plan

## Summary

Add universal GPU acceleration via Vulkan backend using pre-built binaries with automatic GPU selection (discrete GPU over integrated).

## Why Vulkan

| Criteria | Vulkan | CUDA |
|----------|--------|------|
| GPU Support | NVIDIA, AMD, Intel (discrete + integrated) | NVIDIA only |
| Distribution Size | ~100-150 MB | ~600 MB per architecture |
| User Requirements | Standard GPU drivers | NVIDIA drivers only |

## Pre-built Vulkan Binaries

**Source:** https://github.com/jerryshell/whisper.cpp-windows-vulkan-bin/releases
**Size:** 17.4 MB
**Build date:** January 18, 2026 (compatible with pywhispercpp's whisper.cpp from Jan 21, 2026)

**Already downloaded to:** `D:\TMP\whisper-vulkan-prebuilt\`

**Contents:**
- `whisper.dll` (1.3 MB) - main library with Vulkan support
- `ggml-vulkan.dll` (55 MB) - Vulkan backend
- `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll` - support libraries

**Verified working:** Detects both NVIDIA RTX 4090 and AMD iGPU via Vulkan.

## Implementation Steps

### Step 1: Modify pywhispercpp bindings for GPU device selection

**File:** `D:\TMP\pywhispercpp\src\main.cpp`

Add new wrapper function to expose `gpu_device` parameter:

```cpp
struct whisper_context_wrapper whisper_init_from_file_with_params_wrapper(
    const char * path_model, bool use_gpu, int gpu_device) {
    struct whisper_context_params params = whisper_context_default_params();
    params.use_gpu = use_gpu;
    params.gpu_device = gpu_device;
    struct whisper_context * ctx = whisper_init_from_file_with_params(path_model, params);
    struct whisper_context_wrapper ctw_w;
    ctw_w.ptr = ctx;
    return ctw_w;
}
```

Add pybind11 binding at bottom:
```cpp
DEF_RELEASE_GIL("whisper_init_from_file_with_params", &whisper_init_from_file_with_params_wrapper,
    "Load model with GPU params. use_gpu: enable GPU, gpu_device: device index (0=first)");
```

### Step 2: Build pywhispercpp with Vulkan using pre-built DLLs

Copy pre-built Vulkan DLLs to pywhispercpp before building:
```batch
copy D:\TMP\whisper-vulkan-prebuilt\*.dll D:\TMP\pywhispercpp\whisper.cpp\
```

Build pywhispercpp (NO Vulkan SDK needed - using pre-built DLLs):
```batch
cd /d D:\TMP\pywhispercpp
rmdir /s /q build 2>nul
set CMAKE_ARGS=-DPython_FIND_REGISTRY=NEVER
"D:\claudecli-dictate2\.venv\Scripts\python.exe" -m pip install --no-cache-dir . --force-reinstall
```

Then copy Vulkan DLLs to venv site-packages:
```batch
copy D:\TMP\whisper-vulkan-prebuilt\*.dll "D:\claudecli-dictate2\.venv\Lib\site-packages\"
```

### Step 3: Update CLD config

**File:** `src/cld/config.py`

Add `gpu_device` to EngineConfig:
```python
@dataclass
class EngineConfig:
    type: Literal["whisper"] = "whisper"
    whisper_model: str = "medium-q5_0"
    device: str = "auto"  # "auto", "cpu", or "gpu"
    gpu_device: int = -1  # -1=auto-select, 0=first GPU, 1=second GPU
```

### Step 4: Update pywhispercpp Model class

**File:** `D:\TMP\pywhispercpp\pywhispercpp\model.py`

Modify `_init_model()` to use new function with GPU params:
```python
def _init_model(self) -> None:
    with utils.redirect_stderr(to=self.redirect_whispercpp_logs_to):
        # Use new function with GPU params
        self._ctx = pw.whisper_init_from_file_with_params(
            self.model_path,
            self.use_gpu,      # True for GPU acceleration
            self.gpu_device    # Device index (-1 for auto)
        )
```

Add constructor params:
```python
def __init__(self, ..., use_gpu: bool = True, gpu_device: int = -1, **params):
    self.use_gpu = use_gpu
    self.gpu_device = gpu_device
```

### Step 5: Update CLD whisper engine

**File:** `src/cld/engines/whisper.py`

Pass GPU settings to Model:
```python
self._model = Model(
    model_path,
    use_gpu=(config.engine.device != "cpu"),
    gpu_device=config.engine.gpu_device,
    n_threads=n_threads,
    ...
)
```

### Step 6: Add GPU auto-selection logic

**File:** `src/cld/ui/hardware.py`

```python
def auto_select_gpu() -> int:
    """Auto-select best GPU (discrete over integrated).

    Returns device index, or -1 to let whisper.cpp decide.
    Vulkan typically lists discrete GPUs first (index 0).
    """
    # Return 0 (first GPU) which is usually discrete
    # whisper.cpp Vulkan backend lists discrete GPUs before iGPUs
    return 0
```

## Files to Modify

| File | Changes |
|------|---------|
| `D:\TMP\pywhispercpp\src\main.cpp` | Add `whisper_init_from_file_with_params_wrapper` |
| `D:\TMP\pywhispercpp\pywhispercpp\model.py` | Add `use_gpu` and `gpu_device` params |
| `src/cld/config.py` | Add `gpu_device` to EngineConfig |
| `src/cld/engines/whisper.py` | Pass GPU settings to Model |
| `src/cld/ui/hardware.py` | Add `auto_select_gpu()` function |

## Verification

1. Check Vulkan backend:
```python
import _pywhispercpp as pw
print(pw.whisper_print_system_info())  # Should show "Vulkan"
```

2. Verify GPU detection:
```bash
uv run python -m cld.daemon run --overlay --debug
```
Look for: `ggml_vulkan: Found 2 Vulkan devices`

3. Monitor GPU usage during transcription:
- NVIDIA: `nvidia-smi -l 1`
- Task Manager GPU tab for AMD/Intel

## Config Format

```json
{
  "engine": {
    "type": "whisper",
    "whisper_model": "medium-q5_0",
    "device": "auto",
    "gpu_device": -1
  }
}
```

- `device`: "auto" (use GPU if available), "cpu" (force CPU), "gpu" (require GPU)
- `gpu_device`: -1 (auto-select), 0 (first GPU), 1 (second GPU)
