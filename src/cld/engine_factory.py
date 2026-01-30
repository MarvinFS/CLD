"""STT engine construction and validation."""

from cld.config import Config
from cld.engines import STTEngine
from cld.engines.whisper import WhisperEngine, is_gpu_supported
from cld.errors import EngineError


def build_engine(config: Config) -> STTEngine:
    """Create an engine instance for the configured engine."""
    engine_type = config.engine.type
    if engine_type == "whisper":
        # force_cpu=True -> use_gpu=False, otherwise let engine auto-detect
        use_gpu = False if config.engine.force_cpu else None

        # When gpu_device=-1 (auto-select) and GPU is available,
        # explicitly use device 0 (first discrete GPU in Vulkan order).
        # Passing -1 to whisper.cpp doesn't auto-select - it falls back to CPU.
        gpu_device = config.engine.gpu_device
        if gpu_device == -1 and use_gpu is not False and is_gpu_supported():
            gpu_device = 0  # First GPU (usually discrete)

        return WhisperEngine(
            model_name=config.engine.whisper_model,
            use_gpu=use_gpu,
            gpu_device=gpu_device,
            translate_to_english=config.engine.translate_to_english,
        )
    raise EngineError(f"Unknown engine '{engine_type}'")
