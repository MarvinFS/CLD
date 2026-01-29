"""Whisper STT engine using pywhispercpp (whisper.cpp bindings)."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

_whisper_available = False
_Model = None
_import_error = None
_cuda_supported = False

try:
    from pywhispercpp.model import Model as _Model
    _whisper_available = True
    # Check if CUDA backend is available via system info
    # CUDA builds use GPU automatically - no use_gpu parameter needed
    try:
        import _pywhispercpp as _pw
        _cuda_supported = "CUDA" in _pw.whisper_print_system_info()
    except Exception:
        _cuda_supported = False
except Exception as e:
    _import_error = f"{type(e).__name__}: {e}"


def get_models_dir() -> Path:
    """Get CLD models directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CLD" / "models"
    return Path.home() / ".cld" / "models"


def is_cuda_supported() -> bool:
    """Check if pywhispercpp was built with CUDA support."""
    return _cuda_supported


class WhisperEngine:
    """Whisper speech-to-text engine backed by pywhispercpp (whisper.cpp).

    Uses GGML model files. Supports GPU acceleration when pywhispercpp
    is built with GGML_CUDA=1.

    Models (default: medium-q5_0):
        - small: ~488MB, fast, good accuracy
        - medium-q5_0: ~539MB, quantized, best balance (default)
        - medium: ~1.5GB, full precision, best accuracy
    """

    def __init__(
        self,
        model_name: str = "medium-q5_0",
        n_threads: Optional[int] = None,
        use_gpu: Optional[bool] = None,
    ):
        self.model_name = model_name
        self.n_threads = n_threads or max(4, (os.cpu_count() or 8) - 2)
        self._model: Optional[object] = None
        self._model_lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._last_error: Optional[str] = None

        # GPU support: auto-detect or use explicit setting
        if use_gpu is None:
            # Auto: use GPU if pywhispercpp supports it
            self.use_gpu = _cuda_supported
        elif use_gpu and not _cuda_supported:
            self._logger.warning("GPU requested but pywhispercpp lacks CUDA support. Using CPU.")
            self.use_gpu = False
        else:
            self.use_gpu = use_gpu

        self._logger.info("WhisperEngine: model=%s, threads=%d, use_gpu=%s (cuda_supported=%s)",
                         model_name, self.n_threads, self.use_gpu, _cuda_supported)

    def is_available(self) -> bool:
        return _whisper_available

    def get_last_error(self) -> Optional[str]:
        """Get the last error message."""
        return self._last_error

    def _get_model_path(self) -> Path:
        """Get path to GGML model file."""
        return get_models_dir() / f"ggml-{self.model_name}.bin"

    def load_model(self) -> bool:
        """Load the Whisper model.

        Returns:
            True if model loaded successfully.
        """
        if not self.is_available():
            self._last_error = f"pywhispercpp not installed: {_import_error}"
            return False

        # Fast path - already loaded
        if self._model is not None:
            return True

        # Thread-safe loading with double-checked locking
        with self._model_lock:
            if self._model is not None:
                return True

            model_path = self._get_model_path()

            if not model_path.exists():
                self._last_error = f"Model not found: {model_path}"
                self._logger.error(self._last_error)
                return False

            try:
                # CUDA is used automatically when available - no explicit flag needed
                # pywhispercpp will use ggml-cuda backend if built with CUDA support
                self._model = _Model(str(model_path))
                self._last_error = None

                device_str = "GPU" if (self.use_gpu and _cuda_supported) else "CPU"
                self._logger.info(
                    f"Loaded {self.model_name} model on {device_str} with {self.n_threads} threads"
                )
                return True

            except RuntimeError as e:
                error_msg = str(e)
                if "out of memory" in error_msg.lower():
                    self._last_error = (
                        f"Not enough memory for {self.model_name} model. Try a smaller model."
                    )
                else:
                    self._last_error = f"Runtime error: {error_msg}"
                self._logger.exception("Failed to load Whisper model")
                return False

            except OSError as e:
                error_msg = str(e)
                if "no space" in error_msg.lower():
                    self._last_error = "Not enough disk space for model"
                else:
                    self._last_error = f"File system error: {error_msg}"
                self._logger.exception("Failed to load Whisper model")
                return False

            except Exception as e:
                self._last_error = f"Failed to load model: {e}"
                self._logger.exception("Failed to load Whisper model")
                return False

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio to text.

        Args:
            audio: Audio samples as numpy array (mono, 16kHz expected)
            sample_rate: Sample rate (should be 16000 for Whisper)

        Returns:
            Transcribed text or empty string on error.
        """
        if not self.load_model():
            return ""
        try:
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            # translate=False keeps original language (no English translation)
            # language="auto" enables automatic language detection
            segments = self._model.transcribe(audio, translate=False, language="auto")
            text = " ".join(s.text.strip() for s in segments)
            return text.strip()

        except Exception:
            self._logger.exception("Whisper transcription failed")
            return ""
