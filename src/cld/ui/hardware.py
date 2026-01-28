"""Hardware detection for STT model recommendations (CLD2 - CPU-only)."""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HardwareInfo:
    """Hardware capability information."""

    has_cuda: bool = False
    gpu_name: Optional[str] = None
    vram_gb: Optional[float] = None
    cpu_cores: int = 1
    ram_gb: Optional[float] = None
    recommended_engine: str = "whisper"
    recommended_model: str = "medium-q5_0"

    @property
    def summary(self) -> str:
        """Human-readable hardware summary."""
        return f"CPU ({self.cpu_cores} cores)"


def detect_hardware() -> HardwareInfo:
    """Detect hardware capabilities and recommend STT configuration.

    Returns:
        HardwareInfo with detection results and recommendations.
    """
    info = HardwareInfo()

    # Detect CPU cores
    try:
        import os
        info.cpu_cores = os.cpu_count() or 1
    except Exception:
        pass

    # Detect system RAM
    try:
        import psutil
        mem = psutil.virtual_memory()
        info.ram_gb = mem.total / (1024**3)
    except ImportError:
        # Fallback for Windows without psutil
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulonglong = ctypes.c_ulonglong

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", c_ulonglong),
                    ("ullAvailPhys", c_ulonglong),
                    ("ullTotalPageFile", c_ulonglong),
                    ("ullAvailPageFile", c_ulonglong),
                    ("ullTotalVirtual", c_ulonglong),
                    ("ullAvailVirtual", c_ulonglong),
                    ("ullAvailExtendedVirtual", c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            info.ram_gb = stat.ullTotalPhys / (1024**3)
        except Exception:
            pass
    except Exception:
        pass

    # Determine recommendations based on hardware (CPU-only)
    info.recommended_engine, info.recommended_model = _get_recommendations(info)

    return info


def _get_recommendations(info: HardwareInfo) -> tuple[str, str]:
    """Determine recommended GGML Whisper model based on CPU cores.

    CLD2 uses pywhispercpp with GGML models (CPU-only):
    - 8+ cores: medium (full precision)
    - 4+ cores: medium-q5_0 (quantized, default)
    - 2-3 cores: small

    Args:
        info: Hardware detection results.

    Returns:
        Tuple of (engine, model) recommendations.
    """
    if info.cpu_cores < 2:
        # Refuse to run on single-core systems
        return ("whisper", "small")
    elif info.cpu_cores >= 8:
        return ("whisper", "medium")
    elif info.cpu_cores >= 4:
        return ("whisper", "medium-q5_0")
    else:
        return ("whisper", "small")


def get_max_supported_model(info: Optional[HardwareInfo] = None) -> str:
    """Get the maximum supported model based on hardware.

    Args:
        info: Hardware info (detects if None).

    Returns:
        Maximum supported model name.
    """
    if info is None:
        info = detect_hardware()

    _, model = _get_recommendations(info)
    return model


def get_available_models(engine: str = "whisper") -> list[tuple[str, str]]:
    """Get available GGML Whisper models.

    Args:
        engine: Engine type (only "whisper" supported).

    Returns:
        List of (value, display_name) tuples.
    """
    return [
        ("small", "Small (~488MB) - Good accuracy"),
        ("medium-q5_0", "Medium Q5 (~539MB) - Recommended"),
        ("medium", "Medium (~1.5GB) - Best accuracy"),
    ]
