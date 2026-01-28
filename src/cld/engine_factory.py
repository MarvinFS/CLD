"""STT engine construction and validation."""

from cld.config import Config
from cld.engines import STTEngine
from cld.engines.whisper import WhisperEngine
from cld.errors import EngineError


def build_engine(config: Config) -> STTEngine:
    """Create an engine instance for the configured engine."""
    engine_type = config.engine.type
    if engine_type == "whisper":
        # Resolve device setting: "auto", "gpu"/"cuda", or "cpu"
        device = config.engine.device.lower()
        if device == "auto":
            use_gpu = None  # Let WhisperEngine auto-detect
        elif device in ("gpu", "cuda"):
            use_gpu = True
        else:
            use_gpu = False

        return WhisperEngine(
            model_name=config.engine.whisper_model,
            use_gpu=use_gpu,
        )
    raise EngineError(f"Unknown engine '{engine_type}'")
