"""Audio recording using sounddevice."""

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np

# Thread-safe audio level and spectrum for visualization
_current_level: float = 0.0
_level_lock = threading.Lock()
_spectrum_bands: list[float] = [0.0] * 32
_spectrum_lock = threading.Lock()

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
    preroll_ms: int = 300  # Pre-roll buffer in milliseconds to capture audio before hotkey


@dataclass
class AudioChunk:
    """A chunk of recorded audio."""

    data: np.ndarray
    sample_rate: int
    timestamp: float


class AudioRecorder:
    """Records audio from the microphone.

    This class provides both blocking and streaming interfaces for recording.
    Uses a pre-roll buffer to capture audio just before the hotkey is pressed,
    preventing the first few letters from being cut off.
    """

    def __init__(self, config: Optional[RecorderConfig] = None):
        """Initialize the recorder.

        Args:
            config: Recording configuration.
        """
        self.config = config or RecorderConfig()
        self._recording = False
        self._primed = False  # Whether pre-roll stream is running
        self._stream: Optional["sd.InputStream"] = None
        self._recorded_chunks: Deque[np.ndarray] = deque()
        self._max_chunks = self._compute_max_chunks()
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

        # Pre-roll buffer: circular buffer to capture audio before start() is called
        preroll_samples = int(self.config.preroll_ms * self.config.sample_rate / 1000)
        preroll_chunks = max(1, math.ceil(preroll_samples / self.config.blocksize))
        self._preroll_buffer: Deque[np.ndarray] = deque(maxlen=preroll_chunks)
        self._logger.debug("Pre-roll buffer: %dms (%d chunks)", self.config.preroll_ms, preroll_chunks)

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

    def _audio_callback(self, indata, frames, time_info, status):
        """Audio callback that handles both pre-roll and recording."""
        global _current_level, _spectrum_bands
        if status:
            self._logger.debug("Audio callback status: %s", status)

        audio = indata.flatten()

        # Calculate overall RMS level
        rms = np.sqrt(np.mean(audio ** 2))
        level = min(1.0, rms * 80)
        with _level_lock:
            _current_level = level

        # Compute FFT spectrum for visualization (32 bands)
        # Focus on actual voice frequency range: 200-4000 Hz
        # This is where speech formants and consonants live
        fft = np.fft.rfft(audio)
        magnitudes = np.abs(fft)

        n_bins = len(magnitudes)
        bands = []
        # Voice-focused frequency range (200 Hz to 4000 Hz)
        min_freq, max_freq = 200, 4000
        num_bands = 32
        for i in range(num_bands):
            # Log-spaced frequency boundaries within voice range
            f_low = min_freq * (max_freq / min_freq) ** (i / num_bands)
            f_high = min_freq * (max_freq / min_freq) ** ((i + 1) / num_bands)
            # Convert to FFT bin indices
            bin_low = int(f_low * n_bins * 2 / self.config.sample_rate)
            bin_high = int(f_high * n_bins * 2 / self.config.sample_rate)
            bin_low = max(0, min(bin_low, n_bins - 1))
            bin_high = max(bin_low + 1, min(bin_high, n_bins))
            # Average magnitude in this band
            band_mag = np.mean(magnitudes[bin_low:bin_high]) if bin_high > bin_low else 0
            bands.append(band_mag)

        # Normalize bands - pure FFT, no fake bass
        max_mag = max(bands) if bands else 1.0
        if max_mag > 0:
            bands = [min(1.0, (b / max_mag) * level * 3.0) for b in bands]
        else:
            bands = [0.0] * 32

        with _spectrum_lock:
            _spectrum_bands = bands

        # Store chunk based on recording state
        chunk = indata.copy()
        with self._lock:
            if self._recording:
                # Store chunks for transcription
                self._recorded_chunks.append(chunk)
            else:
                # Not recording - fill pre-roll buffer (circular)
                self._preroll_buffer.append(chunk)

    def prime(self) -> bool:
        """Start the audio stream for pre-roll buffering.

        Call this early (e.g., at daemon startup) to minimize latency
        and capture audio before the hotkey is pressed.

        Returns:
            True if primed successfully.
        """
        if sd is None:
            return False

        if self._primed:
            return True

        try:
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                blocksize=self.config.blocksize,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._primed = True
            self._logger.info("Audio stream primed with %dms pre-roll", self.config.preroll_ms)
            return True
        except Exception:
            self._logger.exception("Failed to prime audio stream")
            return False

    def start(self) -> bool:
        """Start recording audio.

        If prime() was called, the pre-roll buffer is included at the
        beginning of the recording to capture audio from before the
        hotkey was pressed.

        Returns:
            True if recording started successfully.
        """
        if sd is None:
            return False

        if self._recording:
            return True

        try:
            # Initialize recording buffer
            if self._max_chunks:
                self._recorded_chunks = deque(maxlen=self._max_chunks)
            else:
                self._recorded_chunks = deque()

            with self._lock:
                # Copy pre-roll buffer to beginning of recording
                if self._preroll_buffer:
                    self._logger.debug("Including %d pre-roll chunks", len(self._preroll_buffer))
                    for chunk in self._preroll_buffer:
                        self._recorded_chunks.append(chunk)
                    self._preroll_buffer.clear()

                self._recording = True

            # If not primed, start stream now (fallback for direct start())
            if not self._primed:
                self._stream = sd.InputStream(
                    samplerate=self.config.sample_rate,
                    channels=self.config.channels,
                    dtype=self.config.dtype,
                    blocksize=self.config.blocksize,
                    callback=self._audio_callback,
                )
                self._stream.start()

            return True

        except Exception:
            self._logger.exception("Failed to start audio recording")
            return False

    def stop(self) -> Optional[np.ndarray]:
        """Stop recording and return all recorded audio.

        If the recorder was primed, the stream continues running for
        the pre-roll buffer. Call shutdown() to fully stop the stream.

        Returns:
            Numpy array of all recorded audio, or None if no audio.
        """
        if not self._recording:
            return None

        with self._lock:
            self._recording = False

            if not self._recorded_chunks:
                return None

            # Concatenate all chunks
            audio = np.concatenate(list(self._recorded_chunks))
            self._recorded_chunks = deque()

        # If primed, keep stream running for pre-roll
        # If not primed, stop the stream
        if not self._primed and self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                self._logger.debug("Failed to stop audio stream cleanly", exc_info=True)
            self._stream = None

        return np.squeeze(audio)

    def shutdown(self) -> None:
        """Fully stop the audio stream.

        Call this when the recorder is no longer needed.
        """
        self._recording = False
        self._primed = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                self._logger.debug("Failed to shutdown audio stream cleanly", exc_info=True)
            self._stream = None

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

    def get_spectrum_bands(self) -> list[float]:
        """Get current spectrum bands (16 floats, 0.0-1.0) for visualization.

        Thread-safe method to get FFT spectrum divided into 16 logarithmic
        frequency bands covering voice range (~85Hz to ~8kHz).
        """
        with _spectrum_lock:
            return _spectrum_bands.copy()

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
