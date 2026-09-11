"""Nemotron STT engine: NVIDIA Nemotron-3.5-ASR-Streaming-0.6B on onnxruntime.

The model is k2-fsa's ONNX export (int8, 1120 ms chunks) of NVIDIA's
cache-aware FastConformer-RNNT. CLD transcribes a finished recording, so
``_decode`` runs NeMo's streaming loop over the whole buffer, CPU-only:

- Features: NeMo's log-mel front end (``_features``).
- Chunks: 121-frame encoder windows (9 cached frames + 112 new) that step by
  112 frames. 16 zero frames in front put the windows on NeMo's chunk grid,
  whose first chunk is 105 frames.
- End of stream: the recording's last chunk is filled with silence, and one
  more short chunk of 4 new frames goes in with its true length. A partial
  final chunk is how the model learns the utterance is over, and it closes the
  text with terminal punctuation and a language tag. sherpa-onnx 1.13.7 pads
  the last chunk to a full window instead, and with this export the final
  period never comes.
- Decoding: greedy RNN-T, at most 10 symbols per frame. Language tags such as
  ``<en-US>`` are dropped from the text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Optional

import numpy as np

from cld.engines._timeout import TimeoutRunner, FuturesTimeoutError

_ort_available = False
_ort = None
_import_error = None

try:
    import onnxruntime as _ort
    _ort_available = True
except Exception as e:  # pragma: no cover - exercised only without the wheel
    _import_error = f"{type(e).__name__}: {e}"


_SAMPLE_RATE = 16000
_HOP = 160  # 10 ms feature hop
_LEAD_FRAMES = 16  # zero frames that align our windows with NeMo's 105-frame first chunk
_FINAL_FRAMES = 4  # new frames in the short closing chunk
_SILENCE = float(np.log(2.0 ** -24))  # log-mel value of digital silence
_MAX_SYMBOLS = 10  # per encoder frame, as in NeMo and sherpa-onnx greedy search
_LANG_TAG = re.compile(r"<[a-z]{2,3}(-[A-Z]{2})?>")


def _mel_filters(n_fft: int = 512, n_mels: int = 128) -> np.ndarray:
    """Slaney mel filterbank over 0-8000 Hz, equal to librosa.filters.mel(norm="slaney")."""
    logstep = np.log(6.4) / 27.0

    def to_mel(hz):
        return np.where(hz >= 1000, 15.0 + np.log(np.maximum(hz, 1e-10) / 1000) / logstep, hz * 3 / 200)

    def to_hz(mel):
        return np.where(mel >= 15.0, 1000 * np.exp(logstep * (mel - 15.0)), mel * 200 / 3)

    fft_hz = np.linspace(0, _SAMPLE_RATE / 2, n_fft // 2 + 1)
    mel_hz = to_hz(np.linspace(to_mel(0.0), to_mel(_SAMPLE_RATE / 2), n_mels + 2))
    ramps = mel_hz[:, None] - fft_hz[None, :]
    widths = np.diff(mel_hz)
    tri = np.maximum(0, np.minimum(-ramps[:-2] / widths[:-1, None], ramps[2:] / widths[1:, None]))
    return (tri * (2.0 / (mel_hz[2:] - mel_hz[:-2]))[:, None]).astype(np.float32)


_MEL = _mel_filters()
# torch.hann_window(400, periodic=False), centred in the 512-point FFT frame.
_WINDOW = np.zeros(512, np.float32)
_WINDOW[56:456] = np.hanning(400)


def _features(audio: np.ndarray) -> np.ndarray:
    """NeMo log-mel features, shape (frames, 128).

    Preemphasis 0.97, 25 ms Hann window, 10 ms hop, 512-point FFT, power
    spectrum, Slaney mel, log(x + 2**-24), no normalization. Matches the
    Transformers NemotronAsrStreamingFeatureExtractor frame for frame: centred
    STFT with zero padding, and its masked last frame is left out.
    """
    # ponytail: one FFT over the whole recording, ~0.5 GB peak for 10 minutes
    # of audio; process it in blocks if recordings ever get that long.
    x = np.concatenate([audio[:1], audio[1:] - 0.97 * audio[:-1]])
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, 256), 512)[::_HOP]
    power = np.abs(np.fft.rfft(frames[: len(audio) // _HOP] * _WINDOW, axis=1)).astype(np.float32) ** 2
    return np.log(power @ _MEL.T + 2.0 ** -24).astype(np.float32)


def _prompt_id(prompts: dict, language: str, auto_id: int) -> int:
    """Language code -> prompt id. A bare code such as "ja" matches "ja-JP", as in sherpa-onnx."""
    if language in prompts:
        return prompts[language]
    for key in sorted(prompts):
        if key.split("-")[0] == language:
            return prompts[key]
    return auto_id


class _Model:
    """The three ONNX sessions, plus what the decode loop reads from their metadata."""

    def __init__(self, tokens, encoder, decoder, joiner, n_threads: int):
        opts = _ort.SessionOptions()
        opts.intra_op_num_threads = n_threads
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3

        def session(path):
            return _ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])

        self.encoder, self.decoder, self.joiner = session(encoder), session(decoder), session(joiner)
        meta = self.encoder.get_modelmeta().custom_metadata_map

        def dims(name):
            return (1,) + tuple(int(meta[f"{name}_dim{i}"]) for i in (1, 2, 3))

        self.window = int(meta["window_size"])  # 121 = 9 cached + 112 new frames
        self.shift = int(meta["chunk_shift"])  # 112
        self.channel_cache = dims("cache_last_channel")
        self.time_cache = dims("cache_last_time")
        self.lstm = (int(meta["pred_rnn_layers"]), 1, int(meta["pred_hidden"]))
        self.prompts = json.loads(meta["prompt_dictionary"])
        self.auto_prompt = int(meta["auto_prompt_id"])
        # The decoder's input names are ONNX export noise ("states.1", "onnx::Slice_3").
        self.decoder_inputs = [i.name for i in self.decoder.get_inputs()]
        self.joiner_inputs = [i.name for i in self.joiner.get_inputs()]
        lines = tokens.read_text(encoding="utf-8").splitlines()
        self.symbols = [line.rsplit(" ", 1)[0] for line in lines]
        self.blank = len(self.symbols) - 1  # <blk> is the last token

    def predict(self, token: int, state):
        """Prediction network on one token -> (output, next LSTM state)."""
        feed = (np.array([[token]], np.int32), np.array([1], np.int32), *state)
        out = self.decoder.run(None, dict(zip(self.decoder_inputs, feed)))
        return out[0], (out[2], out[3])

    def join(self, frame, predicted) -> int:
        """Most likely token for one encoder frame."""
        feed = dict(zip(self.joiner_inputs, (frame, predicted)))
        return int(self.joiner.run(None, feed)[0].argmax())


class NemotronEngine:
    """Nemotron cache-aware streaming transducer on onnxruntime, used in batch mode."""

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

        self._model: Optional[_Model] = None
        self._model_lock = threading.Lock()
        # Held for the whole duration of a transcribe() so unload_model()
        # (sleep/wake, engine switch) can't free the model mid-decode.
        self._transcribe_lock = threading.Lock()
        self._runner = TimeoutRunner(thread_name_prefix="cld-nemotron")
        self._logger = logging.getLogger(__name__)
        self._last_error: Optional[str] = None

    def is_available(self) -> bool:
        return _ort_available

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
            self._last_error = f"onnxruntime not installed: {_import_error}"
            return False

        if self._model is not None:
            return True

        with self._model_lock:
            if self._model is not None:
                return True

            files = self._resolve_files()
            if files is None:
                self._logger.error(self._last_error)
                return False

            try:
                self._model = _Model(*files, n_threads=self.n_threads)
                self._last_error = None
                self._logger.info(
                    "Loaded Nemotron model '%s' on CPU with %d threads (lang=%s)",
                    self.model_name, self.n_threads, self.language,
                )
                return True
            except Exception as e:
                self._last_error = f"Failed to load Nemotron model: {e}"
                self._logger.exception("Failed to load Nemotron model")
                self._model = None
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
                if self._model is not None:
                    self._logger.info("Unloading Nemotron model")
                    self._model = None
        finally:
            if clean:
                self._transcribe_lock.release()
        return clean

    def _decode(self, audio: np.ndarray, sample_rate: int) -> str:
        """Streaming encoder over the whole recording, then greedy RNN-T search."""
        m = self._model
        if m is None:
            return ""
        if sample_rate != _SAMPLE_RATE:
            raise ValueError(f"Nemotron needs {_SAMPLE_RATE} Hz audio, got {sample_rate} Hz")

        feats = _features(audio)
        lead = np.zeros((_LEAD_FRAMES, feats.shape[1]), np.float32)
        # Silence up to the end of the last chunk, then a closing chunk of
        # _FINAL_FRAMES new frames. The model writes the closing punctuation
        # and language tag on that short chunk far more reliably than on
        # whatever partial chunk the recording happens to end with.
        n = _LEAD_FRAMES + len(feats)
        tail_len = (m.window - m.shift + _FINAL_FRAMES - n) % m.shift
        tail = np.full((tail_len, feats.shape[1]), _SILENCE, np.float32)
        feats = np.concatenate([lead, feats, tail])

        prompt = np.array([_prompt_id(m.prompts, self.language, m.auto_prompt)], np.int64)
        caches = [np.zeros(m.channel_cache, np.float32), np.zeros(m.time_cache, np.float32),
                  np.zeros(1, np.int64)]
        predicted, state = m.predict(m.blank, (np.zeros(m.lstm, np.float32),) * 2)
        tokens = []
        start = 0
        while True:
            last = len(feats) - start <= m.window
            chunk = feats[start:start + m.window]
            enc, enc_len, *caches = m.encoder.run(None, {
                "audio_signal": np.ascontiguousarray(chunk.T[None]),
                "length": np.array([len(chunk)], np.int64),
                "cache_last_channel": caches[0],
                "cache_last_time": caches[1],
                "cache_last_channel_len": caches[2],
                "prompt_index": prompt,
            })
            for t in range(int(enc_len[0])):
                frame = np.ascontiguousarray(enc[:, :, t:t + 1])
                for _ in range(_MAX_SYMBOLS):
                    y = m.join(frame, predicted)
                    if y == m.blank:
                        break
                    tokens.append(y)
                    predicted, state = m.predict(y, state)
            if last:
                break
            start += m.shift

        text = "".join(s for s in (m.symbols[t] for t in tokens) if not _LANG_TAG.fullmatch(s))
        return " ".join(text.replace("▁", " ").split())

    def open_stream(self, sample_rate: int = 16000) -> None:
        """No live typing (see STTEngine): its text while the user spoke was too rough to type."""
        return None

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
