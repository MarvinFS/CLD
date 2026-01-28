# CLD Migration Lessons Learned

## pywhispercpp API

### Translation vs Transcription
pywhispercpp defaults may translate to English. Always explicitly set:
```python
segments = model.transcribe(audio, translate=False, language="auto")
```
- `translate=False` - keeps original language (no English translation)
- `language="auto"` - enables automatic language detection

### Model Constructor
```python
Model(model_path, n_threads=N)  # n_threads parameter is correct
```

### Transcribe Return Value
Returns iterable of segments with `.text` attribute:
```python
text = " ".join(s.text.strip() for s in segments)
```

## GGML Model Management

### Single File Structure
GGML models are single `.bin` files, not directories:
```
%LOCALAPPDATA%\CLD\models\ggml-medium-q5_0.bin
```
Not like faster-whisper which has folders with model.bin, config.json, etc.

### Download URLs
Direct download from HuggingFace:
```
https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin
```

### Available Models
| Model | File | Size |
|-------|------|------|
| small | ggml-small.bin | 488MB |
| medium-q5_0 | ggml-medium-q5_0.bin | 539MB |
| medium | ggml-medium.bin | 1.5GB |

## UI/Config Integration

### Model Dialog Must Save Config
After successful download, save selected model to config:
```python
from cld.config import Config
config = Config.load()
config.engine.whisper_model = self._model_name
config.save()
```

### Daemon Must Reload After Dialog
After model setup dialog completes, reload config and reinitialize engine:
```python
if self._show_model_setup_dialog(model_manager):
    self.config = Config.load()
    model_name = self.config.engine.whisper_model
    self._engine = build_engine(self.config)
```

### Default Model Consistency
Ensure default model is consistent across:
- config.py (EngineConfig default)
- hardware.py (_get_recommendations fallback)
- model_dialog.py (_detect_hardware fallback)

All should use `"medium-q5_0"` as default.

## Thread Safety

### Double-Checked Locking for Model Loading
```python
def __init__(self):
    self._model_lock = threading.Lock()

def load_model(self):
    if self._model is not None:  # Fast path
        return True

    with self._model_lock:
        if self._model is not None:  # Check again inside lock
            return True
        # ... load model ...
```

## ModelManager Requirements

### Required Methods
ModelManager must implement `update_model()` for UI dialogs:
```python
def update_model(self, model_name, progress_callback=None):
    model_path = self._get_model_path(model_name)
    if model_path.exists():
        model_path.unlink()
    return self.download_model(model_name, progress_callback)
```

## Path Management

### Keep Original Paths
Don't change app data paths when forking - keeps compatibility:
- Config: `%LOCALAPPDATA%\CLD\settings.json`
- Models: `%LOCALAPPDATA%\CLD\models\`

### Centralize Path Logic
Both whisper.py and model_manager.py define `get_models_dir()` - keep them in sync.

## Build Considerations

### PyInstaller Hidden Imports
```
--hidden-import pywhispercpp
```

### CPU-Only Operation
pywhispercpp/whisper.cpp is CPU-only (no CUDA). Remove GPU/VRAM references from UI.

## Testing Checklist

1. Fresh install - model download dialog appears
2. Model selection saves to config
3. Multilingual transcription (Russian, German, etc.) - should NOT translate to English
4. Config migration from old format
5. Thread safety under concurrent transcribe calls
