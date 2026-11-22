"""Hardware detection for STT model recommendations."""

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GPUDeviceInfo:
    """Information about a single GPU device."""

    index: int
    name: str


@dataclass
class HardwareInfo:
    """Hardware capability information."""

    has_cuda: bool = False
    has_vulkan: bool = False
    gpu_name: Optional[str] = None
    cpu_cores: int = 1
    ram_gb: Optional[float] = None
    recommended_engine: str = "whisper"
    recommended_model: str = "medium-q5_0"

    @property
    def has_gpu(self) -> bool:
        """True if any GPU acceleration is available."""
        return self.has_cuda or self.has_vulkan

    @property
    def gpu_backend(self) -> Optional[str]:
        """Return the active GPU backend name, or None if CPU-only."""
        if self.has_vulkan:
            return "Vulkan"
        if self.has_cuda:
            return "CUDA"
        return None

    @property
    def recommendation(self) -> str:
        """Model to recommend in the UI: Nemotron without a GPU, else the Whisper model."""
        return "Nemotron" if self.recommended_engine == "nemotron" else self.recommended_model

    @property
    def summary(self) -> str:
        """Human-readable hardware summary."""
        if self.has_gpu and self.gpu_name:
            backend = f" ({self.gpu_backend})" if self.gpu_backend else ""
            return f"{self.gpu_name}{backend}"
        return f"CPU ({self.cpu_cores} cores)"


def enumerate_gpus() -> List[GPUDeviceInfo]:
    """Return Vulkan GPUs captured when pywhispercpp initialized."""
    try:
        from cld.engines.whisper import get_vulkan_devices
        return [GPUDeviceInfo(index=idx, name=name) for idx, name in get_vulkan_devices()]
    except Exception as e:
        logger.debug("Vulkan GPU enumeration failed: %s", e)
        return []


def detect_hardware() -> HardwareInfo:
    """Detect hardware capabilities and recommend STT configuration."""
    info = HardwareInfo()

    try:
        info.cpu_cores = os.cpu_count() or 1
    except Exception:
        pass

    try:
        import psutil
        info.ram_gb = psutil.virtual_memory().total / (1024**3)
    except Exception:
        pass

    try:
        from cld.engines.whisper import (
            get_vulkan_devices,
            is_cuda_supported,
            is_vulkan_supported,
        )
        info.has_vulkan = is_vulkan_supported()
        info.has_cuda = is_cuda_supported()
        vulkan_devices = get_vulkan_devices()
        if vulkan_devices:
            info.gpu_name = vulkan_devices[0][1]
    except Exception as e:
        logger.debug("Whisper backend detection failed: %s", e)

    if info.has_vulkan:
        logger.info("Vulkan GPU backend available (universal GPU support)")
    elif info.has_cuda:
        logger.info("CUDA GPU backend available (NVIDIA-only)")

    info.recommended_engine, info.recommended_model = _get_recommendations(info)
    return info


def _get_recommendations(info: HardwareInfo) -> tuple[str, str]:
    """Determine the recommended engine and GGML Whisper model based on hardware.

    - GPU: Whisper large-v3-turbo-q5_0 (most accurate, fastest on a GPU)
    - No GPU: Nemotron. The Whisper model to preselect there is medium-q5_0,
      since turbo takes about 1.7x as long on the CPU.
    """
    if info.has_gpu:
        return ("whisper", "large-v3-turbo-q5_0")
    return ("nemotron", "medium-q5_0")


def get_available_models(engine: str = "whisper") -> list[tuple[str, str]]:
    """Get available models for an engine as (value, display_name) tuples."""
    if engine == "nemotron":
        from cld.model_manager import get_models
        return [
            (name, f"{name} ({spec.get('size', '?')})")
            for name, spec in get_models("nemotron").items()
        ]
    return [
        ("large-v3-turbo-q5_0", "Large v3 Turbo Q5 (~574MB) - Recommended with a GPU"),
        ("medium-q5_0", "Medium Q5 (~539MB) - Translates to English"),
    ]
