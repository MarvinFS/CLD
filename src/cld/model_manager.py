"""Model management for CLD - download, validation, and caching of GGML models."""

import hashlib
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# GGML Model metadata for pywhispercpp.
#
# Each entry has a pinned SHA-256 digest and exact byte size taken directly
# from the upstream LFS pointer files at
# https://huggingface.co/ggerganov/whisper.cpp/raw/main/<file>. The hashes
# are verified before a downloaded file is accepted; trust-on-first-use is
# never permitted. To add a new model, fetch its LFS pointer and copy
# `sha256` and `size` here.
WHISPER_MODELS = {
    "small": {
        "file": "ggml-small.bin",
        "size": "488MB",
        "size_bytes": 487_601_967,
        "sha256": "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
        "ram": "1GB",
        "cores": 4,
        "description": "Good accuracy - 4+ CPU cores recommended",
    },
    "medium-q5_0": {
        "file": "ggml-medium-q5_0.bin",
        "size": "539MB",
        "size_bytes": 539_212_467,
        "sha256": "19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f",
        "ram": "2GB",
        "cores": 4,
        "description": "Default - quantized for best speed/accuracy balance",
    },
    "medium": {
        "file": "ggml-medium.bin",
        "size": "1.5GB",
        "size_bytes": 1_533_763_059,
        "sha256": "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208",
        "ram": "3GB",
        "cores": 6,
        "description": "Best accuracy - 6+ CPU cores recommended",
    },
}

# Base URL for GGML model downloads.
GGML_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

# Local metadata file caches which pinned hashes were last validated, so we
# don't recompute the SHA-256 of multi-GB files on every startup. The cache
# is advisory only: a stale entry is re-verified on next use, and the source
# of truth for "is this model authentic" is always the in-code WHISPER_MODELS
# table above, never this file.
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
        """Load verification cache (last-known-good SHA-256s) from local file."""
        if self._metadata_path.exists():
            try:
                with open(self._metadata_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to load model metadata: %s", e)
        return {}

    def _save_metadata(self) -> None:
        """Save verification cache to local file."""
        try:
            with open(self._metadata_path, "w", encoding="utf-8") as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save model metadata: %s", e)

    @staticmethod
    def _compute_sha256(file_path: Path) -> str:
        """Compute SHA-256 of a file in 1 MB chunks."""
        digest = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _get_model_path(self, model_name: str) -> Path:
        """Get path to GGML model file."""
        if model_name not in WHISPER_MODELS:
            return self._models_dir / f"ggml-{model_name}.bin"
        return self._models_dir / WHISPER_MODELS[model_name]["file"]

    def _verify_hash(self, file_path: Path, model_name: str) -> tuple[bool, str]:
        """Verify model file against its pinned SHA-256.

        Authenticity is anchored to the hardcoded ``WHISPER_MODELS[...]["sha256"]``
        entry, NOT to whatever the previous run happened to store. A local
        verification cache (``self._metadata``) lets us skip the expensive
        full-file hash when (size, mtime) match a prior successful check, but
        on cache miss or size mismatch we recompute.

        Returns:
            (True, "") if the file's SHA-256 equals the pinned hash and size
            matches; (False, reason) otherwise.
        """
        if model_name not in WHISPER_MODELS:
            return False, f"Unknown model: {model_name}"

        expected_hash = WHISPER_MODELS[model_name].get("sha256")
        expected_size = WHISPER_MODELS[model_name].get("size_bytes")
        if not expected_hash or not expected_size:
            return False, f"No pinned SHA-256 for {model_name}; refusing to trust file"

        try:
            stat = file_path.stat()
        except OSError as e:
            return False, f"Failed to stat file: {e}"

        if stat.st_size != expected_size:
            return False, (
                f"Size mismatch for {model_name}: expected {expected_size} bytes, "
                f"got {stat.st_size} bytes"
            )

        # Verification cache hit (same size + same mtime as last good check) -
        # skip recomputing multi-GB SHA-256.
        cached = self._metadata.get(model_name) or {}
        if (
            cached.get("sha256") == expected_hash
            and cached.get("size") == stat.st_size
            and cached.get("mtime") == int(stat.st_mtime)
        ):
            logger.debug("Hash cache hit for %s", model_name)
            return True, ""

        try:
            logger.info("Verifying SHA-256 of %s (%d bytes)...", model_name, stat.st_size)
            actual_hash = self._compute_sha256(file_path)
        except OSError as e:
            return False, f"Failed to read file: {e}"

        if actual_hash != expected_hash:
            return False, (
                f"SHA-256 mismatch for {model_name}: expected {expected_hash}, "
                f"got {actual_hash}"
            )

        self._metadata[model_name] = {
            "sha256": actual_hash,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }
        self._save_metadata()
        logger.info("Hash OK for %s", model_name)
        return True, ""

    def is_model_available(self, model_name: str, verify_hash: bool = False) -> bool:
        """Check if a model is downloaded and ready.

        Args:
            model_name: Model name (e.g., 'medium-q5_0', 'small').
            verify_hash: If True, also verify the file's SHA-256 against the
                pinned hash in ``WHISPER_MODELS``.

        Returns:
            True if the model file exists (and SHA-256 matches when
            ``verify_hash=True``).
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
        """Download a GGML Whisper model with pinned SHA-256 verification.

        Flow:
          1. Download to a sibling ``<file>.tmp`` so a failure never replaces
             the working model file.
          2. Verify the downloaded file's SHA-256 against the pinned hash.
          3. ``os.replace()`` to the final path atomically only after success.

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
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")

        self._models_dir.mkdir(parents=True, exist_ok=True)

        # Clean up any stale temp from a previous interrupted download.
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as e:
                logger.debug("Failed to remove stale temp %s: %s", temp_path, e)

        try:
            logger.info("Downloading model: %s from %s", model_name, url)

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

            urllib.request.urlretrieve(url, temp_path, reporthook)

            # Verify SHA-256 of the downloaded temp file BEFORE making it
            # visible at the final path. If verification fails the working
            # model (if any) is untouched.
            ok, err = self._verify_hash(temp_path, model_name)
            if not ok:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                logger.error("Downloaded model failed SHA-256 verification: %s", err)
                return False, f"Verification failed: {err}"

            os.replace(temp_path, target_path)

            # Refresh verification cache with the now-final path's mtime so we
            # don't recompute SHA-256 on next startup.
            try:
                stat = target_path.stat()
                self._metadata[model_name] = {
                    "sha256": WHISPER_MODELS[model_name]["sha256"],
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                }
                self._save_metadata()
            except Exception as e:
                logger.debug("Failed to update verification cache: %s", e)

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

        finally:
            # If we exited via an exception path leaving the temp behind, kill it.
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def validate_model(self, model_name: str) -> tuple[bool, str]:
        """Validate a downloaded model against its pinned SHA-256.

        Size-within-20% is not sufficient authenticity evidence; we verify
        the full SHA-256 against the hash hardcoded in ``WHISPER_MODELS``.

        Args:
            model_name: Model name to validate.

        Returns:
            Tuple of (valid, error_message).
        """
        if model_name not in WHISPER_MODELS:
            return False, f"Unknown model: {model_name}"

        model_path = self.get_model_path(model_name)
        if not model_path:
            return False, "Model not found"

        return self._verify_hash(model_path, model_name)

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

        The old model is NEVER unlinked before the new download succeeds and
        verifies. ``download_model()`` writes to a ``.tmp`` sibling and only
        atomically replaces the final file after SHA-256 verification, so a
        failed update leaves the previous working model in place.

        Args:
            model_name: Model name to update.
            progress_callback: Called with (downloaded_bytes, total_bytes, speed_mbps).

        Returns:
            Tuple of (success, error_message).
        """
        return self.download_model(model_name, progress_callback)
