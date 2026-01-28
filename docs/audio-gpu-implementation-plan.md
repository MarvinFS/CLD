# CLD Audio Visualization & GPU Support Implementation

## Summary

This document describes the implementation of real audio visualization and GPU support for CLD, completed on 2026-01-28.

## What Was Implemented

### 1. Real Audio Visualization

Replaced fake sine-wave waveform animation with actual microphone audio levels.

**Files Modified:**

- `src/cld/recorder.py` - Added thread-safe audio level calculation in the audio callback
- `src/cld/ui/overlay.py` - Updated waveform animation to use real audio levels
- `src/cld/daemon_service.py` - Added `get_audio_level()` method and wired overlay callback

**How It Works:**

The audio callback in `recorder.py` calculates RMS (root mean square) of each audio chunk and stores it in a thread-safe global variable. The overlay polls this value at 30fps and applies smoothing for natural-looking waveform bars that respond to actual voice input.

```python
# In recorder.py callback:
rms = np.sqrt(np.mean(indata ** 2))
level = min(1.0, rms * 10)  # Normalize to 0-1
with _level_lock:
    _current_level = level
```

**Benefits:**
- Waveform bars now respond to actual microphone input
- Louder speech = taller bars, silence = minimal bars
- Eliminated "Audio queue full; dropping chunk" warnings (removed unused queue)

### 2. GPU Support Infrastructure

Added detection and configuration for CUDA GPU acceleration with pywhispercpp.

**Files Modified:**

- `src/cld/ui/hardware.py` - Added NVIDIA GPU detection via nvidia-smi and pywhispercpp CUDA check
- `src/cld/engines/whisper.py` - Added `use_gpu` parameter and auto-detection logic
- `src/cld/engine_factory.py` - Wired config device setting to WhisperEngine

**How It Works:**

1. `hardware.py` detects GPU via `nvidia-smi --query-gpu=name,memory.total`
2. Checks if pywhispercpp was built with CUDA by inspecting Model.__init__ signature for `use_gpu` parameter
3. `whisper.py` auto-detects CUDA support and passes `use_gpu=True` to Model constructor when available
4. Config `engine.device` setting controls behavior: "auto", "gpu"/"cuda", or "cpu"

## Dependencies for GPU Support

### Required: CUDA Toolkit

pywhispercpp must be compiled from source with CUDA enabled. This requires:

1. **NVIDIA GPU Driver** (already installed - version 591.74)
2. **CUDA Toolkit** (NOT installed - required for compilation)

Download CUDA Toolkit from: https://developer.nvidia.com/cuda-downloads

Recommended version: CUDA 12.x or 13.x (match driver's supported CUDA version shown in nvidia-smi)

### Building pywhispercpp with CUDA

After installing CUDA Toolkit:

```powershell
# Clone with submodules (submodules don't auto-fetch via pip/uv)
cd D:\TMP
git clone https://github.com/absadiki/pywhispercpp
cd pywhispercpp
rm -rf pybind11 whisper.cpp
git clone --depth 1 https://github.com/pybind/pybind11.git pybind11
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git whisper.cpp

# Build with CUDA for RTX 4090 (Ada Lovelace = arch 89)
$env:GGML_CUDA = "1"
$env:CMAKE_ARGS = "-DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES=89"
pip install --no-cache-dir .
```

### CUDA Architecture Values

| GPU Generation | Architecture | CMAKE_CUDA_ARCHITECTURES |
|----------------|--------------|--------------------------|
| RTX 4090/4080/4070 (Ada) | Ada Lovelace | 89 |
| RTX 3090/3080/3070 (Ampere) | Ampere | 86 |
| RTX 2080/2070 (Turing) | Turing | 75 |
| GTX 1080/1070 (Pascal) | Pascal | 61 |

## Lessons Learned

### 1. Git Submodules Don't Auto-Fetch

When installing pywhispercpp from git URL via pip or uv, the submodules (pybind11, whisper.cpp) are NOT fetched. The build fails with:

```
CMake Error: The source directory .../pybind11 does not contain a CMakeLists.txt file.
```

**Solution:** Clone repo manually and clone submodules separately:
```bash
git clone https://github.com/absadiki/pywhispercpp
cd pywhispercpp
git clone --depth 1 https://github.com/pybind/pybind11.git pybind11
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git whisper.cpp
```

### 2. uv Copies Source to Temp Directory

When building from local path, `uv pip install` copies the source to a temp directory, which doesn't include the manually cloned submodules.

**Solution:** Use system pip directly, not uv, for building from local source with submodules.

### 3. CUDA Toolkit vs Driver

Having NVIDIA GPU drivers installed (which includes CUDA runtime) is NOT sufficient for compilation. The CUDA Development Toolkit must be installed separately to get:
- `cuda.lib` (linker library)
- `nvcc` (NVIDIA CUDA compiler)
- CUDA headers

Build error without toolkit:
```
LINK : fatal error LNK1181: cannot open input file 'cuda.lib'
```

### 4. Environment Variables in Bash vs PowerShell

Bash (Git Bash on Windows) doesn't understand PowerShell syntax for environment variables:

```bash
# Wrong (PowerShell syntax in bash):
$env:GGML_CUDA="1"; pip install .

# Correct (bash syntax):
GGML_CUDA=1 pip install .
```

### 5. Thread-Safe Audio Level Updates

Audio callbacks run in a separate thread from tkinter. Used a simple lock-protected global float instead of a queue to avoid the "queue full" issue:

```python
_current_level: float = 0.0
_level_lock = threading.Lock()

# In callback (audio thread):
with _level_lock:
    _current_level = level

# In overlay (main thread):
with _level_lock:
    return _current_level
```

## Configuration

The device setting in `settings.json` controls GPU usage:

```json
{
  "engine": {
    "type": "whisper",
    "whisper_model": "medium-q5_0",
    "device": "auto"
  }
}
```

Values:
- `"auto"` - Use GPU if pywhispercpp has CUDA support, otherwise CPU
- `"gpu"` or `"cuda"` - Force GPU (falls back to CPU if unavailable)
- `"cpu"` - Force CPU only

## Verification

### Audio Visualization

1. Run CLD with overlay: `uv run python -m cld.daemon run --overlay`
2. Press hotkey to start recording
3. Speak at varying volumes
4. Waveform bars should respond to voice (louder = taller)

### GPU Support (after installing CUDA Toolkit and rebuilding)

1. Run CLD with `--debug` flag
2. Check startup log for: `WhisperEngine: model=..., use_gpu=True`
3. Run `nvidia-smi -l 1` in separate terminal
4. Record and transcribe
5. GPU memory should increase during model load
6. CUDA utilization > 0% during transcription

## Current Status

| Feature | Status |
|---------|--------|
| Real audio visualization | Complete, working |
| GPU detection (nvidia-smi) | Complete, working |
| pywhispercpp CUDA check | Complete, working |
| GPU inference | Blocked - requires CUDA Toolkit installation |

## Next Steps

1. Install CUDA Toolkit 12.x or 13.x
2. Rebuild pywhispercpp with CUDA support
3. Verify GPU acceleration with nvidia-smi monitoring
4. Benchmark transcription speed (expect 3-5x improvement)
