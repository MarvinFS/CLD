# CLD Build Documentation

This document describes how to build pywhispercpp with Vulkan GPU acceleration and package CLD as a standalone Windows application.

## Quick Start: Complete Build Workflow

For those who want to build CLD from scratch, here's the complete workflow:

```batch
:: 1. Clone the repository
git clone https://github.com/your-repo/cld.git
cd cld

:: 2. Create Python 3.12 virtual environment
python -m venv .venv

:: 3. Install dependencies
.venv\Scripts\pip install -e ".[dev]"

:: 4. Build pywhispercpp with Vulkan support (requires VS 2022 + Vulkan SDK)
build-scripts\build_vulkan_short_path.bat

:: 5. Build the PyInstaller executable
.venv\Scripts\python.exe -m PyInstaller -y CLD.spec

:: 6. (Optional) Compress with UPX for smaller distribution
powershell.exe -ExecutionPolicy Bypass -File compress_upx.ps1

:: Result: dist/CLD/ folder with CLD.exe and _internal/ directory
```

The rest of this document explains each step in detail.

## Overview

CLD uses pywhispercpp for speech recognition with Vulkan GPU acceleration. The standard pywhispercpp from PyPI does not include GPU support, so we build it from source with the Vulkan backend enabled. Additionally, we modify the source to expose GPU device selection parameters that aren't available in the upstream version.

## Prerequisites

### Visual Studio 2022 Build Tools

Download and install from https://visualstudio.microsoft.com/downloads/ (scroll down to "Tools for Visual Studio"). Select the "Desktop development with C++" workload which includes the MSVC compiler and CMake.

After installation, the build tools are located at:
- BuildTools: `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat`
- Community: `C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat`

### Python 3.12

CLD requires Python 3.12. The pywhispercpp Python extension (.pyd file) is compiled for a specific Python version (cp312 = Python 3.12). Using a different Python version at runtime will cause silent crashes.

CRITICAL: If you have Python 3.14 or other versions installed, you must ensure Python 3.12 is first in PATH during build. The build script handles this by setting:
```batch
set PATH=%VENV%\Scripts;C:\Program Files\Python312;%PATH%
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER
```

The `-DPython_FIND_REGISTRY=NEVER` prevents CMake from finding the wrong Python version via Windows registry.

### Vulkan SDK

Download and install from https://vulkan.lunarg.com/sdk/home (~2GB). The SDK provides:
- Vulkan headers and libraries for compilation
- `glslc` shader compiler (required to compile GPU shaders into ggml-vulkan.dll)

Without the Vulkan SDK, CMake will fail with: "Could NOT find Vulkan (missing: Vulkan_LIBRARY Vulkan_INCLUDE_DIR glslc)"

NOTE: The SDK is only needed for building. Users running the compiled CLD application do not need the SDK installed, they just need standard GPU drivers with Vulkan support (which all modern drivers have).

## File Structure

```
D:\claudecli-dictate2\
├── pywhispercpp-src/              # pywhispercpp source with CLD modifications
│   ├── src/main.cpp               # Modified: added GPU device selection wrapper
│   ├── pywhispercpp/model.py      # Modified: added use_gpu/gpu_device params
│   ├── whisper.cpp/               # Git submodule: whisper.cpp source
│   ├── pybind11/                  # Git submodule: Python bindings library
│   ├── CMakeLists.txt             # Build configuration
│   └── pyproject.toml             # Python package metadata
│
├── build-scripts/
│   ├── build_vulkan_short_path.bat  # Main build script (uses subst)
│   ├── build_vulkan_py312.bat       # Alternative build script (direct path)
│   └── patches/
│       └── gpu_device_selection.patch  # Documentation of source modifications
│
├── .venv/                         # Python 3.12 virtual environment
│   └── Lib/site-packages/         # Build outputs installed here
│       ├── _pywhispercpp.cp312-win_amd64.pyd
│       ├── ggml-vulkan-*.dll
│       ├── whisper-*.dll
│       └── ... other DLLs
│
├── CLD.spec                       # PyInstaller spec file
├── pyi_rth_pywhispercpp.py        # PyInstaller runtime hook
└── dist/CLD/                      # Final packaged application
```

## Source Modifications

The upstream pywhispercpp doesn't expose GPU device selection parameters. CLD adds the following modifications:

### src/main.cpp

Added after line 80, a wrapper function that exposes GPU parameters:

```cpp
// GPU device selection support (CLD modification)
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

Added pybind11 binding (in the PYBIND11_MODULE section):

```cpp
DEF_RELEASE_GIL("whisper_init_from_file_with_params", &whisper_init_from_file_with_params_wrapper,
    "Initialize whisper context with GPU device selection. "
    "Args: path_model (str), use_gpu (bool), gpu_device (int). "
    "gpu_device: 0=first GPU, 1=second GPU, etc.");
```

### pywhispercpp/model.py

Added parameters to `__init__`:

```python
def __init__(
    self,
    model: str = 'tiny',
    models_dir: str = None,
    log_level: int = WHISPER_LOG_LEVEL_ERROR,
    n_threads: int = None,
    use_gpu: bool = True,      # CLD addition
    gpu_device: int = 0,       # CLD addition
    ...
):
    self.use_gpu = use_gpu
    self.gpu_device = gpu_device
```

Modified `_init_model()` to use the new function when available:

```python
def _init_model(self):
    if hasattr(pw, 'whisper_init_from_file_with_params'):
        self._ctx = pw.whisper_init_from_file_with_params(
            self.model_path, self.use_gpu, self.gpu_device
        )
    else:
        # Fallback for unmodified pywhispercpp
        self._ctx = pw.whisper_init_from_file(self.model_path)
```

## Build Instructions

### Using the Build Script (Recommended)

Open a regular Command Prompt (not Developer Command Prompt, the script handles vcvarsall):

```batch
cd D:\claudecli-dictate2
build-scripts\build_vulkan_short_path.bat
```

The script performs the following steps:
1. Sets up Visual Studio build environment via vcvarsall.bat
2. Configures PATH for Python 3.12
3. Sets CMAKE_ARGS for Vulkan build
4. Creates a short path mapping using `subst X:` to avoid Windows path length limits
5. Builds and installs pywhispercpp to the venv
6. Removes the drive mapping
7. Verifies the build output

### Why subst is Needed

The Vulkan build creates extremely long nested paths during compilation, particularly for the shader compiler:

```
D:\claudecli-dictate2\pywhispercpp-src\build\temp.win-amd64-cpython-312\Release\_pywhispercpp\whisper.cpp\ggml\src\ggml-vulkan\vulkan-shaders-gen-prefix\src\vulkan-shaders-gen-build\CMakeFiles\CMakeScratch\TryCompile-xxxxx\
```

These paths exceed Windows MAX_PATH limit (~260 characters) causing build failure with error "C1083: Cannot open compiler generated file: ''".

The `subst X:` command maps a drive letter to the source folder, drastically shortening all paths during build.

### Environment Variables

The build uses these environment variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `CMAKE_ARGS` | `-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER` | Enable Vulkan, prevent wrong Python |
| `CMAKE_BUILD_PARALLEL_LEVEL` | `16` | Use all CPU cores for compilation |
| `SETUPTOOLS_SCM_PRETEND_VERSION` | `1.4.2` | Version when .git is unavailable |

## Build Output Files

After successful build, these files appear in `.venv/Lib/site-packages/`:

| File | Size | Description |
|------|------|-------------|
| `_pywhispercpp.cp312-win_amd64.pyd` | ~330 KB | Python extension with GPU device selection |
| `ggml-vulkan-*.dll` | ~55 MB | Vulkan compute backend with compiled shaders |
| `whisper-*.dll` | ~1.3 MB | Core whisper.cpp library |
| `ggml-*.dll` | ~68 KB | GGML base library |
| `ggml-base-*.dll` | ~537 KB | GGML base operations |
| `ggml-cpu-*.dll` | ~721 KB | CPU backend with AVX512 support |
| `vulkan-1-*.dll` | ~1.7 MB | Vulkan loader library |
| `msvcp140-*.dll` | ~558 KB | VC++ runtime (bundled by delvewheel) |
| `vcomp140-*.dll` | ~193 KB | OpenMP runtime (bundled by delvewheel) |

## delvewheel and DLL Name Mangling

The pywhispercpp build system uses [repairwheel](https://discuss.python.org/t/repairwheel-single-cross-platform-interface-to-auditwheel-delocate-and-delvewheel/31827) which automatically invokes [delvewheel](https://github.com/adang1345/delvewheel) on Windows. This tool:

1. Adds SHA256 hash suffixes to DLL names (e.g., `ggml-vulkan-c394d1f39c32686ec401654749edeaa1.dll`)
2. Bundles runtime dependencies that may not be on target systems
3. Modifies the .pyd import table to reference the mangled DLL names

### Why Hash Suffixes?

The hash suffixes prevent [DLL hell](https://vinayak.io/2020/10/22/day-52-bundling-dlls-with-windows-wheels-the-dll-mangling-way/) - if multiple Python packages bundle DLLs with the same name (e.g., `ggml.dll`), Windows would load whichever is already in memory, potentially causing crashes. The hash makes each DLL uniquely identifiable.

### Bundled Runtime Dependencies

delvewheel automatically bundles these additional DLLs that aren't part of whisper.cpp itself:

| DLL | Size | Why Bundled |
|-----|------|-------------|
| `vulkan-1-*.dll` | ~1.7 MB | Vulkan loader - ensures Vulkan works without SDK installed |
| `msvcp140-*.dll` | ~558 KB | Visual C++ runtime (2015-2022) - may be missing on some systems |
| `vcomp140-*.dll` | ~193 KB | OpenMP runtime - required for parallel operations in whisper.cpp |

These runtime DLLs ensure CLD works on systems that don't have Visual C++ Redistributable or Vulkan SDK installed.

### Comparison with Previous Build

Older builds (without repairwheel) produced 6 files with plain names:
```
ggml.dll, ggml-base.dll, ggml-cpu.dll, ggml-vulkan.dll, whisper.dll
_pywhispercpp.cp312-win_amd64.pyd
```

Current builds (with repairwheel/delvewheel) produce 9 files with hash suffixes:
```
ggml-*.dll, ggml-base-*.dll, ggml-cpu-*.dll, ggml-vulkan-*.dll, whisper-*.dll
vulkan-1-*.dll, msvcp140-*.dll, vcomp140-*.dll
_pywhispercpp.cp312-win_amd64.pyd
```

The PyInstaller spec uses glob patterns to handle both old and new naming conventions.

## Verifying the Build

After building, verify Vulkan support:

```python
import _pywhispercpp as pw

# Check system info shows Vulkan
info = pw.whisper_print_system_info()
print("System info:", info)
assert "Vulkan" in info

# Check GPU device selection function exists
has_gpu_params = hasattr(pw, 'whisper_init_from_file_with_params')
print(f"GPU device selection available: {has_gpu_params}")
assert has_gpu_params
```

Expected output includes something like:
```
System info: Vulkan = 1 | Vulkan GPU: NVIDIA GeForce RTX 4090...
GPU device selection available: True
```

## PyInstaller Packaging

### Spec File Configuration

The `CLD.spec` file uses glob patterns to collect DLLs with hash suffixes:

```python
import glob

site_packages = '.venv/Lib/site-packages'
pywhispercpp_binaries = []

# Python extension
pyd_files = glob.glob(f'{site_packages}/_pywhispercpp*.pyd')
for f in pyd_files:
    pywhispercpp_binaries.append((f, '.'))

# Core DLLs (whisper, ggml, vulkan)
for pattern in ['whisper*.dll', 'ggml*.dll', 'vulkan*.dll', 'msvcp*.dll', 'vcomp*.dll']:
    for f in glob.glob(f'{site_packages}/{pattern}'):
        pywhispercpp_binaries.append((f, '.'))
```

### Runtime Hook

The `pyi_rth_pywhispercpp.py` runtime hook ensures DLLs can be found at runtime:

```python
import os
import sys

if getattr(sys, 'frozen', False):
    # Add executable directory to DLL search path
    bundle_dir = os.path.dirname(sys.executable)
    os.add_dll_directory(bundle_dir)
    os.environ['PATH'] = bundle_dir + os.pathsep + os.environ.get('PATH', '')
```

### Building the Executable

```batch
cd D:\claudecli-dictate2
.venv\Scripts\python.exe -m PyInstaller -y CLD.spec
```

Output appears in `dist/CLD/` (~429 MB uncompressed, ~67 MB after UPX compression).

## Troubleshooting

### "Cannot open compiler generated file: ''"

Windows path length limit exceeded. Use `build_vulkan_short_path.bat` which creates a subst mapping.

### "Could NOT find Vulkan"

Vulkan SDK not installed. Download from https://vulkan.lunarg.com/sdk/home

### "Python.h not found" or wrong Python version

PATH doesn't have Python 3.12 first, or CMake found wrong Python. Ensure:
```batch
set PATH=D:\claudecli-dictate2\.venv\Scripts;C:\Program Files\Python312;%PATH%
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER
```

### Runtime crash in packaged exe

Python version mismatch. The .pyd file is compiled for Python 3.12 (cp312). If you ran PyInstaller with Python 3.14, the exe will crash. Always use:
```batch
.venv\Scripts\python.exe -m PyInstaller -y CLD.spec
```

### "Vulkan" not in system info

The build did not include Vulkan. Check that CMAKE_ARGS includes `-DGGML_VULKAN=1` and Vulkan SDK is installed.

### GPU not detected at runtime

Vulkan requires GPU drivers with Vulkan support. All modern NVIDIA, AMD, and Intel drivers include this. Update your GPU drivers if needed.

## Python Dependencies

CLD uses these Python packages (from pyproject.toml):

| Package | Version | Purpose |
|---------|---------|---------|
| `sounddevice` | >=0.4 | Audio capture via PortAudio |
| `pynput` | >=1.7 | Global hotkey listener (keyboard/mouse events) |
| `pyperclip` | >=1.8 | Clipboard operations for text output fallback |
| `numpy` | >=1.24 | Audio array processing |
| `keyboard` | >=0.13 | Activation key capture (scancode detection) |
| `pystray` | >=0.19 | System tray integration |
| `pillow` | >=9.0 | Icon image loading for tray/overlay |
| `pywhispercpp` | >=1.4 | Speech recognition (built from source with Vulkan) |
| `psutil` | >=5.9 | Process management (daemon PID handling) |

Development dependencies:

| Package | Purpose |
|---------|---------|
| `pytest` | Unit testing |
| `ruff` | Linting and code formatting |
| `pyinstaller` | Executable packaging |

## PyInstaller Runtime Hooks

CLD uses three runtime hooks to handle platform-specific initialization in the frozen executable:

### pyi_rth_numpy.py

Fixes numpy circular import issues in frozen executables. numpy.fft has internal dependencies that fail to resolve when frozen. The hook pre-imports the problematic modules in the correct order:

```python
import numpy.fft._pocketfft_umath  # noqa: F401
import numpy.fft._pocketfft  # noqa: F401
import numpy.fft  # noqa: F401
```

### pyi_rth_tcltk.py

Sets TCL_LIBRARY and TK_LIBRARY environment variables so tkinter can find its data files. PyInstaller bundles Tcl/Tk data but tkinter needs explicit paths to find them:

```python
if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
    # Search order: _internal/tcl/, tcl/, _MEIPASS locations
    # Sets os.environ['TCL_LIBRARY'] and os.environ['TK_LIBRARY']
```

### pyi_rth_pywhispercpp.py

Adds DLL search directories so the pywhispercpp native extension can find whisper.cpp DLLs at runtime:

```python
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    internal_dir = os.path.join(exe_dir, '_internal')
    os.add_dll_directory(internal_dir)
    os.add_dll_directory(exe_dir)
    # Also prepends to PATH for older Windows versions
```

Without this hook, the .pyd file would fail to load its DLL dependencies.

## UPX Compression (Optional)

After building with PyInstaller, you can optionally compress the output using UPX to reduce distribution size from ~429 MB to ~67 MB:

```powershell
powershell.exe -ExecutionPolicy Bypass -File compress_upx.ps1
```

The script compresses all .dll and .pyd files in dist/CLD/, skipping files that UPX cannot process (like api-ms-win-crt-*.dll). UPX must be installed and available in PATH.

Note: UPX compression is for local builds only; the script is not included in the public release.

## Why Vulkan Over CUDA

CLD uses Vulkan instead of CUDA for these reasons:

| Aspect | Vulkan | CUDA |
|--------|--------|------|
| GPU Support | NVIDIA, AMD, Intel (all vendors) | NVIDIA only |
| Distribution Size | ~100-150 MB | ~600 MB per GPU architecture |
| Runtime Requirements | Standard GPU drivers | CUDA toolkit or specific runtime |
| Performance | 80-95% of CUDA speed | Fastest on NVIDIA |
| Build Complexity | Single universal build | One build per GPU family (sm_70, sm_80, etc.) |

Vulkan provides near-CUDA performance with universal GPU support and smaller distribution size. Users with any GPU (NVIDIA, AMD, Intel including integrated) can use GPU acceleration without downloading architecture-specific builds.
