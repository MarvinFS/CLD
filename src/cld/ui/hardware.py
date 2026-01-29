"""Hardware detection for STT model recommendations."""

import logging
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GPUDeviceInfo:
    """Information about a single GPU device."""

    index: int
    name: str
    vram_gb: float

    @property
    def display_name(self) -> str:
        """User-friendly display name for dropdown."""
        return f"{self.name} ({self.vram_gb:.1f}GB VRAM)"


@dataclass
class HardwareInfo:
    """Hardware capability information."""

    has_cuda: bool = False
    has_vulkan: bool = False
    gpu_name: Optional[str] = None
    vram_gb: Optional[float] = None
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
    def summary(self) -> str:
        """Human-readable hardware summary."""
        if self.has_gpu and self.gpu_name:
            vram_str = f", {self.vram_gb:.1f}GB VRAM" if self.vram_gb else ""
            backend = f" ({self.gpu_backend})" if self.gpu_backend else ""
            return f"{self.gpu_name}{vram_str}{backend}"
        return f"CPU ({self.cpu_cores} cores)"


def _detect_gpu_wmi() -> tuple[bool, Optional[str], Optional[float]]:
    """Detect GPU via Windows WMI (vendor-agnostic).

    Works with NVIDIA, AMD, and Intel GPUs (discrete and integrated).

    Returns:
        Tuple of (has_gpu, gpu_name, vram_gb).
    """
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get",
             "Name,AdapterRAM", "/format:csv"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse CSV: Node,AdapterRAM,Name
            # Skip header line, find first discrete GPU (> 512MB VRAM)
            lines = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
            for line in lines[1:]:  # Skip header
                parts = line.split(",")
                if len(parts) >= 3:
                    adapter_ram = parts[1].strip()
                    name = parts[2].strip()
                    # Skip integrated GPUs with minimal VRAM (< 512MB)
                    if adapter_ram and int(adapter_ram) > 512 * 1024 * 1024:
                        vram_gb = int(adapter_ram) / (1024**3)
                        return True, name, vram_gb
            # Fallback: return first GPU even if low VRAM
            if len(lines) > 1:
                parts = lines[1].split(",")
                if len(parts) >= 3:
                    name = parts[2].strip()
                    adapter_ram = parts[1].strip() if parts[1].strip() else "0"
                    vram_gb = int(adapter_ram) / (1024**3) if adapter_ram != "0" else None
                    return True, name, vram_gb
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.debug("wmic timed out")
    except Exception as e:
        logger.debug("wmic failed: %s", e)
    return False, None, None


def enumerate_gpus() -> List[GPUDeviceInfo]:
    """Enumerate all GPUs via Windows WMI (vendor-agnostic).

    Works with NVIDIA, AMD, and Intel GPUs (discrete and integrated).

    Returns:
        List of GPUDeviceInfo for each detected GPU.
    """
    devices = []
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get",
             "Name,AdapterRAM", "/format:csv"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
            index = 0
            for line in lines[1:]:  # Skip header
                parts = line.split(",")
                if len(parts) >= 3:
                    adapter_ram = parts[1].strip()
                    name = parts[2].strip()
                    if name:  # Valid GPU entry
                        vram_gb = int(adapter_ram) / (1024**3) if adapter_ram else 0.0
                        devices.append(GPUDeviceInfo(
                            index=index,
                            name=name,
                            vram_gb=vram_gb,
                        ))
                        index += 1
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.debug("wmic timed out during GPU enumeration")
    except Exception as e:
        logger.debug("GPU enumeration failed: %s", e)
    return devices


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


def _check_pywhispercpp_vulkan() -> bool:
    """Check if pywhispercpp was built with Vulkan support.

    Vulkan builds include ggml-vulkan backend for cross-vendor GPU acceleration.
    Works with NVIDIA, AMD, and Intel GPUs (both discrete and integrated).
    Detection via whisper_print_system_info() or presence of ggml-vulkan.dll.
    """
    try:
        import _pywhispercpp as pw
        info = pw.whisper_print_system_info()
        if "Vulkan" in info:
            return True
        # Also check for ggml-vulkan.dll in site-packages (pre-built binaries)
        import importlib.util
        from pathlib import Path
        spec = importlib.util.find_spec("_pywhispercpp")
        if spec and spec.origin:
            vulkan_dll = Path(spec.origin).parent / "ggml-vulkan.dll"
            return vulkan_dll.exists()
    except Exception:
        pass
    return False


def get_gpu_backend_info() -> str:
    """Get detailed GPU backend information from pywhispercpp.

    Returns:
        Backend information string from whisper_print_system_info().
    """
    try:
        import _pywhispercpp as pw
        return pw.whisper_print_system_info()
    except Exception as e:
        return f"Error getting backend info: {e}"


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

    # Detect GPU via WMI (works with NVIDIA, AMD, Intel)
    has_gpu, gpu_name, vram_gb = _detect_gpu_wmi()
    if has_gpu:
        info.gpu_name = gpu_name
        info.vram_gb = vram_gb

    # Check GPU backends in pywhispercpp
    # Vulkan is preferred (universal support: NVIDIA, AMD, Intel discrete and integrated)
    # CUDA is fallback (NVIDIA-only, specific architecture builds)
    info.has_vulkan = _check_pywhispercpp_vulkan()
    info.has_cuda = _check_pywhispercpp_cuda()

    if info.has_vulkan:
        logger.info("Vulkan GPU backend available (universal GPU support)")
    elif info.has_cuda:
        logger.info("CUDA GPU backend available (NVIDIA-only)")
    elif has_gpu:
        logger.info("GPU detected but pywhispercpp has no GPU backend. "
                   "Rebuild with GGML_VULKAN=1 for universal GPU acceleration.")

    # Determine recommendations based on hardware
    info.recommended_engine, info.recommended_model = _get_recommendations(info)

    return info


def _get_recommendations(info: HardwareInfo) -> tuple[str, str]:
    """Determine recommended GGML Whisper model based on hardware.

    CLD uses pywhispercpp with GGML models:
    - With GPU (Vulkan/CUDA): medium or larger for fast inference
    - CPU 8+ cores: medium (full precision)
    - CPU 4+ cores: medium-q5_0 (quantized, default)
    - CPU 2-3 cores: small

    Args:
        info: Hardware detection results.

    Returns:
        Tuple of (engine, model) recommendations.
    """
    # GPU recommendations (based on VRAM if known, otherwise assume capable)
    if info.has_gpu:
        if info.vram_gb is not None:
            if info.vram_gb >= 6:
                return ("whisper", "medium")
            elif info.vram_gb >= 3:
                return ("whisper", "medium-q5_0")
            else:
                return ("whisper", "small")
        else:
            # Vulkan with unknown VRAM (e.g., iGPU without nvidia-smi)
            # Default to medium-q5_0 as safe choice
            return ("whisper", "medium-q5_0")

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


def auto_select_gpu() -> int:
    """Auto-select the best GPU device index.

    Vulkan typically lists discrete GPUs before integrated GPUs.
    Returns device index 0 (first GPU, usually discrete) for auto-selection,
    or -1 to let whisper.cpp decide.

    Returns:
        GPU device index (0 for first/discrete GPU).
    """
    # Return 0 (first GPU) which is usually discrete
    # whisper.cpp Vulkan backend lists discrete GPUs before iGPUs
    return 0
