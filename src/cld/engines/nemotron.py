"""Nemotron STT engine using sherpa-onnx (k2-fsa).

NVIDIA Nemotron-3.5-ASR-Streaming-0.6B exported to ONNX (int8) and run through
sherpa-onnx as a cache-aware streaming transducer. CLD uses it in *batch* mode:
feed the whole recording into one stream, flush, and read the final result.
CPU-only in v1 (live streaming deferred).

Real Python API (probed against sherpa_onnx 1.13.3, not the C++ PR names):
    rec = OnlineRecognizer.from_transducer(tokens, encoder, decoder, joiner,
                                           num_threads=N, provider="cpu")
    stream = rec.create_stream()
    stream.set_option("language", "<code>")      # per-stream; "en"/"ru"/"auto"/...
    stream.accept_waveform(16000, samples_f32)
    stream.input_finished()
    while rec.is_ready(stream): rec.decode_stream(stream)
    text = rec.get_result(stream)
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import numpy as np

from cld.engines._timeout import TimeoutRunner, FuturesTimeoutError

_sherpa_available = False
_sherpa = None
_import_error = None

try:
    import sherpa_onnx as _sherpa  # noqa: F401
    _sherpa_available = True
except Exception as e:  # pragma: no cover - exercised only without the wheel
    _import_error = f"{type(e).__name__}: {e}"


# Trailing silence appended to the stream so the last chunk flushes through the
# cache-aware encoder before we read the result. MUST exceed the model's chunk
# size (1120 ms) or the final chunk never decodes and the last word is dropped
# (observed: "...pieces of gold." truncated to "...pieces of co"). 2.0 s gives
# a full chunk plus margin.
_TRAILING_SILENCE_S = 2.0


class NemotronEngine:
    """sherpa-onnx Nemotron streaming-transducer engine, used in batch mode."""

    def __init__(
        self,
        model_name: str,
        language: str = "auto",
        n_threads: Optional[int] = None,
        transcription_timeout: int = 120,
    ):
        self.model_name = model_name
        self.language = language or "auto"
        cpu_count = os.cpu_count() or 8
        # CPU-only: leave core 0 for the system, like WhisperEngine.
        self.n_threads = n_threads or max(4, cpu_count - 2)
        self._cpu_count = cpu_count
        self.transcription_timeout = transcription_timeout

        self._recognizer: Optional[object] = None
        self._model_lock = threading.Lock()
        # Held for the whole duration of a transcribe() so unload_model()
        # (sleep/wake, engine switch) can't free the recognizer mid-decode.
        self._transcribe_lock = threading.Lock()
        self._runner = TimeoutRunner(thread_name_prefix="cld-nemotron")
        self._logger = logging.getLogger(__name__)
        self._last_error: Optional[str] = None

    def is_available(self) -> bool:
        return _sherpa_available

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def _set_cpu_affinity_exclude_core0(self) -> None:
        # ponytail: mirrors WhisperEngine's affinity (15 lines); not worth a
        # shared module, both engines are CPU-bound and want core 0 free.
        try:
            import psutil
            process = psutil.Process()
            all_cpus = list(range(self._cpu_count))
            if self._cpu_count > 4:
                allowed = [c for c in all_cpus if c >= 2]
            else:
                allowed = [c for c in all_cpus if c >= 1]
            if allowed:
                process.cpu_affinity(allowed)
        except ImportError:
            pass
        except Exception as e:
            self._logger.debug("Failed to set CPU affinity: %s", e)

    def _resolve_files(self):
        """Resolve (tokens, encoder, decoder, joiner) absolute paths.

        Returns a tuple of 4 paths, or None with ``_last_error`` set if the
        model isn't installed/valid. Defers all version/marker resolution to
        ModelManager so the engine never reimplements the pointer scheme.
        """
        from cld.model_manager import ModelManager, get_spec

        try:
            spec = get_spec("nemotron", self.model_name)
        except KeyError:
            self._last_error = f"Unknown Nemotron model: {self.model_name}"
            return None

        mm = ModelManager()
        model_dir = mm.resolve_nemotron_dir(self.model_name)
        if model_dir is None:
            self._last_error = (
                f"Nemotron model '{self.model_name}' is not installed. "
                "Download it from the model dialog."
            )
            return None

        files = (
            model_dir / spec["tokens"],
            model_dir / spec["encoder"],
            model_dir / spec["decoder"],
            model_dir / spec["joiner"],
        )
        for f in files:
            if not f.exists():
                self._last_error = f"Nemotron model file missing: {f.name}"
                return None
        return files

    def load_model(self) -> bool:
        if not self.is_available():
            self._last_error = f"sherpa-onnx not installed: {_import_error}"
            return False

        if self._recognizer is not None:
            return True

        with self._model_lock:
            if self._recognizer is not None:
                return True

            files = self._resolve_files()
            if files is None:
                self._logger.error(self._last_error)
                return False
            tokens, encoder, decoder, joiner = files

            try:
                self._recognizer = _sherpa.OnlineRecognizer.from_transducer(
                    tokens=str(tokens),
                    encoder=str(encoder),
                    decoder=str(decoder),
                    joiner=str(joiner),
                    num_threads=self.n_threads,
                    provider="cpu",
                )
                self._last_error = None
                self._logger.info(
                    "Loaded Nemotron model '%s' on CPU with %d threads (lang=%s)",
                    self.model_name, self.n_threads, self.language,
                )
                return True
            except Exception as e:
                self._last_error = f"Failed to load Nemotron model: {e}"
                self._logger.exception("Failed to load Nemotron model")
                self._recognizer = None
                return False

    def unload_model(self, wait_timeout: float = 30.0) -> bool:
        clean = self._transcribe_lock.acquire(timeout=wait_timeout)
        try:
            if not clean:
                self._logger.warning(
                    "Transcription did not finish within %.1fs; unloading anyway.",
                    wait_timeout,
                )
            with self._model_lock:
                if self._recognizer is not None:
                    self._logger.info("Unloading Nemotron model")
                    try:
                        del self._recognizer
                    except Exception:
                        pass
                    self._recognizer = None
        finally:
            if clean:
                self._transcribe_lock.release()
        return clean

    def _decode(self, audio: np.ndarray, sample_rate: int) -> str:
        """Batch decode: one stream, whole buffer, trailing silence, drain."""
        rec = self._recognizer
        if rec is None:
            return ""
        stream = rec.create_stream()
        # Per-stream language. config.validate() already clamps to a supported
        # value or "auto", so this is safe to pass through.
        try:
            stream.set_option("language", self.language)
        except Exception as e:
            self._logger.debug("set_option language=%s failed: %s", self.language, e)
        stream.accept_waveform(sample_rate, audio)
        silence = np.zeros(int(_TRAILING_SILENCE_S * sample_rate), dtype=np.float32)
        stream.accept_waveform(sample_rate, silence)
        stream.input_finished()
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        return (rec.get_result(stream) or "").strip()

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        with self._transcribe_lock:
            if not self.load_model():
                return ""

            self._set_cpu_affinity_exclude_core0()
            try:
                if audio.dtype != np.float32:
                    audio = audio.astype(np.float32)
                return self._runner.run(
                    lambda: self._decode(audio, sample_rate),
                    self.transcription_timeout,
                )
            except FuturesTimeoutError:
                self._logger.warning(
                    "Transcription timed out after %d seconds.", self.transcription_timeout
                )
                self._last_error = (
                    f"Transcription timed out after {self.transcription_timeout}s"
                )
                return ""
            except Exception:
                self._logger.exception("Nemotron transcription failed")
                return ""
