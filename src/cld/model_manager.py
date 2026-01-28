"""Model management for CLD2 - download, validation, and caching of GGML models."""

import logging
import os
import urllib.request
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# GGML Model metadata for pywhispercpp
WHISPER_MODELS = {
    "small": {
        "file": "ggml-small.bin",
        "size": "488MB",
        "size_bytes": 488_000_000,
        "ram": "1GB",
        "cores": 4,
        "description": "Good accuracy - 4+ CPU cores recommended",
    },
    "medium-q5_0": {
        "file": "ggml-medium-q5_0.bin",
        "size": "539MB",
        "size_bytes": 539_000_000,
        "ram": "2GB",
        "cores": 4,
        "description": "Default - quantized for best speed/accuracy balance",
    },
    "medium": {
        "file": "ggml-medium.bin",
        "size": "1.5GB",
        "size_bytes": 1_500_000_000,
        "ram": "3GB",
        "cores": 6,
        "description": "Best accuracy - 6+ CPU cores recommended",
    },
}

# Base URL for GGML model downloads
GGML_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


def get_models_dir() -> Path:
    """Get CLD models directory in LOCALAPPDATA."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CLD" / "models"
    return Path.home() / ".cld" / "models"


def setup_model_cache() -> None:
    """Ensure models directory exists."""
    models_dir = get_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Models directory: %s", models_dir)


class ModelManager:
    """Manages GGML Whisper model downloads and validation."""

    def __init__(self):
        """Initialize model manager."""
        setup_model_cache()
        self._models_dir = get_models_dir()

    def _get_model_path(self, model_name: str) -> Path:
        """Get path to GGML model file."""
        if model_name not in WHISPER_MODELS:
            return self._models_dir / f"ggml-{model_name}.bin"
        return self._models_dir / WHISPER_MODELS[model_name]["file"]

    def is_model_available(self, model_name: str) -> bool:
        """Check if a model is downloaded and ready.

        Args:
            model_name: Model name (e.g., 'medium-q5_0', 'small').

        Returns:
            True if model file exists.
        """
        if model_name not in WHISPER_MODELS:
            logger.warning("Unknown model: %s", model_name)
            return False

        model_path = self._get_model_path(model_name)
        return model_path.exists()

    def get_model_path(self, model_name: str) -> Optional[Path]:
        """Get path to downloaded model.

        Args:
            model_name: Model name.

        Returns:
            Path to model file, or None if not found.
        """
        if model_name not in WHISPER_MODELS:
            return None

        model_path = self._get_model_path(model_name)
        if model_path.exists():
            return model_path
        return None

    def download_model(
        self,
        model_name: str,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> tuple[bool, str]:
        """Download a GGML Whisper model.

        Args:
            model_name: Model name to download.
            progress_callback: Called with (downloaded_bytes, total_bytes, speed_mbps).

        Returns:
            Tuple of (success, error_message).
        """
        if model_name not in WHISPER_MODELS:
            return False, f"Unknown model: {model_name}"

        model_info = WHISPER_MODELS[model_name]
        filename = model_info["file"]
        url = f"{GGML_BASE_URL}/{filename}"
        target_path = self._models_dir / filename

        self._models_dir.mkdir(parents=True, exist_ok=True)

        try:
            logger.info("Downloading model: %s from %s", model_name, url)

            # Download with progress tracking
            import time

            last_time = [time.time()]
            last_downloaded = [0]

            def reporthook(block_num, block_size, total_size):
                downloaded = block_num * block_size
                now = time.time()

                if now - last_time[0] >= 0.5:
                    bytes_delta = downloaded - last_downloaded[0]
                    time_delta = now - last_time[0]
                    speed_mbps = (bytes_delta / time_delta) / (1024 * 1024) if time_delta > 0 else 0

                    if progress_callback:
                        progress_callback(downloaded, total_size, speed_mbps)

                    last_time[0] = now
                    last_downloaded[0] = downloaded

            temp_path = target_path.with_suffix(".tmp")
            urllib.request.urlretrieve(url, temp_path, reporthook)

            temp_path.rename(target_path)

            logger.info("Model download complete: %s", model_name)
            return True, ""

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, f"Model not found: {filename}"
            elif e.code == 401:
                return False, "Authentication required"
            return False, f"HTTP error {e.code}: {e.reason}"

        except urllib.error.URLError as e:
            return False, f"Network error: {e.reason}"

        except OSError as e:
            error_msg = str(e)
            if "No space left" in error_msg or "disk" in error_msg.lower():
                return False, f"Not enough disk space. Need approximately {model_info['size']}."
            return False, f"Disk error: {error_msg}"

        except Exception as e:
            logger.exception("Model download failed")
            return False, f"Download failed: {e}"

    def validate_model(self, model_name: str) -> tuple[bool, str]:
        """Validate a downloaded model.

        Args:
            model_name: Model name to validate.

        Returns:
            Tuple of (valid, error_message).
        """
        if not self.is_model_available(model_name):
            return False, "Model not found"

        model_path = self.get_model_path(model_name)
        if not model_path:
            return False, "Model path not found"

        model_info = WHISPER_MODELS[model_name]

        # Check file size is reasonable (within 20% of expected)
        actual_size = model_path.stat().st_size
        expected_size = model_info["size_bytes"]
        size_ratio = actual_size / expected_size

        if size_ratio < 0.8 or size_ratio > 1.2:
            return False, f"Model file size unexpected: {actual_size / (1024*1024):.0f}MB"

        return True, ""

    def check_cpu_capabilities(self) -> tuple[bool, list[str], list[str]]:
        """Check CPU instruction set capabilities for whisper.cpp.

        whisper.cpp requires certain CPU features:
        - SSE4.1: Minimum requirement
        - AVX: Recommended for performance
        - AVX2: Optimal for larger models

        Returns:
            Tuple of (can_run, supported_features, missing_features).
        """
        supported = []
        missing = []

        try:
            try:
                import cpuinfo

                info = cpuinfo.get_cpu_info()
                flags = info.get("flags", [])

                features_to_check = ["sse4_1", "avx", "avx2", "avx512f"]
                for feature in features_to_check:
                    if feature in flags:
                        supported.append(feature.upper().replace("_", "."))
                    else:
                        missing.append(feature.upper().replace("_", "."))

            except ImportError:
                supported = ["SSE4.1", "AVX", "AVX2"]
                missing = []
                logger.debug("cpuinfo not available, assuming modern CPU with AVX2")

        except Exception as e:
            logger.debug("CPU capability detection failed: %s", e)
            supported = ["SSE4.1", "AVX", "AVX2"]
            missing = []

        can_run = "SSE4.1" in supported or len(supported) > 0

        return can_run, supported, missing

    def check_hardware_compatibility(self, model_name: str) -> tuple[bool, str]:
        """Check if hardware can run a model.

        Args:
            model_name: Model name to check.

        Returns:
            Tuple of (compatible, warning_message).
        """
        if model_name not in WHISPER_MODELS:
            return False, f"Unknown model: {model_name}"

        model_info = WHISPER_MODELS[model_name]
        warnings = []

        # Check CPU capabilities
        can_run, supported, _missing = self.check_cpu_capabilities()

        if not can_run:
            return False, "CPU doesn't support required instruction sets (need SSE4.1 minimum)"

        # Check for AVX2 which is recommended for medium model
        if model_name == "medium" and "AVX2" not in supported:
            warnings.append(
                f"AVX2 not detected - {model_name} model may be slow. Consider medium-q5_0."
            )

        # Check CPU cores
        try:
            cpu_cores = os.cpu_count() or 1
        except Exception:
            cpu_cores = 1

        if cpu_cores < 2:
            return False, "Need at least 2 CPU cores to run Whisper"

        if cpu_cores < model_info["cores"]:
            warnings.append(
                f"Model recommends {model_info['cores']}+ CPU cores, you have {cpu_cores}"
            )

        # Check available memory
        try:
            import psutil

            available_gb = psutil.virtual_memory().available / (1024**3)
            required_gb = float(model_info["ram"].rstrip("GB"))

            if available_gb < required_gb:
                warnings.append(
                    f"Model needs ~{model_info['ram']} RAM, ~{available_gb:.1f}GB available"
                )
        except ImportError:
            pass
        except Exception as e:
            logger.debug("Memory check failed: %s", e)

        if warnings:
            return True, "; ".join(warnings)

        return True, ""

    def get_model_info(self, model_name: str) -> Optional[dict]:
        """Get model metadata.

        Args:
            model_name: Model name.

        Returns:
            Model info dict, or None if unknown.
        """
        return WHISPER_MODELS.get(model_name)

    def get_all_models(self) -> dict:
        """Get all available models.

        Returns:
            Dictionary of model name to info.
        """
        return WHISPER_MODELS.copy()

    def get_download_url(self, model_name: str) -> Optional[str]:
        """Get direct download URL for model.

        Args:
            model_name: Model name.

        Returns:
            URL string, or None if unknown model.
        """
        if model_name not in WHISPER_MODELS:
            return None

        filename = WHISPER_MODELS[model_name]["file"]
        return f"{GGML_BASE_URL}/{filename}"

    def update_model(
        self,
        model_name: str,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> tuple[bool, str]:
        """Update an existing model by re-downloading it.

        Args:
            model_name: Model name to update.
            progress_callback: Called with (downloaded_bytes, total_bytes, speed_mbps).

        Returns:
            Tuple of (success, error_message).
        """
        # Remove old model file if it exists
        model_path = self._get_model_path(model_name)
        if model_path.exists():
            try:
                model_path.unlink()
            except OSError as e:
                return False, f"Failed to remove old model: {e}"

        # Download new version
        return self.download_model(model_name, progress_callback)
