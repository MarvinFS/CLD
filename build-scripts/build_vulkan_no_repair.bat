@echo off
setlocal

REM ============================================================================
REM Build pywhispercpp with Vulkan - skip wheel repair and copy DLLs manually
REM ============================================================================

echo === Setting up Visual Studio build environment ===
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64

echo === Setting up Python 3.12 environment ===
set PATH=D:\claudecli-dictate2\.venv\Scripts;C:\Program Files\Python312;%PATH%
REM Use all CPU cores for parallel compilation
set CMAKE_BUILD_PARALLEL_LEVEL=16
set CMAKE_GENERATOR=Ninja
set CMAKE_ARGS=-DGGML_VULKAN=1 -DPython_FIND_REGISTRY=NEVER
set SETUPTOOLS_SCM_PRETEND_VERSION=1.4.2
set SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYWHISPERCPP=1.4.2
REM Skip wheel repair - we'll copy DLLs manually
set NO_REPAIR=1

echo Python version:
python --version

REM Remove any existing X: mapping
subst X: /d 2>nul

REM Map X: to pywhispercpp-src folder
echo === Creating short path mapping X: -^> D:\claudecli-dictate2\pywhispercpp-src ===
subst X: D:\claudecli-dictate2\pywhispercpp-src
if errorlevel 1 (
    echo ERROR: Failed to create subst mapping. Try running as admin or use a different letter.
    exit /b 1
)

cd /d X:\
rmdir /s /q build 2>nul
rmdir /s /q _skbuild 2>nul

echo.
echo === Building pywhispercpp with Vulkan from X:\ ===
python -m pip install --no-cache-dir . --force-reinstall

set BUILD_RESULT=%errorlevel%

echo.
echo === Copying DLLs to site-packages ===
set DLL_SRC=X:\build\temp.win-amd64-cpython-312\Release\_pywhispercpp\bin
set DLL_DEST=D:\claudecli-dictate2\.venv\Lib\site-packages

echo Copying from %DLL_SRC% to %DLL_DEST%
copy /Y "%DLL_SRC%\*.dll" "%DLL_DEST%\" 2>nul
if not exist "%DLL_SRC%\*.dll" (
    echo Trying Release subfolder...
    copy /Y "%DLL_SRC%\Release\*.dll" "%DLL_DEST%\" 2>nul
)

REM Remove mapping
echo.
echo === Removing short path mapping ===
cd /d D:\
subst X: /d

if %BUILD_RESULT% neq 0 (
    echo.
    echo BUILD FAILED with error %BUILD_RESULT%
    exit /b %BUILD_RESULT%
)

echo.
echo === Checking results ===
echo DLLs in site-packages:
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*.dll 2>nul
echo.
echo PYD files:
dir /b D:\claudecli-dictate2\.venv\Lib\site-packages\*pywhispercpp*.pyd 2>nul

echo.
echo === Verifying Vulkan support ===
python -c "import _pywhispercpp as pw; print(pw.whisper_print_system_info())"

endlocal
