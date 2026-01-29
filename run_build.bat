@echo off
setlocal

echo === Setting up Visual Studio build environment ===
REM Try BuildTools first, then Community
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
) else (
    echo ERROR: Visual Studio 2022 not found!
    exit /b 1
)

echo === Setting up Python 3.12 environment ===

REM Set Python 3.12 from venv first in PATH (before system Python 3.14)
set PATH=D:\claudecli-dictate2\.venv\Scripts;C:\Program Files\Python312;%PATH%

REM Set CMake args for Vulkan build
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER

echo Python version:
python --version

echo.
echo pip version:
pip --version

echo.
echo CMAKE_ARGS=%CMAKE_ARGS%

echo.
echo === Starting build ===
cd /d D:\claudecli-dictate2\pywhispercpp-src

REM Clean previous builds
if exist build rmdir /s /q build
if exist _skbuild rmdir /s /q _skbuild

echo.
echo Building pywhispercpp with Vulkan...
python -m pip install --no-cache-dir . --force-reinstall --verbose 2>&1

echo.
echo === Build complete ===

REM Check if DLLs were created
echo.
echo Checking for output files...
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*.dll 2>nul
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*.pyd 2>nul

endlocal
