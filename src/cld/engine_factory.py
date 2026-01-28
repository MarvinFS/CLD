"""STT engine construction and validation."""

from cld.config import Config
from cld.engines import STTEngine
from cld.engines.whisper import WhisperEngine
from cld.errors import EngineError


def build_engine(config: Config) -> STTEngine:
    """Create an engine instance for the configured engine."""
    engine_type = config.engine.type
    if engine_type == "whisper":
        return WhisperEngine(model_name=config.engine.whisper_model)
    raise EngineError(f"Unknown engine '{engine_type}'")
