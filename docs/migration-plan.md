# CLD: pywhispercpp Migration Plan

Fork ClaudeCli-Dictate to CLD with pywhispercpp backend, reducing ML pipeline from ~170MB to ~3MB.

## Phase 1: Project Fork and Setup

**Create CLD project at D:\claudecli-dictate2:**
```powershell
xcopy /E /I "D:\OneDrive - NoWay Inc\APPS\claudecli-dictate" "D:\claudecli-dictate2"
cd D:\claudecli-dictate2
Remove-Item -Recurse -Force .git, dist, build, __pycache__, .venv -ErrorAction SilentlyContinue
git init
```

**Save this plan to new project:**
```powershell
Copy-Item "C:\Users\test\.claude\plans\deep-booping-pony.md" "D:\claudecli-dictate2\docs\migration-plan.md"
```

**Update pyproject.toml:**
- name: `cld`
- entry point: `cld = "cld.cli:main"`
- Replace `faster-whisper>=1.0` with `pywhispercpp>=1.4`
- Add `nuitka>=2.0` to dev dependencies

## Phase 2: GGML Model Configuration

**New WHISPER_MODELS in model_manager.py:**

| Model | File | Size | RAM | Cores | Use Case |
|-------|------|------|-----|-------|----------|
| small | ggml-small.bin | 488MB | 1GB | 4 | Low-end systems |
| medium-q5_0 | ggml-medium-q5_0.bin | 539MB | 2GB | 4 | Default (quantized) |
| medium | ggml-medium.bin | 1.5GB | 3GB | 6 | High-end systems |

**Download URLs:**
```
https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin
```

**Model storage (flat):**
```
%LOCALAPPDATA%\CLD\models\ggml-medium-q5_0.bin
```

**Manual download for development:** Download model file and place in models folder before running.

## Phase 3: Engine Implementation

**Rewrite src/cld/engines/whisper.py:**

```python
from pywhispercpp.model import Model
import os

class WhisperEngine:
    def __init__(self, model_name: str = "medium-q5_0", n_threads: int = None):
        self.model_name = model_name
        self.n_threads = n_threads or max(4, (os.cpu_count() or 8) - 2)
        self._model = None
        self._last_error = None

    def is_available(self) -> bool:
        try:
            from pywhispercpp.model import Model
            return True
        except ImportError:
            return False

    def load_model(self) -> bool:
        model_path = get_models_dir() / f"ggml-{self.model_name}.bin"
        if not model_path.exists():
            self._last_error = f"Model not found: {model_path}"
            return False
        self._model = Model(str(model_path), n_threads=self.n_threads)
        return True

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if not self.load_model():
            return ""
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        segments = self._model.transcribe(audio)
        return ' '.join(s.text.strip() for s in segments).strip()
```

## Phase 4: Model Manager Updates

**Simplify model_manager.py:**
1. Replace WHISPER_MODELS with GGML metadata
2. Config dir: `CLD` → `CLD`
3. `is_model_available()`: Single file check `ggml-{model}.bin`
4. `download_model()`: Direct HTTP with urllib.request.urlretrieve
5. `validate_model()`: Check .bin file size only
6. Hardware validation: Refuse if <2 cores or no SSE4.1

## Phase 5: UI Updates

**model_dialog.py:**
- Model list: small, medium-q5_0 (default), medium
- Show: Size, RAM, CPU cores requirements
- Manual download: Show direct .bin URLs and target folder

**hardware.py recommendations:**
- 8+ cores → medium
- 4+ cores → medium-q5_0
- 2-3 cores → small
- <2 cores → refuse

**config.py:**
- Default model: `medium-q5_0`
- Config dir: `CLD`

## Phase 6: Build System (Three Options)

### Option A: PyInstaller (Primary - Proven, Folder Output)

```powershell
uv run pyinstaller -y --onedir --windowed --name CLD `
    --icon cld_icon.ico `
    --add-data "sounds;sounds" `
    --add-data "cld_icon.png;." `
    --add-data "mic_256.png;." `
    --add-data "C:/Python314/tcl/tcl8.6;tcl/tcl8.6" `
    --add-data "C:/Python314/tcl/tk8.6;tcl/tk8.6" `
    --add-data ".venv/Lib/site-packages/_sounddevice_data;_sounddevice_data" `
    --runtime-hook pyi_rth_numpy.py `
    --runtime-hook pyi_rth_tcltk.py `
    --hidden-import pywhispercpp `
    src/cld/cli.py
```

Output: `dist/CLD/` folder (~270MB estimated)

### Option B: PyInstaller + UPX Compression (Smaller Output)

**Install UPX:**
```powershell
# Download from https://github.com/upx/upx/releases
# Extract to C:\tools\upx or add to PATH
winget install upx.upx
```

**Build with UPX compression:**
```powershell
uv run pyinstaller -y --onedir --windowed --name CLD `
    --icon cld_icon.ico `
    --add-data "sounds;sounds" `
    --add-data "cld_icon.png;." `
    --add-data "mic_256.png;." `
    --add-data "C:/Python314/tcl/tcl8.6;tcl/tcl8.6" `
    --add-data "C:/Python314/tcl/tk8.6;tcl/tk8.6" `
    --add-data ".venv/Lib/site-packages/_sounddevice_data;_sounddevice_data" `
    --runtime-hook pyi_rth_numpy.py `
    --runtime-hook pyi_rth_tcltk.py `
    --hidden-import pywhispercpp `
    --upx-dir "C:/tools/upx" `
    src/cld/cli.py
```

**Or compress after build:**
```powershell
# Compress all DLLs and PYDs in dist folder (30-50% size reduction)
Get-ChildItem -Path "dist/CLD/_internal" -Recurse -Include "*.dll","*.pyd" | ForEach-Object {
    upx --best $_.FullName
}
# Also compress main exe
upx --best "dist/CLD/CLD.exe"
```

Output: `dist/CLD/` folder (~150-180MB estimated with UPX)

**UPX Notes:**
- Compresses executables/DLLs by 30-50%
- Slightly slower startup (decompression overhead)
- Some AV may flag UPX-compressed files (false positives)
- Don't compress numpy/scipy DLLs (causes crashes)

**Exclude problematic DLLs from UPX:**
```powershell
# Compress everything except numpy/scipy
Get-ChildItem -Path "dist/CLD/_internal" -Recurse -Include "*.dll","*.pyd" |
    Where-Object { $_.FullName -notmatch "numpy|scipy|mkl" } |
    ForEach-Object { upx --best $_.FullName }
```

### Option C: Nuitka (Experimental - Single File)

```powershell
uv run python -m nuitka `
    --onefile `
    --standalone `
    --windows-console-mode=disable `
    --enable-plugin=tk-inter `
    --enable-plugin=numpy `
    --windows-icon-from-ico=cld_icon.ico `
    --include-data-files=sounds=sounds `
    --include-data-files=cld_icon.png=. `
    --include-data-files=mic_256.png=. `
    --include-package-data=_sounddevice_data `
    --output-dir=dist-nuitka `
    --output-filename=CLD.exe `
    src/cld/cli.py
```

Output: Single `CLD.exe` (~600-900MB, 30-60 min build)

**Known Nuitka issues to solve:**
- sounddevice DLL bundling (may need explicit --include-data-dir for _sounddevice_data)
- pywhispercpp native library detection
- Daemon subprocess spawning in compiled exe

**Nuitka detection in code:**
```python
if "__compiled__" in dir():
    # Running as Nuitka-compiled exe
    bundle_dir = Path(sys.executable).parent
else:
    # Running from source or PyInstaller
    bundle_dir = Path(__file__).parent
```

## Build Option Comparison

| Option | Output | Size | Build Time | Startup | Notes |
|--------|--------|------|------------|---------|-------|
| PyInstaller | Folder | ~270MB | ~1 min | ~2s | Proven, stable |
| PyInstaller+UPX | Folder | ~150MB | ~2 min | ~3s | Smaller, some AV issues |
| Nuitka | Single exe | ~600MB | ~45 min | ~1s | Experimental, native |

## Phase 7: Documentation

**Update CLAUDE.md:**
- Project name: CLD
- Model table: GGML models
- Remove faster-whisper references
- Add all three build commands
- Note CPU-only operation

## Files to Modify

| File | Changes |
|------|---------|
| `pyproject.toml` | name, deps, entry point |
| `src/cld/engines/whisper.py` | pywhispercpp API |
| `src/cld/model_manager.py` | GGML models, HTTP download |
| `src/cld/ui/model_dialog.py` | New model list |
| `src/cld/ui/hardware.py` | Updated recommendations |
| `src/cld/config.py` | Default model, config dir |
| `CLAUDE.md` | Full documentation update |

## Verification Steps

1. `uv sync --python 3.12` - Dependencies install
2. Download ggml-medium-q5_0.bin manually to models folder
3. `uv run python -m cld.daemon run --overlay` - App runs
4. Record and transcribe - Text output works
5. PyInstaller build - Creates dist/CLD/
6. PyInstaller+UPX build - Smaller dist/CLD/
7. Nuitka build - Creates dist-nuitka/CLD.exe
8. Test all executables standalone

## Implementation Order

1. Fork project to D:\claudecli-dictate2
2. Save this plan as docs/migration-plan.md
3. Update pyproject.toml
4. Rewrite whisper.py engine
5. Update model_manager.py
6. Update UI components
7. Test with source
8. PyInstaller build and test
9. PyInstaller+UPX build and test
10. Nuitka build and test (experimental)
11. Update documentation
