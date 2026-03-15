# Prebuilt Vulkan Binaries

Pre-compiled pywhispercpp binaries with Vulkan GPU support for Windows x64 (Python 3.12).

These are custom-built from `pywhispercpp-src/` with `GGML_VULKAN=1`. The stock PyPI
version of pywhispercpp does NOT include GPU support and will crash CLD on startup.

## Files

| File | Description |
|------|-------------|
| `_pywhispercpp.cp312-win_amd64.pyd` | Python extension module (Python 3.12, 64-bit) |
| `whisper.dll` | whisper.cpp core library |
| `ggml.dll` | GGML tensor library |
| `ggml-base.dll` | GGML base operations |
| `ggml-cpu.dll` | GGML CPU backend |
| `ggml-vulkan.dll` | GGML Vulkan GPU backend (~54MB) |

## Installation

Copy all files to `.venv/Lib/site-packages/`:

```batch
copy prebuilt\vulkan-win64\* .venv\Lib\site-packages\
```

## Rebuilding

To rebuild from source (requires Visual Studio 2022 Build Tools and Vulkan SDK):

```batch
build-scripts\build_vulkan_no_repair.bat
```
