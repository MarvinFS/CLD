"""STT engine implementations."""

from typing import Optional, Protocol
import numpy as np


class STTEngine(Protocol):
    """Protocol for STT engines (the engine lifecycle contract).

    All engines (WhisperEngine, NemotronEngine) implement these. The daemon
    drives the lifecycle: ``is_available`` -> ``load_model`` -> ``transcribe``
    (repeatedly) -> ``unload_model``. ``get_last_error`` surfaces the reason
    for a failed ``load_model``/``transcribe`` to the UI.
    """

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe audio to text.

        Args:
            audio: Audio data as numpy array.
            sample_rate: Sample rate of the audio.

        Returns:
            Transcribed text.
        """
        ...

    def is_available(self) -> bool:
        """Check if the engine is available (dependency importable)."""
        ...

    def load_model(self) -> bool:
        """Load the model. Returns True if successful."""
        ...

    def unload_model(self, wait_timeout: float = 30.0) -> bool:
        """Unload the model and free native/GPU resources.

        Must be safe to call while idle and must not delete the native model
        out from under an in-flight ``transcribe()``. Returns True on a clean
        unload. The daemon calls this on engine switch and sleep/wake.
        """
        ...

    def get_last_error(self) -> Optional[str]:
        """Return the last error message, or None if the last op succeeded."""
        ...
