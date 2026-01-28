"""Audio recording using sounddevice."""

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np

# Thread-safe atomic float for audio level visualization
_current_level: float = 0.0
_level_lock = threading.Lock()

_SOUNDDEVICE_IMPORT_ERROR: Exception | None = None
try:
    import sounddevice as sd
except Exception as exc:
    sd = None
    _SOUNDDEVICE_IMPORT_ERROR = exc


@dataclass
class RecorderConfig:
    """Configuration for audio recording."""

    sample_rate: int = 16000
    channels: int = 1
    blocksize: int = 1024  # ~64ms at 16kHz
    dtype: str = "float32"
    max_recording_seconds: Optional[int] = None


@dataclass
class AudioChunk:
    """A chunk of recorded audio."""

    data: np.ndarray
    sample_rate: int
    timestamp: float


class AudioRecorder:
    """Records audio from the microphone.

    This class provides both blocking and streaming interfaces for recording.
    """

    def __init__(self, config: Optional[RecorderConfig] = None):
        """Initialize the recorder.

        Args:
            config: Recording configuration.
        """
        self.config = config or RecorderConfig()
        self._recording = False
        self._stream: Optional["sd.InputStream"] = None
        self._recorded_chunks: Deque[np.ndarray] = deque()
        self._max_chunks = self._compute_max_chunks()
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def _compute_max_chunks(self) -> Optional[int]:
        if not self.config.max_recording_seconds:
            return None
        max_seconds = max(1, int(self.config.max_recording_seconds))
        chunks = max_seconds * self.config.sample_rate / self.config.blocksize
        return max(1, math.ceil(chunks))

    def is_available(self) -> bool:
        """Check if audio recording is available."""
        if sd is None:
            return False

        try:
            devices = sd.query_devices()
            return any(d.get("max_input_channels", 0) > 0 for d in devices)
        except Exception:
            return False

    def get_devices(self) -> list[dict]:
        """Get available input devices.

        Returns:
            List of device info dictionaries.
        """
        if sd is None:
            return []

        try:
            devices = sd.query_devices()
            return [
                {"name": d["name"], "index": i, "channels": d["max_input_channels"]}
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            ]
        except Exception:
            return []

    def start(self) -> bool:
        """Start recording audio.

        Returns:
            True if recording started successfully.
        """
        if sd is None:
            return False

        if self._recording:
            return True

        try:
            if self._max_chunks:
                self._recorded_chunks = deque(maxlen=self._max_chunks)
            else:
                self._recorded_chunks = deque()

            def callback(indata, frames, time_info, status):
                global _current_level
                if status:
                    self._logger.debug("Audio callback status: %s", status)
                # Calculate audio level for visualization (atomic update)
                rms = np.sqrt(np.mean(indata ** 2))
                # Normalize: typical speech ~0.01-0.1 RMS, scale to 0-1
                level = min(1.0, rms * 10)
                with _level_lock:
                    _current_level = level
                # Store all chunks for transcription (never drops)
                with self._lock:
                    self._recorded_chunks.append(indata.copy())

            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                blocksize=self.config.blocksize,
                callback=callback,
            )
            self._stream.start()
            self._recording = True
            return True

        except Exception:
            self._logger.exception("Failed to start audio recording")
            return False

    def stop(self) -> Optional[np.ndarray]:
        """Stop recording and return all recorded audio.

        Returns:
            Numpy array of all recorded audio, or None if no audio.
        """
        if not self._recording or self._stream is None:
            return None

        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            self._logger.debug("Failed to stop audio stream cleanly", exc_info=True)

        self._stream = None
        self._recording = False

        with self._lock:
            if not self._recorded_chunks:
                return None

            # Concatenate all chunks
            audio = np.concatenate(list(self._recorded_chunks))
            self._recorded_chunks = deque()
            return np.squeeze(audio)

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    def get_current_level(self) -> float:
        """Get current audio level (0.0-1.0) for visualization.

        Thread-safe method to get the most recent audio level
        calculated from microphone input during recording.
        """
        with _level_lock:
            return _current_level

    def get_volume_level(self, chunk: np.ndarray) -> float:
        """Calculate volume level (0-1) for a chunk.

        Args:
            chunk: Audio chunk.

        Returns:
            Volume level from 0.0 to 1.0.
        """
        if chunk.size == 0:
            return 0.0

        # RMS volume
        rms = np.sqrt(np.mean(chunk**2))

        # Normalize to 0-1 range (assuming typical voice levels)
        # Adjust these thresholds based on testing
        min_db = -60
        max_db = -10
        db = 20 * np.log10(max(rms, 1e-10))
        normalized = (db - min_db) / (max_db - min_db)
        return max(0.0, min(1.0, normalized))


def get_sounddevice_import_error() -> Exception | None:
    """Return the sounddevice import error, if any."""
    return _SOUNDDEVICE_IMPORT_ERROR
