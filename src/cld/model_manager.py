"""Model management for CLD - download, validation, and caching of GGML models."""

import hashlib
import json
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

# Local metadata file stores MD5 hashes of downloaded models
# This allows integrity verification without hardcoded hashes that break on updates
METADATA_FILE = "models.json"


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
        self._metadata_path = self._models_dir / METADATA_FILE
        self._metadata = self._load_metadata()

    def _load_metadata(self) -> dict:
        """Load model metadata (hashes, sizes) from local file."""
        if self._metadata_path.exists():
            try:
                with open(self._metadata_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to load model metadata: %s", e)
        return {}

    def _save_metadata(self) -> None:
        """Save model metadata to local file."""
        try:
            with open(self._metadata_path, "w") as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save model metadata: %s", e)

    def _compute_md5(self, file_path: Path) -> str:
        """Compute MD5 hash of a file."""
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def _get_model_path(self, model_name: str) -> Path:
        """Get path to GGML model file."""
        if model_name not in WHISPER_MODELS:
            return self._models_dir / f"ggml-{model_name}.bin"
        return self._models_dir / WHISPER_MODELS[model_name]["file"]

    def _verify_hash(self, file_path: Path, model_name: str) -> tuple[bool, str]:
        """Verify MD5 hash of model file against stored hash.

        Args:
            file_path: Path to model file to verify.
            model_name: Model name for hash lookup.

        Returns:
            Tuple of (valid, error_message).
            - If no stored hash, computes and stores it (first run).
            - If stored hash exists, verifies file matches.
        """
        try:
            logger.info("Verifying %s...", model_name)
            actual_hash = self._compute_md5(file_path)
            actual_size = file_path.stat().st_size

            # Check if we have stored metadata for this model
            stored = self._metadata.get(model_name)
            if stored is None:
                # First time - store the hash
                self._metadata[model_name] = {
                    "md5": actual_hash,
                    "size": actual_size,
                }
                self._save_metadata()
                logger.info("Stored hash for %s: %s", model_name, actual_hash)
                return True, ""

            expected_hash = stored.get("md5")
            if expected_hash and actual_hash != expected_hash:
                error_msg = f"File corrupted or modified: {model_name}"
                logger.error("%s (expected %s, got %s)", error_msg, expected_hash, actual_hash)
                return False, error_msg

            logger.info("Hash OK for %s", model_name)
            return True, ""

        except OSError as e:
            error_msg = f"Failed to read file: {e}"
            logger.error(error_msg)
            return False, error_msg

        except Exception as e:
            error_msg = f"Verification failed: {e}"
            logger.exception("Unexpected error during verification")
            return False, error_msg

    def is_model_available(self, model_name: str, verify_hash: bool = False) -> bool:
        """Check if a model is downloaded and ready.

        Args:
            model_name: Model name (e.g., 'medium-q5_0', 'small').
            verify_hash: If True, also verify SHA256 hash matches expected.

        Returns:
            True if model file exists (and hash matches if verify_hash=True).
        """
        if model_name not in WHISPER_MODELS:
            logger.warning("Unknown model: %s", model_name)
            return False

        model_path = self._get_model_path(model_name)
        if not model_path.exists():
            return False

        if verify_hash:
            is_valid, _ = self._verify_hash(model_path, model_name)
            return is_valid

        return True

    def is_model_up_to_date(self, model_name: str) -> tuple[bool, str]:
        """Check if a model exists and has the correct hash.

        Args:
            model_name: Model name to check.

        Returns:
            Tuple of (up_to_date, message).
            - (True, "Model is up to date") if hash matches
            - (False, "Model not found") if file doesn't exist
            - (False, "Hash mismatch...") if hash doesn't match
        """
        if model_name not in WHISPER_MODELS:
            return False, f"Unknown model: {model_name}"

        model_path = self._get_model_path(model_name)
        if not model_path.exists():
            return False, "Model not found"

        is_valid, error_msg = self._verify_hash(model_path, model_name)
        if is_valid:
            return True, "Model is up to date"
        return False, error_msg

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

            # Move to final location
            temp_path.rename(target_path)

            # Store hash of downloaded file
            try:
                file_hash = self._compute_md5(target_path)
                file_size = target_path.stat().st_size
                self._metadata[model_name] = {
                    "md5": file_hash,
                    "size": file_size,
                }
                self._save_metadata()
                logger.info("Stored hash for %s: %s", model_name, file_hash)
            except Exception as e:
                logger.warning("Failed to store hash: %s", e)

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
