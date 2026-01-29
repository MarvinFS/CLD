"""Hardware detection for STT model recommendations."""

import logging
import subprocess
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
        if self.has_cuda and self.gpu_name:
            vram_str = f", {self.vram_gb:.1f}GB VRAM" if self.vram_gb else ""
            return f"{self.gpu_name}{vram_str}"
        return f"CPU ({self.cpu_cores} cores)"


def _detect_nvidia_gpu() -> tuple[bool, Optional[str], Optional[float]]:
    """Detect NVIDIA GPU via nvidia-smi.

    Returns:
        Tuple of (has_gpu, gpu_name, vram_gb).
    """
    try:
        # Hide console window on Windows
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse: "NVIDIA GeForce RTX 4090, 24564"
            line = result.stdout.strip().split("\n")[0]  # First GPU only
            parts = line.split(", ")
            if len(parts) >= 2:
                name = parts[0].strip()
                vram_mb = float(parts[1].strip())
                return True, name, vram_mb / 1024
    except FileNotFoundError:
        # nvidia-smi not found - no NVIDIA driver
        pass
    except subprocess.TimeoutExpired:
        logger.debug("nvidia-smi timed out")
    except Exception as e:
        logger.debug("nvidia-smi failed: %s", e)
    return False, None, None


def _check_pywhispercpp_cuda() -> bool:
    """Check if pywhispercpp was built with CUDA support.

    CUDA builds include ggml-cuda backend which is used automatically.
    Detection via whisper_print_system_info() which shows "CUDA" if available.
    """
    try:
        import _pywhispercpp as pw
        info = pw.whisper_print_system_info()
        # System info contains "CUDA" if built with CUDA support
        return "CUDA" in info
    except Exception:
        pass
    return False


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

    # Detect NVIDIA GPU
    has_gpu, gpu_name, vram_gb = _detect_nvidia_gpu()
    if has_gpu:
        info.gpu_name = gpu_name
        info.vram_gb = vram_gb
        # Check if pywhispercpp has CUDA support
        info.has_cuda = _check_pywhispercpp_cuda()
        if has_gpu and not info.has_cuda:
            logger.info("NVIDIA GPU detected but pywhispercpp lacks CUDA support. "
                       "Rebuild with GGML_CUDA=1 for GPU acceleration.")

    # Determine recommendations based on hardware
    info.recommended_engine, info.recommended_model = _get_recommendations(info)

    return info


def _get_recommendations(info: HardwareInfo) -> tuple[str, str]:
    """Determine recommended GGML Whisper model based on hardware.

    CLD uses pywhispercpp with GGML models:
    - With GPU (CUDA): medium or larger for fast inference
    - CPU 8+ cores: medium (full precision)
    - CPU 4+ cores: medium-q5_0 (quantized, default)
    - CPU 2-3 cores: small

    Args:
        info: Hardware detection results.

    Returns:
        Tuple of (engine, model) recommendations.
    """
    # GPU recommendations (based on VRAM)
    if info.has_cuda and info.vram_gb:
        if info.vram_gb >= 6:
            return ("whisper", "medium")
        elif info.vram_gb >= 3:
            return ("whisper", "medium-q5_0")
        else:
            return ("whisper", "small")

    # CPU-only recommendations based on core count
    if info.cpu_cores < 2:
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
