@echo off
REM Build pywhispercpp with Vulkan backend for CLD
REM Run from Developer Command Prompt for VS 2022
REM
REM Prerequisites:
REM   - Visual Studio 2022 Build Tools (C++ compiler + CMake)
REM   - Python 3.12 (must exclude Python 3.14 from PATH during build)
REM   - Vulkan SDK installed at C:\VulkanSDK\1.4.x
REM   - GPU drivers with Vulkan support
REM
REM Usage:
REM   1. Open "Developer Command Prompt for VS 2022"
REM   2. cd D:\claudecli-dictate2\build-scripts
REM   3. build_vulkan_py312.bat

setlocal

set VENV=D:\claudecli-dictate2\.venv
set PYWHISPERCPP_SRC=D:\claudecli-dictate2\pywhispercpp-src

REM Ensure Python 3.12 from venv is used, not system Python 3.14
set PATH=%VENV%\Scripts;C:\Program Files\Python312;%PATH%

echo ============================================
echo Building pywhispercpp with Vulkan backend
echo ============================================
echo.
echo VENV: %VENV%
echo Source: %PYWHISPERCPP_SRC%
echo.

REM Verify Python version
python --version
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    exit /b 1
)

REM Verify Vulkan SDK
if not exist "C:\VulkanSDK" (
    echo WARNING: Vulkan SDK not found at C:\VulkanSDK
    echo Download from: https://vulkan.lunarg.com/sdk/home
)

cd /d %PYWHISPERCPP_SRC%
if errorlevel 1 (
    echo ERROR: Could not change to %PYWHISPERCPP_SRC%
    exit /b 1
)

echo Cleaning previous build...
rmdir /s /q build 2>nul
rmdir /s /q _skbuild 2>nul

echo.
echo Setting CMake args for Vulkan build...
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER

echo.
echo Installing pywhispercpp with Vulkan support...
python -m pip install --no-cache-dir . --force-reinstall --verbose
if errorlevel 1 (
    echo ERROR: pip install failed
    exit /b 1
)

echo.
echo Copying Vulkan DLLs to venv site-packages...

REM Copy from whisper.cpp build output
if exist "%PYWHISPERCPP_SRC%\whisper.cpp\build\bin\Release\*.dll" (
    copy "%PYWHISPERCPP_SRC%\whisper.cpp\build\bin\Release\*.dll" "%VENV%\Lib\site-packages\" /Y
    echo Copied from whisper.cpp\build\bin\Release
)

REM Copy from build directory
if exist "%PYWHISPERCPP_SRC%\build\*.dll" (
    copy "%PYWHISPERCPP_SRC%\build\*.dll" "%VENV%\Lib\site-packages\" /Y
    echo Copied from build
)

REM Copy from _skbuild if using scikit-build
for /d %%D in ("%PYWHISPERCPP_SRC%\_skbuild\*") do (
    if exist "%%D\cmake-build\*.dll" (
        copy "%%D\cmake-build\*.dll" "%VENV%\Lib\site-packages\" /Y
        echo Copied from %%D\cmake-build
    )
)

echo.
echo ============================================
echo Build complete!
echo ============================================
echo.
echo Verify DLLs in venv:
dir "%VENV%\Lib\site-packages\*.dll" 2>nul
dir "%VENV%\Lib\site-packages\*.pyd" 2>nul

echo.
echo Test with:
echo   python -c "import _pywhispercpp as pw; print(pw.whisper_print_system_info())"

endlocal
