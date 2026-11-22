# CLD Build Documentation

This document describes how to build pywhispercpp with Vulkan GPU acceleration and package CLD as a standalone Windows application.

## Quick Start

```batch
:: 1. Clone and setup
git clone https://github.com/MarvinFS/CLD.git
cd CLD
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"

:: 2. Build upstream pywhispercpp v1.5.1 with Vulkan + portable AVX2 CPU backend
::    (requires Visual Studio 2022 Build Tools + Vulkan SDK)
build-scripts\build_vulkan.bat

:: 3. Build the executable
.venv\Scripts\python.exe -m PyInstaller -y CLD.spec

:: Result: dist/CLD/ folder with CLD.exe
```

## Prerequisites

### Visual Studio 2022 Build Tools

Download from https://visualstudio.microsoft.com/downloads/ and select the "Desktop development with C++" workload.

### Python 3.12

The pywhispercpp extension is compiled for Python 3.12 (cp312). Using a different version causes crashes.

### Vulkan SDK

Download from https://vulkan.lunarg.com/sdk/home (~2 GB). Required for compiling `ggml-vulkan.dll` with Vulkan shaders. Users running CLD only need standard GPU drivers.

## Build Process

### Build Script: `build-scripts\build_vulkan.bat`

Open a regular Command Prompt in the repository root and run:

```batch
build-scripts\build_vulkan.bat
```

The script:
1. Sets up the Visual Studio 2022 x64 build environment.
2. Clones upstream `absadiki/pywhispercpp` tag `v1.5.1` (whisper.cpp 1.8.5) into `%TEMP%` with submodules.
3. Strips `.git` from the temp clone and patches its `setup.py` to honor `NO_REPAIR=1` (preserving plain DLL names for `CLD.spec`).
4. Maps the temp clone to `X:` (`subst X:`) to avoid Windows `MAX_PATH` limits during Vulkan shader builds.
5. Builds with Ninja and `-DGGML_VULKAN=1 -DGGML_NATIVE=OFF -DPython_FIND_REGISTRY=NEVER` so `ggml-cpu.dll` targets portable AVX2 without AVX-512 instructions.
6. Copies the `.pyd` and five GGML/Whisper DLLs into `.venv/Lib/site-packages/` and `prebuilt/vulkan-win64/`.
7. Verifies `AVX2 = 1` and that `AVX512` is disabled.

## Build Output

After a successful build, these files appear in `.venv/Lib/site-packages/` and `prebuilt/vulkan-win64/`:

| File | Description |
|------|-------------|
| `_pywhispercpp.cp312-win_amd64.pyd` | Python 3.12 extension module |
| `ggml-vulkan.dll` | Vulkan compute backend |
| `whisper.dll` | Core whisper.cpp library |
| `ggml.dll` | GGML router library |
| `ggml-base.dll` | GGML base operations |
| `ggml-cpu.dll` | Portable AVX2 CPU backend (no AVX-512) |

## Verifying the Build

```batch
.venv\Scripts\python.exe -c "import _pywhispercpp as pw; print(pw.whisper_print_system_info())"
```

Expected output lists detected Vulkan devices and `CPU : ... AVX = 1 | AVX2 = 1` without `AVX512 = 1`.

## PyInstaller Packaging

Build the executable:

```batch
.venv\Scripts\python.exe -m PyInstaller -y CLD.spec
```

The `CLD.spec` file collects the pywhispercpp extension and DLLs from `.venv/Lib/site-packages/` and writes `dist/CLD/CLD.exe` and `dist/CLD/_internal/`. UPX is disabled in `CLD.spec` so `CLD.exe` keeps its Control Flow Guard table intact; run `compress_upx.ps1` afterwards to compress eligible DLLs in `dist/CLD/_internal/`.

## Troubleshooting

### "Cannot open compiler generated file: ''"

Windows `MAX_PATH` limit exceeded. The build script maps `%TEMP%\cld-pywhispercpp-1.5.1` to `X:` with `subst`. If `X:` is already in use, change the drive letter in `build-scripts\build_vulkan.bat`.

### "Could NOT find Vulkan"

Vulkan SDK is not installed. Download from https://vulkan.lunarg.com/sdk/home.

### Runtime crash in packaged exe

Python version mismatch. Always use `.venv\Scripts\python.exe -m PyInstaller`, not system Python.

## File Structure

```
<repo-root>\
├── build-scripts/
│   └── build_vulkan.bat            # Builds upstream pywhispercpp v1.5.1 with Vulkan + AVX2
├── prebuilt/vulkan-win64/          # Prebuilt Vulkan binaries for Python 3.12 (Git LFS)
├── .venv/Lib/site-packages/        # Build outputs installed here
├── CLD.spec                        # PyInstaller spec file
└── dist/CLD/                       # Final packaged application
```

## Why Vulkan Over CUDA

| Aspect | Vulkan | CUDA |
|--------|--------|------|
| GPU Support | NVIDIA, AMD, Intel (all) | NVIDIA only |
| Distribution Size | ~100-150 MB | ~600 MB per architecture |
| Build Complexity | Single universal build | One per GPU family |
| Performance | 80-95% of CUDA | Fastest on NVIDIA |
