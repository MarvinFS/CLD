"""Configuration management for CLD."""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Configuration schema version for migrations
CONFIG_VERSION = 1

# Default Nemotron model (the one pinned sherpa-onnx package in v1).
DEFAULT_NEMOTRON_MODEL = "nemotron-3.5-streaming-0.6b-1120ms-int8"

# Nemotron per-stream language codes (passed to stream.set_option("language", X)).
# "auto" lets the model detect; the rest are the 36 unique ISO codes (40 locales)
# from the NVIDIA nemotron-3.5-asr-streaming-0.6b model card.
NEMOTRON_LANGUAGES = (
    "auto", "en", "es", "fr", "it", "pt", "nl", "de", "tr", "ru", "ar", "hi",
    "ja", "ko", "vi", "uk", "pl", "sv", "cs", "nb", "da", "bg", "fi", "hr",
    "sk", "zh", "hu", "ro", "et", "el", "lt", "lv", "mt", "sl", "he", "th", "nn",
)


@dataclass
class ActivationConfig:
    """Activation key settings."""
    key: str = "alt"  # Generic 'alt' works with any Alt key (left, right, or AltGr)
    scancode: int = 0  # Scancode is informational only; matching uses key name
    modifiers: list = field(default_factory=list)  # Optional modifiers: ["ctrl"], ["shift"], ["ctrl", "shift"]
    mode: Literal["push_to_talk", "toggle"] = "toggle"  # Press to start, press again to stop
    enabled: bool = True


@dataclass
class EngineConfig:
    """STT engine settings."""
    type: Literal["whisper", "nemotron"] = "nemotron"  # Active STT engine (default; Whisper is the optional GPU engine)
    whisper_model: str = "medium-q5_0"  # ~1.5GB, good accuracy
    force_cpu: bool = False  # Force CPU-only mode (ignore GPU) [whisper only]
    gpu_device: int = -1  # -1=auto-select, 0=first GPU, etc. [whisper only]
    translate_to_english: bool = False  # Translate to English [whisper only]
    nemotron_model: str = DEFAULT_NEMOTRON_MODEL  # Nemotron model name
    nemotron_language: str = "auto"  # Per-stream language for Nemotron


@dataclass
class OutputConfig:
    """Output settings."""
    mode: Literal["injection", "clipboard", "auto"] = "auto"
    sound_effects: bool = True


@dataclass
class RecordingConfig:
    """Recording settings."""
    max_seconds: int = 300
    sample_rate: int = 16000


@dataclass
class UIConfig:
    """UI settings."""
    overlay_position: list = field(default_factory=lambda: [960, 1000])
    show_on_startup: bool = True


@dataclass
class Config:
    """CLD configuration."""

    version: int = CONFIG_VERSION
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    # Legacy compatibility properties
    @property
    def hotkey(self) -> str:
        """Build hotkey string from activation key and modifiers."""
        # Keys that need angle brackets (special keys)
        special_keys = {
            "alt", "alt_l", "alt_r", "alt_gr",
            "ctrl", "ctrl_l", "ctrl_r",
            "shift", "shift_l", "shift_r",
            "cmd", "cmd_l", "cmd_r",
            "space", "tab", "enter", "return", "esc", "escape",
            "backspace", "delete", "insert", "home", "end",
            "page_up", "page_down", "caps_lock", "num_lock", "scroll_lock",
            "print_screen", "pause",
            "up", "down", "left", "right",
            "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
        }

        parts = []
        # Add modifiers first
        for mod in self.activation.modifiers:
            parts.append(f"<{mod}>")
        # Add main key - wrap in brackets only if it's a special key
        key = self.activation.key.lower()
        if key in special_keys:
            parts.append(f"<{key}>")
        else:
            # Single characters or other keys don't need brackets
            parts.append(self.activation.key)
        return "+".join(parts)

    @property
    def mode(self) -> str:
        """Legacy mode property for compatibility."""
        return "toggle" if self.activation.mode == "toggle" else "push-to-talk"

    # Note: Can't use @property named 'engine' as it conflicts with EngineConfig attribute
    # Use engine.type instead for engine name

    @property
    def whisper_model(self) -> str:
        """Legacy whisper_model property."""
        return self.engine.whisper_model

    @property
    def sample_rate(self) -> int:
        """Legacy sample_rate property."""
        return self.recording.sample_rate

    @property
    def max_recording_seconds(self) -> int:
        """Legacy max_recording_seconds property."""
        return self.recording.max_seconds

    @property
    def output_mode(self) -> str:
        """Legacy output_mode property."""
        return self.output.mode

    @property
    def sound_effects(self) -> bool:
        """Legacy sound_effects property."""
        return self.output.sound_effects

    @classmethod
    def get_config_dir(cls) -> Path:
        """Get the configuration directory path.

        Uses LOCALAPPDATA on Windows to avoid OneDrive sync issues.
        Falls back to home directory on other platforms.

        Security: ``CLD_CONFIG_DIR`` override is validated to prevent path
        traversal. The absoluteness check happens BEFORE ``.resolve()``,
        because ``Path("foo").resolve()`` is already absolute (it's joined
        against cwd) and the old post-resolve check accepted everything.
        """
        override = os.environ.get("CLD_CONFIG_DIR")
        if override:
            raw_path = Path(override).expanduser()
            if not raw_path.is_absolute():
                logger.warning("CLD_CONFIG_DIR must be absolute path, ignoring: %s", override)
            else:
                override_path = raw_path.resolve()
                system_root = os.environ.get("SYSTEMROOT", "C:\\Windows")
                system_dirs = [Path(system_root)]
                is_system_dir = False
                for sd in system_dirs:
                    try:
                        override_path.relative_to(sd.resolve())
                        is_system_dir = True
                        break
                    except ValueError:
                        pass
                if is_system_dir:
                    logger.warning("CLD_CONFIG_DIR cannot be system directory, ignoring: %s", override)
                else:
                    override_path.mkdir(parents=True, exist_ok=True)
                    return override_path

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            config_dir = Path(local_app_data) / "CLD"
        else:
            config_dir = Path.home() / ".cld"

        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    @classmethod
    def get_config_path(cls) -> Path:
        """Get the configuration file path."""
        return cls.get_config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from file, or return defaults."""
        config_path = cls.get_config_path()

        # Try to load JSON config first
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls._from_dict(data)
            except Exception:
                logger.exception("Failed to load config; using defaults")
                return cls()

        # Return defaults
        return cls()

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary.

        Each section is type-checked independently. A malformed section
        (e.g. ``"activation": "bad"``) is logged and defaulted in isolation,
        so one bad key doesn't wipe out every other user setting in the file.
        """
        config = cls()

        if not isinstance(data, dict):
            logger.warning("Config root is not a dict; using all defaults")
            return config.validate()

        version = data.get("version", 1)
        if isinstance(version, int) and version < CONFIG_VERSION:
            logger.info("Migrating config from version %d to %d", version, CONFIG_VERSION)

        act = data.get("activation")
        if isinstance(act, dict):
            config.activation = ActivationConfig(
                key=act.get("key", config.activation.key),
                scancode=act.get("scancode", config.activation.scancode),
                modifiers=act.get("modifiers", config.activation.modifiers),
                mode=act.get("mode", config.activation.mode),
                enabled=act.get("enabled", config.activation.enabled),
            )
        elif act is not None:
            logger.warning("Invalid 'activation' section (type %s); using defaults", type(act).__name__)

        eng = data.get("engine")
        if isinstance(eng, dict):
            # Handle backwards compatibility: old "device": "cpu" -> new "force_cpu": true
            force_cpu = eng.get("force_cpu", False)
            if not force_cpu and eng.get("device") == "cpu":
                force_cpu = True
            config.engine = EngineConfig(
                type=eng.get("type", config.engine.type),
                whisper_model=eng.get("whisper_model", config.engine.whisper_model),
                force_cpu=force_cpu,
                gpu_device=eng.get("gpu_device", config.engine.gpu_device),
                translate_to_english=eng.get(
                    "translate_to_english", config.engine.translate_to_english
                ),
                nemotron_model=eng.get("nemotron_model", config.engine.nemotron_model),
                nemotron_language=eng.get(
                    "nemotron_language", config.engine.nemotron_language
                ),
            )
        elif eng is not None:
            logger.warning("Invalid 'engine' section (type %s); using defaults", type(eng).__name__)

        out = data.get("output")
        if isinstance(out, dict):
            config.output = OutputConfig(
                mode=out.get("mode", config.output.mode),
                sound_effects=out.get("sound_effects", config.output.sound_effects),
            )
        elif out is not None:
            logger.warning("Invalid 'output' section (type %s); using defaults", type(out).__name__)

        rec = data.get("recording")
        if isinstance(rec, dict):
            config.recording = RecordingConfig(
                max_seconds=rec.get("max_seconds", config.recording.max_seconds),
                sample_rate=rec.get("sample_rate", config.recording.sample_rate),
            )
        elif rec is not None:
            logger.warning("Invalid 'recording' section (type %s); using defaults", type(rec).__name__)

        ui = data.get("ui")
        if isinstance(ui, dict):
            config.ui = UIConfig(
                overlay_position=ui.get("overlay_position", config.ui.overlay_position),
                show_on_startup=ui.get("show_on_startup", config.ui.show_on_startup),
            )
        elif ui is not None:
            logger.warning("Invalid 'ui' section (type %s); using defaults", type(ui).__name__)

        return config.validate()

    def to_dict(self) -> dict:
        """Convert config to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "activation": asdict(self.activation),
            "engine": asdict(self.engine),
            "output": asdict(self.output),
            "recording": asdict(self.recording),
            "ui": asdict(self.ui),
        }

    def save(self) -> bool:
        """Save configuration to file with retry + inter-process lock.

        Multiple processes (daemon + settings dialog) can race when both
        save back to the same JSON. We serialize writes with a sidecar
        lock file held via Windows ``msvcrt.locking`` (exclusive), with a
        POSIX ``fcntl`` fallback. The lock is best-effort: if the lock
        module is unavailable we still do the atomic write, which protects
        against partial files but not against lost-update races.
        """
        config_path = self.get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = config_path.with_suffix(config_path.suffix + ".lock")

        lock_fh = None
        locked = False
        try:
            try:
                # Open with O_RDWR | O_CREAT so we can use msvcrt.locking on Windows.
                lock_fh = open(lock_path, "a+b")
            except OSError as e:
                logger.debug("Could not open config lock file %s: %s", lock_path, e)

            if lock_fh is not None:
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
                        else:  # pragma: no cover - non-windows fallback
                            import fcntl
                            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError:
                        time.sleep(0.05)
                if not locked:
                    logger.warning("Config save proceeding without inter-process lock")

            temp_file = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    delete=False,
                    dir=str(config_path.parent),
                    encoding="utf-8",
                    suffix=".json",
                ) as handle:
                    temp_file = Path(handle.name)
                    json.dump(self.to_dict(), handle, indent=2)

                max_attempts = 3
                delays = [0.1, 0.2, 0.4]
                for attempt in range(max_attempts):
                    try:
                        os.replace(temp_file, config_path)
                        return True
                    except (PermissionError, OSError) as e:
                        if attempt < max_attempts - 1:
                            logger.debug(
                                "Config save attempt %d failed with %s, retrying in %.1fs",
                                attempt + 1,
                                type(e).__name__,
                                delays[attempt],
                            )
                            time.sleep(delays[attempt])
                        else:
                            raise
                return False
            except Exception:
                logger.exception("Failed to save config")
                return False
            finally:
                if temp_file and temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass
        finally:
            if lock_fh is not None:
                if locked:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
                        else:  # pragma: no cover
                            import fcntl
                            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
                try:
                    lock_fh.close()
                except OSError:
                    pass

    def validate(self) -> "Config":
        """Validate and normalize configuration values."""
        # Default activation key + scancode kept in sync with the dataclass default.
        if not self.activation.key:
            default_key = ActivationConfig.key
            logger.warning("Invalid activation key; defaulting to %r", default_key)
            self.activation.key = default_key
            self.activation.scancode = ActivationConfig.scancode

        if self.activation.mode not in ("push_to_talk", "toggle"):
            logger.warning("Invalid mode '%s'; defaulting to 'push_to_talk'", self.activation.mode)
            self.activation.mode = "push_to_talk"

        # Normalize activation.enabled to bool.
        self.activation.enabled = bool(self.activation.enabled)

        # Filter modifiers to known values and ensure list type.
        known_mods = {"ctrl", "shift", "alt", "alt_gr", "cmd", "meta", "win"}
        if not isinstance(self.activation.modifiers, list):
            logger.warning("activation.modifiers is not a list; clearing")
            self.activation.modifiers = []
        else:
            filtered = [m for m in self.activation.modifiers if isinstance(m, str) and m.lower() in known_mods]
            if len(filtered) != len(self.activation.modifiers):
                logger.warning(
                    "Dropped unknown activation.modifiers entries: %s",
                    [m for m in self.activation.modifiers if m not in filtered],
                )
            self.activation.modifiers = filtered

        # Scancode must be a non-negative int.
        try:
            self.activation.scancode = max(0, int(self.activation.scancode))
        except (TypeError, ValueError):
            logger.warning("Invalid activation.scancode; resetting to 0")
            self.activation.scancode = 0

        # Validate engine selection.
        if self.engine.type not in ("whisper", "nemotron"):
            logger.warning("Invalid engine '%s'; defaulting to 'nemotron'", self.engine.type)
            self.engine.type = "nemotron"

        # Validate nemotron model name + language (default invalid -> safe).
        if not isinstance(self.engine.nemotron_model, str) or not self.engine.nemotron_model:
            logger.warning("Invalid nemotron_model; defaulting to %r", DEFAULT_NEMOTRON_MODEL)
            self.engine.nemotron_model = DEFAULT_NEMOTRON_MODEL
        if (
            not isinstance(self.engine.nemotron_language, str)
            or self.engine.nemotron_language not in NEMOTRON_LANGUAGES
        ):
            logger.warning(
                "Invalid nemotron_language '%s'; defaulting to 'auto'",
                self.engine.nemotron_language,
            )
            self.engine.nemotron_language = "auto"

        # Engine booleans + gpu_device range.
        self.engine.force_cpu = bool(self.engine.force_cpu)
        self.engine.translate_to_english = bool(self.engine.translate_to_english)
        try:
            gpu_device = int(self.engine.gpu_device)
        except (TypeError, ValueError):
            logger.warning("Invalid gpu_device; defaulting to -1 (auto)")
            gpu_device = -1
        # -1 == auto-select, anything below that is invalid; cap absurd values.
        if gpu_device < -1 or gpu_device > 15:
            logger.warning("gpu_device %s out of range; defaulting to -1 (auto)", gpu_device)
            gpu_device = -1
        self.engine.gpu_device = gpu_device

        # Validate output.
        if self.output.mode not in ("injection", "clipboard", "auto"):
            logger.warning("Invalid output_mode '%s'; defaulting to 'auto'", self.output.mode)
            self.output.mode = "auto"
        self.output.sound_effects = bool(self.output.sound_effects)

        # Validate recording.
        try:
            self.recording.max_seconds = int(self.recording.max_seconds)
        except (TypeError, ValueError):
            logger.warning("Invalid max_seconds; defaulting to 300")
            self.recording.max_seconds = 300
        if self.recording.max_seconds < 1:
            logger.warning("max_seconds too low; clamping to 1")
            self.recording.max_seconds = 1
        elif self.recording.max_seconds > 600:
            logger.warning("max_seconds too high; clamping to 600")
            self.recording.max_seconds = 600
        if self.recording.sample_rate != 16000:
            logger.warning("sample_rate %s not supported; forcing 16000", self.recording.sample_rate)
            self.recording.sample_rate = 16000

        # Validate UI overlay position - must be a [int, int] list.
        pos = self.ui.overlay_position
        if (
            not isinstance(pos, list)
            or len(pos) != 2
            or not all(isinstance(v, (int, float)) for v in pos)
        ):
            logger.warning("Invalid overlay_position %r; resetting", pos)
            self.ui.overlay_position = [960, 1000]
        else:
            self.ui.overlay_position = [int(pos[0]), int(pos[1])]
        self.ui.show_on_startup = bool(self.ui.show_on_startup)

        return self


def get_platform() -> str:
    """Get the current platform identifier (Windows only)."""
    return "windows"
