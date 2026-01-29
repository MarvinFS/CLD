"""STT engine construction and validation."""

from cld.config import Config
from cld.engines import STTEngine
from cld.engines.whisper import WhisperEngine
from cld.errors import EngineError


def build_engine(config: Config) -> STTEngine:
    """Create an engine instance for the configured engine."""
    engine_type = config.engine.type
    if engine_type == "whisper":
        # force_cpu=True -> use_gpu=False, otherwise let engine auto-detect
        use_gpu = False if config.engine.force_cpu else None

        return WhisperEngine(
            model_name=config.engine.whisper_model,
            use_gpu=use_gpu,
            gpu_device=config.engine.gpu_device,
        )
    raise EngineError(f"Unknown engine '{engine_type}'")
