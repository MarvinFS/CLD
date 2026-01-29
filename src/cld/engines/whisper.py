"""Whisper STT engine using pywhispercpp (whisper.cpp bindings)."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import List, Optional

import numpy as np

_whisper_available = False
_Model = None
_import_error = None
_cuda_supported = False
_vulkan_supported = False
_system_info = ""

try:
    from pywhispercpp.model import Model as _Model
    _whisper_available = True
    # Check GPU backends via system info and DLL presence
    # Vulkan is preferred (universal), CUDA is NVIDIA-only fallback
    try:
        import _pywhispercpp as _pw
        _system_info = _pw.whisper_print_system_info()
        _cuda_supported = "CUDA" in _system_info
        # Check Vulkan support: either in system_info or DLL exists
        _vulkan_supported = "Vulkan" in _system_info
        if not _vulkan_supported:
            # Also check for ggml-vulkan.dll in site-packages (pre-built binaries)
            import importlib.util
            spec = importlib.util.find_spec("_pywhispercpp")
            if spec and spec.origin:
                vulkan_dll = Path(spec.origin).parent / "ggml-vulkan.dll"
                _vulkan_supported = vulkan_dll.exists()
    except Exception:
        pass
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


def is_vulkan_supported() -> bool:
    """Check if pywhispercpp was built with Vulkan support."""
    return _vulkan_supported


def is_gpu_supported() -> bool:
    """Check if any GPU backend is available (Vulkan or CUDA)."""
    return _vulkan_supported or _cuda_supported


def get_gpu_backend() -> Optional[str]:
    """Get the active GPU backend name.

    Returns:
        "Vulkan" (preferred, universal), "CUDA" (NVIDIA-only), or None if CPU-only.
    """
    if _vulkan_supported:
        return "Vulkan"
    if _cuda_supported:
        return "CUDA"
    return None


def get_system_info() -> str:
    """Get the pywhispercpp system info string."""
    return _system_info


# Audio chunking constants for long recordings
CHUNK_DURATION_SECONDS = 60  # Transcribe in 60-second chunks
CHUNK_OVERLAP_SECONDS = 5    # 5-second overlap to preserve context at boundaries


class WhisperEngine:
    """Whisper speech-to-text engine backed by pywhispercpp (whisper.cpp).

    Uses GGML model files. Supports GPU acceleration via:
    - Vulkan backend (universal, ~160MB): Works with NVIDIA, AMD, and Intel GPUs
    - CUDA backend (NVIDIA-only, ~600MB per architecture family): Slightly faster but vendor-locked

    CLD prefers Vulkan for universal GPU support at ~4x smaller distribution size.

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
        gpu_device: int = -1,
        transcription_timeout: int = 120,
    ):
        self.model_name = model_name
        self.n_threads = n_threads or max(4, (os.cpu_count() or 8) - 2)
        self.gpu_device = gpu_device
        self.transcription_timeout = transcription_timeout
        self._model: Optional[object] = None
        self._model_lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._last_error: Optional[str] = None

        # GPU support: auto-detect or use explicit setting
        # Vulkan is preferred (universal), CUDA is fallback (NVIDIA-only)
        gpu_available = is_gpu_supported()
        if use_gpu is None:
            self.use_gpu = gpu_available
        elif use_gpu and not gpu_available:
            self._logger.warning("GPU requested but pywhispercpp has no GPU backend. Using CPU.")
            self.use_gpu = False
        else:
            self.use_gpu = use_gpu

        backend = get_gpu_backend() or "CPU"
        self._logger.info("WhisperEngine: model=%s, threads=%d, backend=%s (use_gpu=%s, gpu_device=%d)",
                         model_name, self.n_threads, backend, self.use_gpu, self.gpu_device)

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
                # GPU backend is used automatically when available
                # Vulkan: universal (NVIDIA/AMD/Intel), CUDA: NVIDIA-only fallback
                # gpu_device: -1 = auto, 0 = first GPU (usually discrete), 1 = second GPU
                self._model = _Model(
                    str(model_path),
                    use_gpu=self.use_gpu,
                    gpu_device=self.gpu_device,
                )
                self._last_error = None

                backend = get_gpu_backend()
                if self.use_gpu and backend:
                    device_str = f"GPU ({backend}, device={self.gpu_device})"
                else:
                    device_str = "CPU"
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

    def _transcribe_internal(self, audio: np.ndarray) -> str:
        """Internal transcription worker (runs in thread pool).

        Args:
            audio: Audio samples as numpy array (mono, float32, 16kHz expected)

        Returns:
            Transcribed text.
        """
        segments = self._model.transcribe(audio, translate=False, language="auto")
        text = " ".join(s.text.strip() for s in segments)
        return text.strip()

    def _chunk_audio(self, audio: np.ndarray, sample_rate: int = 16000) -> List[np.ndarray]:
        """Split audio into overlapping chunks for long recordings.

        Args:
            audio: Full audio array
            sample_rate: Sample rate (default 16kHz)

        Returns:
            List of audio chunks (each ~60 seconds with 5s overlap)
        """
        total_samples = len(audio)
        chunk_samples = CHUNK_DURATION_SECONDS * sample_rate
        overlap_samples = CHUNK_OVERLAP_SECONDS * sample_rate

        # If audio fits in one chunk, return as-is
        if total_samples <= chunk_samples:
            return [audio]

        chunks = []
        start = 0
        while start < total_samples:
            end = min(start + chunk_samples, total_samples)
            chunks.append(audio[start:end])

            # Move start forward by chunk size minus overlap
            start += chunk_samples - overlap_samples

            # Don't create tiny final chunks (< 10 seconds)
            if total_samples - start < sample_rate * 10 and start < total_samples:
                # Extend last chunk to include remaining audio
                if chunks:
                    chunks[-1] = audio[start - (chunk_samples - overlap_samples):]
                break

        return chunks

    def _transcribe_with_timeout(self, audio: np.ndarray) -> str:
        """Transcribe a single audio chunk with timeout protection.

        Args:
            audio: Audio samples as numpy array (mono, float32, 16kHz expected)

        Returns:
            Transcribed text or empty string on timeout.
        """
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._transcribe_internal, audio)
            try:
                return future.result(timeout=self.transcription_timeout)
            except FuturesTimeoutError:
                self._logger.warning(
                    "Chunk transcription timed out after %d seconds.",
                    self.transcription_timeout
                )
                self._last_error = f"Transcription timed out after {self.transcription_timeout}s"
                return ""

    def _join_chunks(self, results: List[str]) -> str:
        """Join chunk transcriptions, handling overlap artifacts.

        The 5-second overlap may cause some words to be duplicated at boundaries.
        This method attempts basic deduplication by detecting repeated word sequences.

        Args:
            results: List of transcribed text from each chunk

        Returns:
            Joined text with overlap deduplication.
        """
        if not results:
            return ""
        if len(results) == 1:
            return results[0]

        joined = results[0]
        for i in range(1, len(results)):
            next_text = results[i]
            if not next_text:
                continue

            joined_words = joined.split()
            next_words = next_text.split()

            # Check for 1-5 word overlap at boundary
            overlap_found = False
            if len(joined_words) >= 3 and len(next_words) >= 3:
                for overlap_len in range(5, 0, -1):
                    if len(joined_words) >= overlap_len and len(next_words) >= overlap_len:
                        if joined_words[-overlap_len:] == next_words[:overlap_len]:
                            # Found overlap, skip duplicate words
                            joined = joined + " " + " ".join(next_words[overlap_len:])
                            overlap_found = True
                            break
            if not overlap_found:
                joined = joined + " " + next_text

        return joined.strip()

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio to text with chunking for long recordings.

        Audio longer than 60 seconds is split into overlapping chunks, transcribed
        independently, then joined with deduplication at boundaries.

        Args:
            audio: Audio samples as numpy array (mono, 16kHz expected)
            sample_rate: Sample rate (should be 16000 for Whisper)

        Returns:
            Transcribed text or empty string on error/timeout.
        """
        if not self.load_model():
            return ""

        try:
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            # Split into chunks for long recordings
            chunks = self._chunk_audio(audio, sample_rate)

            if len(chunks) == 1:
                # Single chunk - use existing timeout logic
                return self._transcribe_with_timeout(chunks[0])

            # Multiple chunks - transcribe each and join
            duration_seconds = len(audio) // sample_rate
            self._logger.info("Transcribing %d chunks (%d seconds total)",
                              len(chunks), duration_seconds)

            results = []
            for i, chunk in enumerate(chunks):
                self._logger.debug("Transcribing chunk %d/%d", i + 1, len(chunks))
                text = self._transcribe_with_timeout(chunk)
                if text:
                    results.append(text)

            return self._join_chunks(results)

        except Exception:
            self._logger.exception("Whisper transcription failed")
            return ""
