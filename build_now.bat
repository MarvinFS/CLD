@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
set CMAKE_BUILD_PARALLEL_LEVEL=16
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER
set SETUPTOOLS_SCM_PRETEND_VERSION=1.4.2
cd /d D:\claudecli-dictate2\pywhispercpp-src
rmdir /s /q build 2>nul
echo Using Python:
D:\claudecli-dictate2\.venv\Scripts\python.exe --version
D:\claudecli-dictate2\.venv\Scripts\python.exe -m pip install --no-cache-dir . --force-reinstall
echo.
echo === Build complete, checking DLLs ===
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*.dll
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*pywhispercpp*.pyd
