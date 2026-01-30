# CLD Build Documentation

This document describes how to build pywhispercpp with Vulkan GPU acceleration and package CLD as a standalone Windows application.

## Quick Start

```batch
:: 1. Clone and setup
git clone https://github.com/your-repo/cld.git
cd cld
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"

:: 2. Build pywhispercpp with Vulkan (requires VS 2022 + Vulkan SDK)
build-scripts\build_vulkan_no_repair.bat

:: 3. Build the executable
.venv\Scripts\python.exe -m PyInstaller -y CLD.spec

:: Result: dist/CLD/ folder with CLD.exe
```

## Prerequisites

### Visual Studio 2022 Build Tools

Download from https://visualstudio.microsoft.com/downloads/ and select "Desktop development with C++" workload.

### Python 3.12

The pywhispercpp extension is compiled for Python 3.12 (cp312). Using a different version causes crashes.

### Vulkan SDK

Download from https://vulkan.lunarg.com/sdk/home (~2GB). Required for compiling ggml-vulkan.dll with Vulkan shaders. Users running CLD only need standard GPU drivers.

## Build Process

### Build Script: build_vulkan_no_repair.bat

This is the recommended build script. Open a regular Command Prompt:

```batch
cd D:\claudecli-dictate2
build-scripts\build_vulkan_no_repair.bat
```

The script:
1. Sets up Visual Studio build environment
2. Uses Ninja generator for fast parallel builds
3. Creates short path mapping (`subst X:`) to avoid Windows MAX_PATH limits
4. Skips delvewheel wheel repair (NO_REPAIR=1) which had path issues
5. Manually copies DLLs to site-packages after build
6. Verifies Vulkan support

### Why NO_REPAIR

The standard pywhispercpp build uses delvewheel to bundle DLLs with hash suffixes. This failed due to path resolution issues with the subst mapping. The NO_REPAIR approach:
- Builds pywhispercpp normally
- Copies DLLs directly without hash mangling
- Results in simpler, predictable file names

### Setup Requirements

Before first build, initialize git in pywhispercpp-src (required for setuptools_scm):

```batch
cd D:\claudecli-dictate2\pywhispercpp-src
git init
git add -A
git commit -m "Initial commit"
git tag v1.4.2
```

This is already done in the repository.

## Build Output

After successful build, these files appear in `.venv/Lib/site-packages/`:

| File | Size | Description |
|------|------|-------------|
| `_pywhispercpp.cp312-win_amd64.pyd` | ~330 KB | Python extension |
| `ggml-vulkan.dll` | ~55 MB | Vulkan compute backend |
| `whisper.dll` | ~1.3 MB | Core whisper.cpp library |
| `ggml.dll` | ~68 KB | GGML router library |
| `ggml-base.dll` | ~537 KB | GGML base operations |
| `ggml-cpu.dll` | ~721 KB | CPU backend with AVX512 |

## Verifying the Build

```batch
.venv\Scripts\python.exe -c "import _pywhispercpp as pw; print(pw.whisper_print_system_info())"
```

Expected output includes `Vulkan = 1` and detected GPUs.

## PyInstaller Packaging

Build the executable:

```batch
.venv\Scripts\python.exe -m PyInstaller -y CLD.spec
```

The `CLD.spec` file collects DLLs via glob patterns to handle both plain names (current) and hash-suffixed names (delvewheel):

```python
for pattern in ['whisper*.dll', 'ggml*.dll', 'vulkan*.dll', 'msvcp*.dll', 'vcomp*.dll']:
    for f in glob.glob(f'{site_packages}/{pattern}'):
        pywhispercpp_binaries.append((f, '.'))
```

Output: `dist/CLD/` (~340 MB with UPX compression)

## Troubleshooting

### "Cannot open compiler generated file: ''"

Windows MAX_PATH limit exceeded. The build script uses `subst X:` to create short paths. If X: is in use, edit the script to use a different drive letter.

### "Could NOT find Vulkan"

Vulkan SDK not installed. Download from https://vulkan.lunarg.com/sdk/home

### setuptools_scm version error

Run `git init && git add -A && git commit -m "init" && git tag v1.4.2` in pywhispercpp-src.

### Runtime crash in packaged exe

Python version mismatch. Always use `.venv\Scripts\python.exe -m PyInstaller`, not system Python.

## File Structure

```
D:\claudecli-dictate2\
├── pywhispercpp-src/           # Source with GPU device selection modifications
│   └── src/main.cpp            # Modified: whisper_init_from_file_with_params
├── build-scripts/
│   └── build_vulkan_no_repair.bat  # Main build script (recommended)
├── .venv/Lib/site-packages/    # Build outputs installed here
├── CLD.spec                    # PyInstaller spec file
└── dist/CLD/                   # Final packaged application
```

## Why Vulkan Over CUDA

| Aspect | Vulkan | CUDA |
|--------|--------|------|
| GPU Support | NVIDIA, AMD, Intel (all) | NVIDIA only |
| Distribution Size | ~100-150 MB | ~600 MB per architecture |
| Build Complexity | Single universal build | One per GPU family |
| Performance | 80-95% of CUDA | Fastest on NVIDIA |
