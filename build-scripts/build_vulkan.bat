@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Build upstream pywhispercpp (v1.5.1) with Vulkan GPU support and portable
REM AVX2 CPU backend (GGML_NATIVE=OFF -> AVX512=0 so ggml-cpu.dll runs on any
REM x64 AVX2 CPU without illegal-instruction crashes).
REM ============================================================================

set "PYWHISPERCPP_TAG=v1.5.1"
set "PYWHISPERCPP_VER=1.5.1"

pushd "%~dp0.."
set "REPO_ROOT=%CD%"
popd

set "VENV_DIR=%REPO_ROOT%\.venv"
set "SITE_PACKAGES=%VENV_DIR%\Lib\site-packages"
set "PREBUILT_DIR=%REPO_ROOT%\prebuilt\vulkan-win64"
set "BUILD_SRC=%TEMP%\cld-pywhispercpp-%PYWHISPERCPP_VER%"

echo === Setting up Visual Studio 2022 build environment ===
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
) else (
    echo ERROR: Visual Studio 2022 Build Tools or Community not found.
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: Virtual environment not found at %VENV_DIR%
    exit /b 1
)

for /f "usebackq delims=" %%P in (`"%VENV_DIR%\Scripts\python.exe" -c "import sys; print(sys.base_prefix)"`) do set "PY_BASE=%%P"
set "PATH=%VENV_DIR%\Scripts;%PY_BASE%;%PATH%"

echo Python version:
python --version

if not exist "C:\VulkanSDK" (
    echo WARNING: Vulkan SDK not found at C:\VulkanSDK
)

echo.
echo === Cloning upstream absadiki/pywhispercpp %PYWHISPERCPP_TAG% ===
if exist "%BUILD_SRC%" rmdir /s /q "%BUILD_SRC%"
git clone --depth 1 --branch %PYWHISPERCPP_TAG% --recurse-submodules --shallow-submodules https://github.com/absadiki/pywhispercpp.git "%BUILD_SRC%"
if errorlevel 1 (
    echo ERROR: git clone failed.
    exit /b 1
)

REM Remove .git from temp clone so setuptools_scm does not cross-mount fail on subst X:
if exist "%BUILD_SRC%\.git" rmdir /s /q "%BUILD_SRC%\.git"

REM Respect NO_REPAIR=1 so repairwheel does not rename DLLs with hashes (CLD.spec upx_exclude uses plain names)
python -c "from pathlib import Path; p = Path(r'%BUILD_SRC%\setup.py'); s = p.read_text(encoding='utf-8'); needle = '        if sys.platform.startswith(\x27win\x27):'; patch = '        if os.environ.get(\x27NO_REPAIR\x27, \x270\x27) == \x271\x27:\n            print(\x27Skipping wheel repair\x27)\n            return\n' + needle; assert needle in s, 'RepairWheel hook not found'; p.write_text(s.replace(needle, patch, 1), encoding='utf-8')"
if errorlevel 1 (
    echo ERROR: Failed to patch temp setup.py for NO_REPAIR.
    exit /b 1
)

set CMAKE_BUILD_PARALLEL_LEVEL=16
set CMAKE_GENERATOR=Ninja
set CMAKE_ARGS=-DGGML_VULKAN=1 -DGGML_NATIVE=OFF -DPython_FIND_REGISTRY=NEVER
set SETUPTOOLS_SCM_PRETEND_VERSION=%PYWHISPERCPP_VER%
set SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYWHISPERCPP=%PYWHISPERCPP_VER%
set PYWHISPERCPP_VERSION=%PYWHISPERCPP_VER%
set NO_REPAIR=1

REM Short path mapping avoids Windows MAX_PATH limits during Vulkan shader builds
subst X: /d >nul 2>&1
subst X: "%BUILD_SRC%"
if errorlevel 1 (
    echo ERROR: Failed to map X: to %BUILD_SRC%
    exit /b 1
)

cd /d X:\
echo.
echo === Building pywhispercpp %PYWHISPERCPP_VER% with Vulkan + GGML_NATIVE=OFF ===
python -m pip install --no-cache-dir --no-deps . --force-reinstall
set BUILD_RESULT=%errorlevel%

if %BUILD_RESULT% equ 0 (
    echo.
    echo === Copying DLLs to site-packages and prebuilt/vulkan-win64 ===
    if not exist "%PREBUILT_DIR%" mkdir "%PREBUILT_DIR%"
    python -c "import shutil; from pathlib import Path; names = {'whisper.dll','ggml.dll','ggml-base.dll','ggml-cpu.dll','ggml-vulkan.dll'}; found = {p.name: p for p in Path(r'X:\build').rglob('*.dll') if p.name in names}; missing = names - set(found); assert not missing, f'Missing built DLLs: {missing}'; [(shutil.copy2(p, Path(r'%SITE_PACKAGES%') / n), shutil.copy2(p, Path(r'%PREBUILT_DIR%') / n)) for n, p in sorted(found.items())]; print('Copied:', ', '.join(sorted(found)))"
    if errorlevel 1 set BUILD_RESULT=1
    copy /Y "%SITE_PACKAGES%\_pywhispercpp*.pyd" "%PREBUILT_DIR%\" >nul
)

cd /d "%REPO_ROOT%"
subst X: /d >nul 2>&1
rmdir /s /q "%BUILD_SRC%" >nul 2>&1

if %BUILD_RESULT% neq 0 (
    echo.
    echo BUILD FAILED with error %BUILD_RESULT%
    exit /b %BUILD_RESULT%
)

echo.
echo === Verifying Vulkan and portable AVX2 (no AVX512) ===
python -c "import _pywhispercpp as pw; info = pw.whisper_print_system_info(); print(info); assert 'AVX2 = 1' in info, 'Expected AVX2 = 1'; assert 'AVX512 = 1' not in info, 'Expected AVX512 disabled (portable build)'"
if errorlevel 1 (
    echo ERROR: Verification failed!
    exit /b 1
)

echo.
echo Build and verification succeeded!
endlocal
