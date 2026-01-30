@echo off
setlocal

REM ============================================================================
REM Build pywhispercpp with Vulkan directly (no subst mapping)
REM Uses PYWHISPERCPP_VERSION to avoid setuptools_scm git issues
REM ============================================================================

echo === Setting up Visual Studio build environment ===
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64

echo === Setting up Python 3.12 environment ===
set PATH=D:\claudecli-dictate2\.venv\Scripts;C:\Program Files\Python312;%PATH%
REM Use all CPU cores for parallel compilation
set CMAKE_BUILD_PARALLEL_LEVEL=16
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER
REM Set version explicitly to avoid setuptools_scm git issues
set PYWHISPERCPP_VERSION=1.4.2
set SETUPTOOLS_SCM_PRETEND_VERSION=1.4.2
set SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYWHISPERCPP=1.4.2

echo Python version:
python --version

cd /d D:\claudecli-dictate2\pywhispercpp-src
rmdir /s /q build 2>nul
rmdir /s /q _skbuild 2>nul

echo.
echo === Building pywhispercpp with Vulkan ===
python -m pip install --no-cache-dir . --force-reinstall

set BUILD_RESULT=%errorlevel%

if %BUILD_RESULT% neq 0 (
    echo.
    echo BUILD FAILED with error %BUILD_RESULT%
    exit /b %BUILD_RESULT%
)

echo.
echo === Checking results ===
echo DLLs in site-packages:
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*.dll 2>nul
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*pywhispercpp*.pyd 2>nul

echo.
echo === Verifying Vulkan support ===
python -c "import _pywhispercpp as pw; print(pw.whisper_print_system_info())"

endlocal
