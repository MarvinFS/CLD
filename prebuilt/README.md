# Prebuilt Vulkan Binaries

Pre-compiled upstream `pywhispercpp` v1.5.1 (`whisper.cpp` 1.8.5) binaries with Vulkan GPU support and a portable AVX2 CPU backend (`-DGGML_VULKAN=1 -DGGML_NATIVE=OFF`) for Windows x64 (Python 3.12).

The stock PyPI wheel for `pywhispercpp` is CPU-only and does not include `ggml-vulkan.dll`.

## Files

| File | Description |
|------|-------------|
| `_pywhispercpp.cp312-win_amd64.pyd` | Python extension module (Python 3.12, 64-bit) |
| `whisper.dll` | whisper.cpp core library |
| `ggml.dll` | GGML tensor router library |
| `ggml-base.dll` | GGML base operations |
| `ggml-cpu.dll` | GGML portable AVX2 CPU backend (no AVX-512) |
| `ggml-vulkan.dll` | GGML Vulkan GPU backend |

## Installation

Copy all files to `.venv/Lib/site-packages/`:

```batch
copy prebuilt\vulkan-win64\* .venv\Lib\site-packages\
```

## Rebuilding

To rebuild from upstream source (requires Visual Studio 2022 Build Tools and Vulkan SDK):

```batch
build-scripts\build_vulkan.bat
```
