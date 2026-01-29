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

    @property
    def display_name(self) -> str:
        """User-friendly display name for dropdown."""
        return self.name


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
    def summary(self) -> str:
        """Human-readable hardware summary."""
        if self.has_gpu and self.gpu_name:
            backend = f" ({self.gpu_backend})" if self.gpu_backend else ""
            return f"{self.gpu_name}{backend}"
        return f"CPU ({self.cpu_cores} cores)"


def _detect_gpu_wmi() -> tuple[bool, Optional[str]]:
    """Detect GPU via Windows WMI.

    Returns:
        Tuple of (has_gpu, gpu_name).
    """
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
            # Skip header "Name", return first real GPU
            for line in lines[1:]:
                if line and line != "Name":
                    return True, line
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.debug("wmic timed out")
    except Exception as e:
        logger.debug("wmic failed: %s", e)
    return False, None


def enumerate_gpus() -> List[GPUDeviceInfo]:
    """Enumerate GPUs as seen by whisper.cpp's Vulkan backend.

    IMPORTANT: Uses Vulkan enumeration, not Windows WMI, because whisper.cpp
    uses Vulkan device indices. WMI may include virtual GPUs (like Parsec)
    that Vulkan doesn't see, causing index mismatches.

    Returns:
        List of GPUDeviceInfo matching whisper.cpp's Vulkan device order.
    """
    devices = []

    # Try to get Vulkan device list from pywhispercpp by capturing C-level output
    try:
        import _pywhispercpp as pw
        import os
        import sys
        import tempfile
        import re

        # Capture C-level stderr by redirecting file descriptor
        # This is necessary because whisper.cpp prints directly to stderr
        old_stderr_fd = os.dup(2)
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as tmp:
            tmp_path = tmp.name

        # Redirect stderr to temp file
        with open(tmp_path, 'w') as tmp_file:
            os.dup2(tmp_file.fileno(), 2)

            # Trigger device enumeration by getting system info
            _ = pw.whisper_print_system_info()

            # Flush stderr
            sys.stderr.flush() if sys.stderr else None

        # Restore stderr
        os.dup2(old_stderr_fd, 2)
        os.close(old_stderr_fd)

        # Read captured output
        with open(tmp_path, 'r') as f:
            output = f.read()

        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        # Parse "ggml_vulkan: X = GPU_NAME (vendor)" lines
        pattern = r'ggml_vulkan:\s*(\d+)\s*=\s*([^|]+)'
        for match in re.finditer(pattern, output):
            index = int(match.group(1))
            # Extract just the GPU name (before the parenthetical vendor info)
            name_full = match.group(2).strip()
            # Clean up: "NVIDIA GeForce RTX 4090 (NVIDIA)" -> "RTX 4090"
            name = name_full.split('(')[0].strip()
            # Simplify common prefixes
            name = name.replace("NVIDIA GeForce ", "").replace("AMD ", "")
            devices.append(GPUDeviceInfo(index=index, name=name))

        if devices:
            logger.debug("Enumerated %d Vulkan GPUs: %s", len(devices),
                        [(d.index, d.name) for d in devices])
            return devices

    except Exception as e:
        logger.debug("Vulkan GPU enumeration failed: %s", e)

    # Fallback to WMI if Vulkan enumeration fails, filtering virtual adapters
    logger.debug("Falling back to WMI GPU enumeration")
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
            # Collect GPUs in categories matching Vulkan enumeration order:
            # Vulkan typically enumerates: discrete NVIDIA, discrete AMD, then integrated
            nvidia_discrete = []
            amd_discrete = []
            integrated = []
            for line in lines[1:]:  # Skip header "Name"
                if line and line != "Name":
                    lower = line.lower()
                    # Skip known virtual display adapters
                    if "parsec" in lower or "virtual" in lower or "microsoft" in lower:
                        continue
                    # Categorize to match Vulkan enumeration order
                    if "radeon graphics" in lower or "uhd graphics" in lower or "iris" in lower:
                        integrated.append(line)
                    elif "nvidia" in lower or "geforce" in lower or "rtx" in lower or "gtx" in lower:
                        nvidia_discrete.append(line)
                    elif "radeon" in lower or "amd" in lower:
                        amd_discrete.append(line)
                    else:
                        # Unknown - treat as discrete
                        nvidia_discrete.append(line)
            # Build device list matching Vulkan order: NVIDIA first, then AMD discrete, then integrated
            for name in nvidia_discrete + amd_discrete + integrated:
                devices.append(GPUDeviceInfo(index=len(devices), name=name))
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
    has_gpu, gpu_name = _detect_gpu_wmi()
    if has_gpu:
        info.gpu_name = gpu_name

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
    - With GPU (Vulkan/CUDA): medium-q5_0 for fast inference
    - CPU 8+ cores: medium (full precision)
    - CPU 4+ cores: medium-q5_0 (quantized, default)
    - CPU 2-3 cores: small

    Args:
        info: Hardware detection results.

    Returns:
        Tuple of (engine, model) recommendations.
    """
    # GPU available - recommend medium-q5_0 as good balance
    if info.has_gpu:
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
