"""Model management for CLD - download, validation, and caching of models.

Two engine families, kept in separate registries (no merged dict - a name
collision must never route to the wrong engine). ``get_spec(engine, name)``
is the single resolver every caller uses.

- Whisper: single GGML ``.bin`` file, downloaded from Hugging Face.
- Nemotron: multi-file sherpa-onnx ``.tar.bz2`` archive, extracted into a
  content-addressed (``models/nemotron/<sha12>/``) immutable dir and committed
  by atomically writing a small pointer file. Every member's SHA-256 is
  validated against the pinned manifest before the pointer flips.
"""

import hashlib
import json
import logging
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath
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
    "medium-q5_0": {
        "file": "ggml-medium-q5_0.bin",
        "size": "539MB",
        "size_bytes": 539_212_467,
        "sha256": "19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f",
        "ram": "2GB",
        "cores": 4,
        "description": (
            "Translates to English. Runs on a GPU, or slowly on the CPU. "
            "30 s of speech: about 14 s on an 8-core CPU, 0.4 s on a GPU."
        ),
    },
    "large-v3-turbo-q5_0": {
        "file": "ggml-large-v3-turbo-q5_0.bin",
        "size": "574MB",
        "size_bytes": 574_041_195,
        "sha256": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
        "ram": "2GB",
        "cores": 4,
        "translates": False,  # Asked to translate, it types the spoken language with junk in front
        "description": (
            "Recommended with a GPU. Most accurate, can't translate to English. "
            "30 s of speech: about 23 s on an 8-core CPU, 0.2 s on a GPU."
        ),
    },
}

# Base URL for GGML model downloads.
GGML_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


# Nemotron model registry. Each entry pins the archive (url + size + sha256)
# AND a complete per-member manifest (every extracted file's path + sha256 +
# size), so authenticity is verified end to end. ``encoder``/``decoder``/
# ``joiner``/``tokens`` name the four files the engine loads. All facts below
# were captured from the official k2-fsa release asset and verified locally.
# k2-fsa re-uploaded the 1120ms archive on 2026-07-09 under the same filename
# (encoder att_context_size fixed from 70 to 56, k2-fsa/sherpa-onnx#3732), so a
# pin can go stale without the URL changing: re-check the asset digest.
NEMOTRON_MODELS = {
    "nemotron-3.5-streaming-0.6b-1120ms-int8": {
        "family": "nemotron-3.5-asr-streaming-0.6b",
        "archive": "tar.bz2",
        "archive_name": "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8-2026-06-11.tar.bz2",
        "url": (
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
            "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8-2026-06-11.tar.bz2"
        ),
        "size_bytes": 475_276_334,
        "size": "475MB download / ~700MB on disk",
        "sha256": "adbdd5e9fef87300c37cebfcfc4f1ebe56845c860c8a760af0a1dd65ce9beed3",
        # Leading directory inside the archive, stripped on extract so the
        # version dir directly contains the members below.
        "top_dir": "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-1120ms-int8-2026-06-11",
        "encoder": "encoder.int8.onnx",
        "decoder": "decoder.int8.onnx",
        "joiner": "joiner.int8.onnx",
        "tokens": "tokens.txt",
        "members": [
            {"path": "decoder.int8.onnx", "size_bytes": 14_978_075,
             "sha256": "19f9c98fc6d0a2c33a65a43b36fdb2e914c26c0aa9764be3aebc502a1e982fb0"},
            {"path": "encoder.int8.onnx", "size_bytes": 657_601_521,
             "sha256": "2fff2166acaa535bd969fb223c1f0783d71029f143cb298bc54c2afe85abf772"},
            {"path": "joiner.int8.onnx", "size_bytes": 9_504_438,
             "sha256": "4101c7c679a0bc30483794b27a059e34e79232aa2068d78d51231a22c8b0d7ce"},
            {"path": "README.md", "size_bytes": 215,
             "sha256": "31a0ca29d86abbe7728a26544afd2f0b3980b76ee02975fd140680f1555e88a9"},
            {"path": "test_wavs/ar.wav", "size_bytes": 209_522,
             "sha256": "6ef45ea67521622c058c500e9657263925ede912acb173e863d5314e9ce4b0b5"},
            {"path": "test_wavs/de.wav", "size_bytes": 121_388,
             "sha256": "36d3c4845b9808a1656a2a2e92d884590e2db94389e6fe559643291ae0cd3710"},
            {"path": "test_wavs/es.wav", "size_bytes": 235_052,
             "sha256": "49fd2cfa4b62db7068143c582b35de9d31ec2733495ece3611105131d21de06c"},
            {"path": "test_wavs/fr.wav", "size_bytes": 219_180,
             "sha256": "b59be4349b92d344fb903677165eaf4694025d1ab119c608726ecbcb3164b528"},
            {"path": "test_wavs/ja.wav", "size_bytes": 719_916,
             "sha256": "780f95a86ba6cc33a4431fcafeacd213417dfa0a6613f93e4400c18f4dd467b0"},
            {"path": "test_wavs/ko.wav", "size_bytes": 305_096,
             "sha256": "15d91c14f80895d567ba5dd2ebdd1e507569306c436875b3f908e213d689b0a4"},
            {"path": "test_wavs/uk.wav", "size_bytes": 192_044,
             "sha256": "e9c007687c3fb78fbd5382ab654093cb3c90989472607324faf487ae01de198f"},
            {"path": "test_wavs/vi.wav", "size_bytes": 128_624,
             "sha256": "bad24232a06f222697cc27e50bc33c7cd9c1bf7faa73847af7e6742f89b366c0"},
            {"path": "test_wavs/zh.wav", "size_bytes": 228_480,
             "sha256": "7f383a320af7d23200a3cf7313a9bc938972acdb1bc180db4e970bfd648cb641"},
            {"path": "tokens.txt", "size_bytes": 131_440,
             "sha256": "729cc103155bafa785f9cd45746cd41cabe97eab7182fc04d594129587958f8a"},
        ],
        "ram": "2GB",
        "cores": 4,
        "description": (
            "Default engine, CPU only. 40 locales including English and Russian, "
            "writes punctuation. 30 s of speech: about 6 s on an 8-core CPU."
        ),
    },
}

# Per-engine registries. NEVER merge these into one dict for control flow -
# a model name present in both would route to the wrong engine.
_REGISTRIES = {
    "whisper": WHISPER_MODELS,
    "nemotron": NEMOTRON_MODELS,
}


def get_spec(engine: str, model_name: str) -> dict:
    """Return the spec dict for (engine, model_name).

    Raises KeyError if the engine or model is unknown. This is the single
    lookup every caller threads through, so engine routing is explicit.
    """
    try:
        registry = _REGISTRIES[engine]
    except KeyError:
        raise KeyError(f"Unknown engine: {engine!r}")
    return registry[model_name]


def has_spec(engine: str, model_name: str) -> bool:
    """True if (engine, model_name) resolves to a known spec."""
    registry = _REGISTRIES.get(engine)
    return bool(registry) and model_name in registry


def get_models(engine: str) -> dict:
    """Return a copy of the registry for an engine ({} if unknown)."""
    registry = _REGISTRIES.get(engine)
    return dict(registry) if registry else {}

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
        if not has_spec("whisper", model_name):
            return self._models_dir / f"ggml-{model_name}.bin"
        return self._models_dir / get_spec("whisper", model_name)["file"]

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
        if not has_spec("whisper", model_name):
            return False, f"Unknown model: {model_name}"

        expected_hash = get_spec("whisper", model_name).get("sha256")
        expected_size = get_spec("whisper", model_name).get("size_bytes")
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
            model_name: Model name (e.g., 'medium-q5_0').
            verify_hash: If True, also verify the file's SHA-256 against the
                pinned hash in ``WHISPER_MODELS``.

        Returns:
            True if the model file exists (and SHA-256 matches when
            ``verify_hash=True``).
        """
        if not has_spec("whisper", model_name):
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
        if not has_spec("whisper", model_name):
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
        if not has_spec("whisper", model_name):
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
        if not has_spec("whisper", model_name):
            return False, f"Unknown model: {model_name}"

        model_info = get_spec("whisper", model_name)
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
                    "sha256": get_spec("whisper", model_name)["sha256"],
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
        if not has_spec("whisper", model_name):
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
        if not has_spec("whisper", model_name):
            return False, f"Unknown model: {model_name}"

        model_info = get_spec("whisper", model_name)
        warnings = []

        # Check CPU capabilities
        can_run, supported, _missing = self.check_cpu_capabilities()

        if not can_run:
            return False, "CPU doesn't support required instruction sets (need SSE4.1 minimum)"

        # Without AVX2 Whisper runs slowly on the CPU
        if "AVX2" not in supported:
            warnings.append(f"AVX2 not detected - {model_name} model may be slow on the CPU.")

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
        return get_spec("whisper", model_name) if has_spec("whisper", model_name) else None

    def get_download_url(self, model_name: str) -> Optional[str]:
        """Get direct download URL for model.

        Args:
            model_name: Model name.

        Returns:
            URL string, or None if unknown model.
        """
        if not has_spec("whisper", model_name):
            return None

        filename = get_spec("whisper", model_name)["file"]
        return f"{GGML_BASE_URL}/{filename}"

    # ----------------------------------------------------------------- #
    # Nemotron (multi-file sherpa-onnx archive) support                  #
    # ----------------------------------------------------------------- #

    def _nemotron_root(self) -> Path:
        return self._models_dir / "nemotron"

    def _nemotron_pointer(self, model_name: str) -> Path:
        """Small text file naming the active content version (sha12)."""
        return self._nemotron_root() / f"{model_name}.current"

    def resolve_nemotron_dir(self, model_name: str) -> Optional[Path]:
        """Resolve the pinned version's dir via the pointer, or None.

        Returns the dir that directly contains the .onnx/tokens files. A pointer
        to a superseded version (an older pin) counts as not installed. Does
        NOT validate hashes (cheap path used on every engine load).
        """
        if not has_spec("nemotron", model_name):
            return None
        ptr = self._nemotron_pointer(model_name)
        if not ptr.exists():
            return None
        try:
            sha = ptr.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if sha != get_spec("nemotron", model_name)["sha256"][:12]:
            return None
        version_dir = self._nemotron_root() / sha
        return version_dir if version_dir.is_dir() else None

    @staticmethod
    def _safe_member_relpath(member_name: str, top_dir: str) -> Optional[str]:
        """Strip the archive's top dir and return a safe relative path.

        Version-safe (Python 3.10+, not just 3.12's ``filter='data'``):
        rejects absolute paths, drive letters, UNC, and ``..`` traversal.
        Returns None for the top-dir entry itself (skip).
        """
        name = member_name.replace("\\", "/")
        # Reject absolute paths / drive letters / UNC outright.
        if name.startswith("/") or name.startswith("//") or (len(name) > 1 and name[1] == ":"):
            raise ValueError(f"Unsafe path in archive: {member_name!r}")
        # Drop "." and empty segments (a leading "/" was already rejected above).
        parts = [p for p in name.split("/") if p and p != "."]
        if top_dir and parts and parts[0] == top_dir:
            parts = parts[1:]
        if not parts:
            return None
        rel = PurePosixPath(*parts)
        if rel.is_absolute() or any(p == ".." for p in rel.parts):
            raise ValueError(f"Unsafe path in archive: {member_name!r}")
        first = rel.parts[0]
        if ":" in first or first.startswith("\\\\"):
            raise ValueError(f"Unsafe path in archive: {member_name!r}")
        return str(rel)

    def _extract_archive_safe(self, archive_path: Path, version_dir: Path, spec: dict) -> None:
        """Extract a .tar.bz2 into ``version_dir`` with path-traversal guards.

        Streams each regular file (no ``extractall``), rejects symlink/hardlink/
        device members, strips the archive top dir, and confirms each output
        path stays within ``version_dir``.
        """
        top_dir = spec.get("top_dir", "")
        version_dir.mkdir(parents=True, exist_ok=True)
        base = version_dir.resolve()
        with tarfile.open(archive_path, "r:bz2") as tf:
            for m in tf.getmembers():
                if m.issym() or m.islnk() or m.isdev():
                    raise ValueError(f"Unsafe member type in archive: {m.name!r}")
                if not m.isfile():
                    continue  # dir entries created on demand below
                rel = self._safe_member_relpath(m.name, top_dir)
                if rel is None:
                    continue
                out = version_dir / rel
                out_resolved = out.resolve()
                if base != out_resolved and base not in out_resolved.parents:
                    raise ValueError(f"Path escapes target dir: {m.name!r}")
                out.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(m)
                if src is None:
                    raise ValueError(f"Cannot read member: {m.name!r}")
                with src, open(out, "wb") as fh:
                    shutil.copyfileobj(src, fh, length=1024 * 1024)

    def _verify_nemotron_member(
        self, version_dir: Path, member: dict, sha_prefix: str, use_cache: bool = True
    ) -> tuple[bool, str]:
        """Verify one member's size + SHA-256 (size+mtime cache like whisper)."""
        path = version_dir / member["path"]
        expected = member["sha256"]
        expected_size = member["size_bytes"]
        try:
            stat = path.stat()
        except OSError as e:
            return False, f"missing member {member['path']}: {e}"
        if stat.st_size != expected_size:
            return False, (
                f"size mismatch for {member['path']}: expected {expected_size}, "
                f"got {stat.st_size}"
            )
        cache_key = f"nemotron:{sha_prefix}:{member['path']}"
        cached = self._metadata.get(cache_key) or {}
        if (
            use_cache
            and cached.get("sha256") == expected
            and cached.get("size") == stat.st_size
            and cached.get("mtime") == int(stat.st_mtime)
        ):
            return True, ""
        actual = self._compute_sha256(path)
        if actual != expected:
            return False, (
                f"SHA-256 mismatch for {member['path']}: expected {expected}, got {actual}"
            )
        self._metadata[cache_key] = {
            "sha256": expected, "size": stat.st_size, "mtime": int(stat.st_mtime),
        }
        self._save_metadata()
        return True, ""

    def _verify_nemotron_members(
        self, version_dir: Path, spec: dict, sha_prefix: str, use_cache: bool = True
    ) -> tuple[bool, str]:
        for member in spec["members"]:
            ok, err = self._verify_nemotron_member(version_dir, member, sha_prefix, use_cache)
            if not ok:
                return False, err
        return True, ""

    def is_nemotron_model_available(self, model_name: str, verify_hash: bool = True) -> bool:
        """True only if marker present, pointer resolves to the pinned version,
        and (default) every member's SHA-256 validates."""
        if not has_spec("nemotron", model_name):
            return False
        version_dir = self.resolve_nemotron_dir(model_name)
        if version_dir is None:
            return False
        spec = get_spec("nemotron", model_name)
        sha_prefix = spec["sha256"][:12]
        if not verify_hash:
            for key in ("tokens", "encoder", "decoder", "joiner"):
                if not (version_dir / spec[key]).exists():
                    return False
            return True
        ok, _ = self._verify_nemotron_members(version_dir, spec, sha_prefix, use_cache=True)
        return ok

    def validate_nemotron_model(self, model_name: str) -> tuple[bool, str]:
        """Force a full re-hash of every member against the pinned manifest."""
        if not has_spec("nemotron", model_name):
            return False, f"Unknown model: {model_name}"
        version_dir = self.resolve_nemotron_dir(model_name)
        if version_dir is None:
            return False, "Model not found"
        spec = get_spec("nemotron", model_name)
        sha_prefix = spec["sha256"][:12]
        return self._verify_nemotron_members(version_dir, spec, sha_prefix, use_cache=False)

    def install_nemotron_from_archive(
        self,
        archive_path,
        model_name: str,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> tuple[bool, str]:
        """Verify an on-disk archive and install it (extract + validate + commit).

        Trust chain: archive size+SHA-256 -> safe extract -> every member's
        SHA-256 -> atomic pointer write (the commit). A user-created marker is
        never trusted; only this method writes the pointer.
        """
        if not has_spec("nemotron", model_name):
            return False, f"Unknown model: {model_name}"
        spec = get_spec("nemotron", model_name)
        archive_path = Path(archive_path)
        if not archive_path.exists():
            return False, f"Archive not found: {archive_path}"

        try:
            archive_size = archive_path.stat().st_size
        except OSError as e:
            return False, f"Cannot stat archive: {e}"
        if archive_size != spec["size_bytes"]:
            return False, (
                f"Archive size mismatch: expected {spec['size_bytes']}, got {archive_size}"
            )
        logger.info("Verifying archive SHA-256 (%d bytes)...", archive_size)
        actual = self._compute_sha256(archive_path)
        if actual != spec["sha256"]:
            return False, f"Archive SHA-256 mismatch: expected {spec['sha256']}, got {actual}"

        sha_prefix = spec["sha256"][:12]
        version_dir = self._nemotron_root() / sha_prefix

        # Idempotent: already installed and committed to this exact version.
        if self.is_nemotron_model_available(model_name, verify_hash=True):
            return True, ""

        # Extract fresh into the content-addressed dir (any prior *different*
        # version stays put; its pointer is only flipped on success below).
        if version_dir.exists():
            shutil.rmtree(version_dir, ignore_errors=True)
        try:
            self._extract_archive_safe(archive_path, version_dir, spec)
        except Exception as e:
            shutil.rmtree(version_dir, ignore_errors=True)
            logger.exception("Nemotron extraction failed")
            return False, f"Extraction failed: {e}"

        ok, err = self._verify_nemotron_members(version_dir, spec, sha_prefix, use_cache=False)
        if not ok:
            shutil.rmtree(version_dir, ignore_errors=True)
            return False, f"Member verification failed: {err}"

        # Commit: atomic small-file pointer write (NOT os.replace over a dir).
        ptr = self._nemotron_pointer(model_name)
        try:
            previous = ptr.read_text(encoding="utf-8").strip()
        except OSError:
            previous = ""  # first install: nothing to clean up
        try:
            self._nemotron_root().mkdir(parents=True, exist_ok=True)
            tmp = ptr.with_suffix(ptr.suffix + ".tmp")
            tmp.write_text(sha_prefix, encoding="utf-8")
            os.replace(tmp, ptr)
        except OSError as e:
            return False, f"Failed to commit model pointer: {e}"

        # A re-pinned model leaves its previous version behind, now unreferenced.
        # Delete only a plain sha12 name, never a path someone wrote into the pointer.
        if (previous != sha_prefix and len(previous) == 12
                and all(c in "0123456789abcdef" for c in previous)):
            self._delete_nemotron_version(previous)

        logger.info("Nemotron model installed: %s -> %s", model_name, sha_prefix)
        return True, ""

    def download_nemotron_model(
        self,
        model_name: str,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> tuple[bool, str]:
        """Download the Nemotron archive to a .tmp and install it."""
        if not has_spec("nemotron", model_name):
            return False, f"Unknown model: {model_name}"
        spec = get_spec("nemotron", model_name)
        root = self._nemotron_root()
        root.mkdir(parents=True, exist_ok=True)
        tmp = root / (spec["archive_name"] + ".tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

        try:
            import time
            last_time = [time.time()]
            last_dl = [0]

            def reporthook(block_num, block_size, total_size):
                dl = block_num * block_size
                now = time.time()
                if now - last_time[0] >= 0.5:
                    d = dl - last_dl[0]
                    dt = now - last_time[0]
                    spd = (d / dt) / (1024 * 1024) if dt > 0 else 0
                    if progress_callback:
                        progress_callback(dl, total_size, spd)
                    last_time[0] = now
                    last_dl[0] = dl

            logger.info("Downloading Nemotron model: %s", spec["url"])
            urllib.request.urlretrieve(spec["url"], tmp, reporthook)
        except urllib.error.HTTPError as e:
            return False, f"HTTP error {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, f"Network error: {e.reason}"
        except OSError as e:
            return False, f"Disk error: {e}"
        except Exception as e:
            logger.exception("Nemotron download failed")
            return False, f"Download failed: {e}"

        try:
            ok, err = self.install_nemotron_from_archive(tmp, model_name, progress_callback)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return ok, err

    def get_nemotron_download_url(self, model_name: str) -> Optional[str]:
        if not has_spec("nemotron", model_name):
            return None
        return get_spec("nemotron", model_name)["url"]

    def get_nemotron_archive_name(self, model_name: str) -> Optional[str]:
        if not has_spec("nemotron", model_name):
            return None
        return get_spec("nemotron", model_name)["archive_name"]

    def remove_whisper_model(self, model_name: str) -> tuple[bool, str]:
        """Delete a downloaded Whisper model file and drop its hash cache."""
        if not has_spec("whisper", model_name):
            return False, f"Unknown model: {model_name}"
        path = self._get_model_path(model_name)
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            return False, f"Failed to delete {path.name}: {e}"
        if self._metadata.pop(model_name, None) is not None:
            self._save_metadata()
        return True, ""

    def remove_nemotron_model(self, model_name: str) -> tuple[bool, str]:
        """Delete an installed Nemotron model: the pointer + its version dir."""
        if not has_spec("nemotron", model_name):
            return False, f"Unknown model: {model_name}"
        spec = get_spec("nemotron", model_name)
        ptr = self._nemotron_pointer(model_name)
        try:
            if ptr.exists():
                ptr.unlink()
        except OSError as e:
            return False, f"Failed to remove model: {e}"
        self._delete_nemotron_version(spec["sha256"][:12])
        return True, ""

    def _delete_nemotron_version(self, sha_prefix: str) -> None:
        """Delete one content version dir and drop its cached member hashes."""
        shutil.rmtree(self._nemotron_root() / sha_prefix, ignore_errors=True)
        stale = [k for k in self._metadata if k.startswith(f"nemotron:{sha_prefix}:")]
        for k in stale:
            self._metadata.pop(k, None)
        if stale:
            self._save_metadata()

    # ----------------------------------------------------------------- #
    # Engine-agnostic dispatchers (used by daemon/UI/setup)             #
    # ----------------------------------------------------------------- #

    def is_engine_model_available(
        self, engine: str, model_name: str, verify_hash: bool = False
    ) -> bool:
        if engine == "nemotron":
            return self.is_nemotron_model_available(model_name, verify_hash=verify_hash)
        return self.is_model_available(model_name, verify_hash=verify_hash)

    def download_engine_model(
        self,
        engine: str,
        model_name: str,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> tuple[bool, str]:
        if engine == "nemotron":
            return self.download_nemotron_model(model_name, progress_callback)
        return self.download_model(model_name, progress_callback)

    def validate_engine_model(self, engine: str, model_name: str) -> tuple[bool, str]:
        if engine == "nemotron":
            return self.validate_nemotron_model(model_name)
        return self.validate_model(model_name)

    def remove_engine_model(self, engine: str, model_name: str) -> tuple[bool, str]:
        if engine == "nemotron":
            return self.remove_nemotron_model(model_name)
        return self.remove_whisper_model(model_name)

    def get_engine_download_url(self, engine: str, model_name: str) -> Optional[str]:
        if engine == "nemotron":
            return self.get_nemotron_download_url(model_name)
        return self.get_download_url(model_name)

    def get_engine_model_info(self, engine: str, model_name: str) -> Optional[dict]:
        return get_spec(engine, model_name) if has_spec(engine, model_name) else None
