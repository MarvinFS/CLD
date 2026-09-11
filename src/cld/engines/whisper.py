"""Whisper STT engine using pywhispercpp (whisper.cpp bindings)."""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import List, Optional

import numpy as np

from cld.engines._timeout import TimeoutRunner, FuturesTimeoutError
from cld.model_manager import WHISPER_MODELS

_whisper_available = False
_Model = None
_import_error = None
_cuda_supported = False
_vulkan_supported = False
_system_info = ""
_has_gpu_init_params = False  # Whether whisper_init_from_file_with_params exists

try:
    from pywhispercpp.model import Model as _Model
    _whisper_available = True
    # Check GPU backends via system info and DLL presence
    # Vulkan is preferred (universal), CUDA is NVIDIA-only fallback
    try:
        import _pywhispercpp as _pw
        _system_info = _pw.whisper_print_system_info()
        _cuda_supported = "CUDA" in _system_info
        # Check Vulkan support: system_info or DLL presence
        # Note: whisper_print_system_info() doesn't report Vulkan even when available,
        # so we primarily check for the DLL
        _vulkan_supported = "Vulkan" in _system_info
        if not _vulkan_supported:
            # Check for ggml-vulkan*.dll (with or without hash suffix from delvewheel)
            import importlib.util
            spec = importlib.util.find_spec("_pywhispercpp")
            if spec and spec.origin:
                site_packages = Path(spec.origin).parent
                # Check both plain name and hash-suffixed name (from delvewheel)
                vulkan_dlls = list(site_packages.glob("ggml-vulkan*.dll"))
                _vulkan_supported = len(vulkan_dlls) > 0
        # Check if GPU device selection function exists (custom build)
        _has_gpu_init_params = hasattr(_pw, 'whisper_init_from_file_with_params')
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


def has_gpu_device_selection() -> bool:
    """Check if pywhispercpp supports GPU device selection.

    Returns True if whisper_init_from_file_with_params function exists,
    which is required for use_gpu and gpu_device parameters to work.
    Standard pywhispercpp silently falls back to CPU if this is missing.
    """
    return _has_gpu_init_params


def _detected_language(model) -> str:
    """The language whisper.cpp detected in the model's last language="auto" pass."""
    return _pw.whisper_lang_str(_pw.whisper_full_lang_id(model._ctx))


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
        - medium-q5_0: ~539MB, quantized, translates to English (default)
        - large-v3-turbo-q5_0: ~574MB, most accurate, fastest on a GPU, can't translate to English
    """

    def __init__(
        self,
        model_name: str = "medium-q5_0",
        n_threads: Optional[int] = None,
        use_gpu: Optional[bool] = None,
        gpu_device: int = -1,
        transcription_timeout: int = 120,
        translate_to_english: bool = False,
    ):
        self.model_name = model_name
        # Use all cores except core 0 (leaves core 0 for system responsiveness)
        cpu_count = os.cpu_count() or 8
        self.n_threads = n_threads or max(4, cpu_count - 2)
        self.gpu_device = gpu_device
        self._cpu_count = cpu_count
        self.transcription_timeout = transcription_timeout
        # A saved Translate to English setting never reaches a model that can't translate.
        can_translate = WHISPER_MODELS.get(model_name, {}).get("translates", True)
        self.translate_to_english = translate_to_english and can_translate
        self._model: Optional[object] = None
        self._model_lock = threading.Lock()
        # Held for the entire duration of an in-flight transcribe() call so
        # that unload_model() (driven by sleep/wake recovery) cannot delete
        # the native model while whisper.cpp is still using it.
        self._transcribe_lock = threading.Lock()
        # Long-lived single-worker runner enforcing a real wall-clock timeout
        # (see engines/_timeout.py). Shared pattern with NemotronEngine.
        self._runner = TimeoutRunner(thread_name_prefix="cld-transcribe")
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

        # Warn if GPU requested but device selection not available
        if self.use_gpu and not has_gpu_device_selection():
            self._logger.warning(
                "GPU requested but whisper_init_from_file_with_params not found. "
                "GPU device selection (use_gpu/gpu_device params) will be ignored. "
                "Rebuild pywhispercpp with GPU support to enable this feature."
            )

        backend = get_gpu_backend() or "CPU"
        self._logger.info("WhisperEngine: model=%s, threads=%d, backend=%s (use_gpu=%s, gpu_device=%d)",
                         model_name, self.n_threads, backend, self.use_gpu, self.gpu_device)
        self._logger.info("System info: %s", _system_info if _system_info else "(not available)")

    def is_available(self) -> bool:
        return _whisper_available

    def unload_model(self, wait_timeout: float = 30.0) -> bool:
        """Unload the model and free GPU/Vulkan resources.

        Must be called before system sleep to prevent native segfaults from
        corrupted Vulkan handles on wake. Call ``load_model()`` to reload.

        Serialization vs ``transcribe()``: ``_transcribe_lock`` is held for
        the entire duration of an active inference call. We acquire that
        lock here (with a bounded wait) so we never delete the native model
        object while a worker thread is still calling into whisper.cpp,
        which previously caused use-after-free crashes during sleep/wake.

        Args:
            wait_timeout: Max seconds to wait for an in-flight transcription
                to finish before forcing the unload.

        Returns:
            True if the model was unloaded cleanly; False if we had to
            proceed without waiting (transcription thread did not release
            the lock in time).
        """
        clean = self._transcribe_lock.acquire(timeout=wait_timeout)
        try:
            if not clean:
                self._logger.warning(
                    "Transcription did not finish within %.1fs; unloading anyway. "
                    "Native crash is possible if inference is still running.",
                    wait_timeout,
                )
            with self._model_lock:
                if self._model is not None:
                    self._logger.info("Unloading Whisper model (freeing GPU resources)")
                    try:
                        del self._model
                    except Exception:
                        pass
                    self._model = None
        finally:
            if clean:
                self._transcribe_lock.release()
        return clean

    def get_last_error(self) -> Optional[str]:
        """Get the last error message."""
        return self._last_error

    def _set_cpu_affinity_exclude_core0(self) -> None:
        """Set CPU affinity to all cores except core 0 for system responsiveness.

        On systems with SMT/HyperThreading, core 0 has logical processors 0 and 1.
        We exclude both to leave the first physical core free.
        """
        try:
            import psutil
            process = psutil.Process()
            # Get all available CPUs
            all_cpus = list(range(self._cpu_count))
            # Exclude logical processors 0 and 1 (physical core 0 on SMT systems)
            # On non-SMT systems, just exclude CPU 0
            if self._cpu_count > 4:
                # SMT system: exclude CPUs 0 and 1 (first physical core)
                allowed_cpus = [cpu for cpu in all_cpus if cpu >= 2]
            else:
                # Small system: just exclude CPU 0
                allowed_cpus = [cpu for cpu in all_cpus if cpu >= 1]

            if allowed_cpus:
                process.cpu_affinity(allowed_cpus)
                self._logger.debug("CPU affinity set to cores: %s (excluded core 0)", allowed_cpus)
        except ImportError:
            self._logger.debug("psutil not available, skipping CPU affinity")
        except Exception as e:
            self._logger.debug("Failed to set CPU affinity: %s", e)

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
                #
                # use_gpu and gpu_device are named params on the custom Vulkan build
                # of pywhispercpp (not passed via **params to _set_params).
                # If stock PyPI version is installed (missing these params), fall back
                # to n_threads only to avoid AttributeError + native segfault.
                import inspect
                model_sig = inspect.signature(_Model.__init__)
                model_kwargs = {"n_threads": self.n_threads}
                if "use_gpu" in model_sig.parameters:
                    model_kwargs["use_gpu"] = self.use_gpu
                    if "gpu_device" in model_sig.parameters:
                        model_kwargs["gpu_device"] = self.gpu_device

                self._model = _Model(str(model_path), **model_kwargs)
                self._last_error = None

                # Verify actual backend from system_info (not just config)
                backend_in_system_info = get_gpu_backend()
                has_device_selection = has_gpu_device_selection()

                if self.use_gpu:
                    if backend_in_system_info and has_device_selection:
                        device_str = f"GPU ({backend_in_system_info}, device={self.gpu_device})"
                    elif backend_in_system_info:
                        # GPU backend available but no device selection
                        device_str = f"GPU ({backend_in_system_info}, auto-selected - device param ignored)"
                    else:
                        # Requested GPU but system_info shows no GPU backend
                        device_str = "CPU (GPU requested but not detected in system_info)"
                        self._logger.warning(
                            "use_gpu=True but no GPU backend in system_info. "
                            "Actual inference will use CPU. System info: %s",
                            _system_info
                        )
                else:
                    device_str = "CPU"

                self._logger.info(
                    "Loaded %s model on %s with %d threads",
                    self.model_name, device_str, self.n_threads
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

        Snapshots ``self._model`` at entry so an in-flight call cannot be
        torn down mid-segment by ``unload_model()``. The caller
        (``transcribe()``) already holds ``_transcribe_lock``, which
        ``unload_model()`` also acquires, so this is belt-and-suspenders.

        Args:
            audio: Audio samples as numpy array (mono, float32, 16kHz expected)

        Returns:
            Transcribed text.
        """
        model = self._model
        if model is None:
            return ""
        segments = model.transcribe(audio, translate=self.translate_to_english, language="auto")
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
        """Transcribe a single audio chunk with a real wall-clock timeout."""
        try:
            return self._runner.run(
                lambda: self._transcribe_internal(audio), self.transcription_timeout
            )
        except FuturesTimeoutError:
            self._logger.warning(
                "Chunk transcription timed out after %d seconds.",
                self.transcription_timeout,
            )
            self._last_error = f"Transcription timed out after {self.transcription_timeout}s"
            # The stuck worker is abandoned and the executor replaced inside
            # TimeoutRunner.run(); the native whisper.cpp call cannot be
            # interrupted from Python but won't block future transcriptions.
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

    def open_stream(self, sample_rate: int = 16000) -> Optional[_Stream]:
        """Live typing on a GPU (see STTEngine). None on the CPU, where one pass over a
        few seconds of speech takes longer than the speech itself."""
        if not self.use_gpu or self._model is None or sample_rate != 16000:
            return None
        return _Stream(self)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio to text with chunking for long recordings.

        Holds ``_transcribe_lock`` for the entire call so concurrent
        ``unload_model()`` (driven by sleep/wake recovery) cannot delete the
        native model while inference is still using it.

        Args:
            audio: Audio samples as numpy array (mono, 16kHz expected)
            sample_rate: Sample rate (should be 16000 for Whisper)

        Returns:
            Transcribed text or empty string on error/timeout.
        """
        with self._transcribe_lock:
            if not self.load_model():
                return ""

            if not self.use_gpu:
                self._set_cpu_affinity_exclude_core0()

            try:
                if audio.dtype != np.float32:
                    audio = audio.astype(np.float32)

                chunks = self._chunk_audio(audio, sample_rate)

                if len(chunks) == 1:
                    return self._transcribe_with_timeout(chunks[0])

                duration_seconds = len(audio) // sample_rate
                self._logger.info(
                    "Transcribing %d chunks (%d seconds total)", len(chunks), duration_seconds
                )

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


# Whole-word Whisper annotations such as [BLANK_AUDIO], (music) or *laughs*.
_ARTIFACT_WORD = re.compile(r"^[\[(*].*[\])*]$")


class _Stream:
    """Live Whisper: a worker re-decodes the recording every _STEP_SAMPLES of new audio.

    A word is committed once a pass agrees on it with a pass that heard at least
    _AGREE_SAMPLES less audio (LocalAgreement-2, as in ufal/whisper_streaming, whose
    passes are also about a second apart). Back-to-back passes hear nearly the same
    audio and agree on almost anything. The rest of the latest pass is tentative.

    The language is detected once and pinned, so later passes skip detection. Past
    _TRIM_SAMPLES the passes drop the audio of leading segments whose words are all
    committed, and those words prompt the passes that follow. finish() transcribes the
    whole recording through the batch path, without the passes' text as context.
    """

    _MIN_SAMPLES = 16000  # passes on less than 1 s of audio make words up
    _STEP_SAMPLES = 4800
    _AGREE_SAMPLES = 16000
    _PIN_SAMPLES = 2 * 16000  # the language is pinned on the first pass with this much audio
    _TRIM_SAMPLES = 20 * 16000

    def __init__(self, engine: WhisperEngine):
        self._engine = engine
        self._logger = engine._logger
        self._lock = threading.Lock()  # guards everything below
        self._recording: List[np.ndarray] = []
        self._total = 0  # samples recorded
        self._audio = np.zeros(0, np.float32)  # what the passes decode: the recording since the last trim
        self._frozen: List[str] = []  # words of the trimmed audio
        self._committed: List[str] = []  # committed words of self._audio
        self._passes: List[tuple] = []  # (samples of self._audio heard, words), latest last
        self._language = "auto"
        self._prompt = ""
        self._grew = threading.Event()
        self._closed = False
        self._worker = threading.Thread(target=self._run, name="cld-whisper-live", daemon=True)
        self._worker.start()

    def feed(self, audio: np.ndarray) -> tuple[str, str]:
        audio = np.asarray(audio, np.float32).ravel()
        with self._lock:
            self._recording.append(audio)
            self._total += len(audio)
            self._audio = np.concatenate([self._audio, audio])
        self._grew.set()
        return self._hypothesis()

    def finish(self) -> str:
        """Stop the passes and transcribe the whole recording as the batch path does."""
        self._closed = True
        self._grew.set()
        self._worker.join(self._engine.transcription_timeout)
        with self._lock:
            audio = np.concatenate(self._recording) if self._recording else None
        # whisper.cpp keeps each decode's text as context for the next one unless no_context
        # is set, and a decode whose context already holds the text of its audio skips it.
        # The passes just read this audio, so the final decode runs without that context.
        self._set_params(no_context=True)
        try:
            return self._engine.transcribe(audio, 16000) if audio is not None else ""
        finally:
            self._set_params(no_context=False)

    def _hypothesis(self) -> tuple[str, str]:
        with self._lock:
            last = self._passes[-1][1] if self._passes else []
            return " ".join(self._frozen + self._committed), " ".join(last[len(self._committed):])

    def _run(self) -> None:
        decoded = 0
        try:
            while True:
                self._grew.wait()
                self._grew.clear()
                if self._closed:
                    return
                with self._lock:
                    audio, total = self._audio, self._total
                if len(audio) < self._MIN_SAMPLES or total - decoded < self._STEP_SAMPLES:
                    continue
                decoded = total
                if not self._pass(audio):
                    return
        except Exception:
            self._logger.exception("Live Whisper pass failed; the final text comes from finish()")

    def _pass(self, audio: np.ndarray) -> bool:
        """One pass over audio, a snapshot of self._audio. False once the model is unloaded."""
        segments = self._decode(audio)
        if segments is None:
            return False
        words = [w for seg, _ in segments for w in seg]
        heard = len(audio)
        with self._lock:
            ref = next((w for n, w in reversed(self._passes) if n <= heard - self._AGREE_SAMPLES), None)
            # ponytail: agreement on word position; a word the model inserts before the
            # committed text shows up doubled until finish(). Align on timestamps if it bites.
            agreed = len(os.path.commonprefix([ref, words])) if ref is not None else 0
            if agreed > len(self._committed):
                self._committed += words[len(self._committed):agreed]
            self._passes = [p for p in self._passes if p[0] > heard - 2 * self._AGREE_SAMPLES]
            self._passes.append((heard, words))
            if heard > self._TRIM_SAMPLES:
                self._trim(segments, heard, words)
        return True

    def _trim(self, segments, heard: int, words: List[str]) -> None:
        done = cut = 0
        for seg, t1 in segments[:-1]:
            if done + len(seg) > len(self._committed):
                break
            done, cut = done + len(seg), int(t1) * 160  # t1 is in 10 ms steps
        if cut:
            self._audio = self._audio[cut:]
            self._frozen += self._committed[:done]
            self._committed = self._committed[done:]
            self._passes = [(heard - cut, words[done:])]
            self._prompt = " ".join(self._frozen)[-200:]

    def _decode(self, audio: np.ndarray):
        """[(words, end time)] per segment, or None when the model is unloaded."""
        engine = self._engine
        with engine._transcribe_lock:
            model = engine._model
            if model is None:
                return None
            segments = model.transcribe(audio, translate=engine.translate_to_english, language=self._language,
                                        no_context=True, initial_prompt=self._prompt)
            if self._language == "auto" and len(audio) >= self._PIN_SAMPLES:
                self._language = _detected_language(model)
        return [([w for w in s.text.split() if not _ARTIFACT_WORD.match(w)], s.t1) for s in segments]

    def _set_params(self, no_context: bool) -> None:
        """pywhispercpp keeps every param a call sets. The batch path expects no_context=False
        and no initial prompt, and only sets the language and translate flag itself."""
        with self._engine._transcribe_lock:
            model = self._engine._model
            if model is not None:
                model._set_params({"no_context": no_context, "initial_prompt": ""})
