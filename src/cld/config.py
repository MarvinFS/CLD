"""Configuration management for CLD."""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# Configuration schema version for migrations
CONFIG_VERSION = 1


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
    type: Literal["whisper"] = "whisper"  # Whisper for multilingual support
    whisper_model: str = "medium-q5_0"  # ~1.5GB, good accuracy
    force_cpu: bool = False  # Force CPU-only mode (ignore GPU)
    gpu_device: int = -1  # -1=auto-select, 0=first GPU, 1=second GPU, etc.
    translate_to_english: bool = False  # Translate non-English speech to English


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
        """
        override = os.environ.get("CLD_CONFIG_DIR")
        if override:
            return Path(override).expanduser()

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            config_dir = Path(local_app_data) / "CLD"
        else:
            config_dir = Path.home() / ".cld"

        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    @classmethod
    def _get_legacy_toml_path(cls) -> Optional[Path]:
        """Get path to legacy TOML config if it exists."""
        legacy_paths = [
            Path.home() / ".claude" / "plugins" / "claude-stt" / "config.toml",
        ]
        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if plugin_root:
            legacy_paths.insert(0, Path(plugin_root).expanduser() / "config.toml")

        for path in legacy_paths:
            if path.exists():
                return path
        return None

    @classmethod
    def get_config_path(cls) -> Path:
        """Get the configuration file path."""
        return cls.get_config_dir() / "settings.json"

    @classmethod
    def _migrate_from_toml(cls, toml_path: Path) -> Optional["Config"]:
        """Migrate configuration from legacy TOML format."""
        try:
            try:
                import tomllib as tomli
            except ImportError:
                try:
                    import tomli
                except ImportError:
                    logger.warning("Cannot migrate TOML config: tomli not installed")
                    return None

            with open(toml_path, "rb") as f:
                data = tomli.load(f)

            stt_config = data.get("claude-stt", {})

            # Map old config to new structure
            config = cls()

            # Activation settings
            old_hotkey = stt_config.get("hotkey", "ctrl+shift+space")
            if "alt_gr" in old_hotkey.lower():
                config.activation.key = "alt_gr"
                config.activation.scancode = 541
            else:
                config.activation.key = old_hotkey

            old_mode = stt_config.get("mode", "toggle")
            config.activation.mode = "toggle" if old_mode == "toggle" else "push_to_talk"

            # Engine settings (whisper only, moonshine deprecated)
            config.engine.type = "whisper"
            config.engine.whisper_model = stt_config.get("whisper_model", "medium")

            # Recording settings
            config.recording.max_seconds = stt_config.get("max_recording_seconds", 300)
            config.recording.sample_rate = stt_config.get("sample_rate", 16000)

            # Output settings
            config.output.mode = stt_config.get("output_mode", "auto")
            config.output.sound_effects = stt_config.get("sound_effects", True)

            logger.info("Migrated config from %s", toml_path)
            return config
        except Exception:
            logger.exception("Failed to migrate TOML config")
            return None

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

        # Try to migrate from legacy TOML
        legacy_path = cls._get_legacy_toml_path()
        if legacy_path:
            config = cls._migrate_from_toml(legacy_path)
            if config:
                config.save()
                return config

        # Return defaults
        return cls()

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary."""
        config = cls()

        # Handle version migration if needed
        version = data.get("version", 1)
        if version < CONFIG_VERSION:
            logger.info("Migrating config from version %d to %d", version, CONFIG_VERSION)

        # Load activation settings
        if "activation" in data:
            act = data["activation"]
            config.activation = ActivationConfig(
                key=act.get("key", config.activation.key),
                scancode=act.get("scancode", config.activation.scancode),
                modifiers=act.get("modifiers", config.activation.modifiers),
                mode=act.get("mode", config.activation.mode),
                enabled=act.get("enabled", config.activation.enabled),
            )

        # Load engine settings
        if "engine" in data:
            eng = data["engine"]
            # Handle backwards compatibility: old "device": "cpu" -> new "force_cpu": true
            force_cpu = eng.get("force_cpu", False)
            if not force_cpu and eng.get("device") == "cpu":
                force_cpu = True
            config.engine = EngineConfig(
                type="whisper",  # Only whisper supported
                whisper_model=eng.get("whisper_model", config.engine.whisper_model),
                force_cpu=force_cpu,
                gpu_device=eng.get("gpu_device", config.engine.gpu_device),
                translate_to_english=eng.get("translate_to_english", config.engine.translate_to_english),
            )

        # Load output settings
        if "output" in data:
            out = data["output"]
            config.output = OutputConfig(
                mode=out.get("mode", config.output.mode),
                sound_effects=out.get("sound_effects", config.output.sound_effects),
            )

        # Load recording settings
        if "recording" in data:
            rec = data["recording"]
            config.recording = RecordingConfig(
                max_seconds=rec.get("max_seconds", config.recording.max_seconds),
                sample_rate=rec.get("sample_rate", config.recording.sample_rate),
            )

        # Load UI settings
        if "ui" in data:
            ui = data["ui"]
            config.ui = UIConfig(
                overlay_position=ui.get("overlay_position", config.ui.overlay_position),
                show_on_startup=ui.get("show_on_startup", config.ui.show_on_startup),
            )

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
        """Save configuration to file with retry logic for Windows file locking."""
        config_path = self.get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

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

            # Retry os.replace() with exponential backoff to handle file locking
            max_attempts = 3
            delays = [0.1, 0.2, 0.4]  # Exponential backoff delays in seconds

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
                        # Final attempt failed, re-raise
                        raise

            return False  # Should never reach here
        except Exception:
            logger.exception("Failed to save config")
            return False
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def validate(self) -> "Config":
        """Validate and normalize configuration values."""
        # Validate activation
        if not self.activation.key:
            logger.warning("Invalid activation key; defaulting to 'alt_gr'")
            self.activation.key = "alt_gr"
            self.activation.scancode = 541

        if self.activation.mode not in ("push_to_talk", "toggle"):
            logger.warning("Invalid mode '%s'; defaulting to 'push_to_talk'", self.activation.mode)
            self.activation.mode = "push_to_talk"

        # Validate engine (whisper only)
        if self.engine.type != "whisper":
            logger.warning("Invalid engine '%s'; defaulting to 'whisper'", self.engine.type)
            self.engine.type = "whisper"

        # Validate output
        if self.output.mode not in ("injection", "clipboard", "auto"):
            logger.warning("Invalid output_mode '%s'; defaulting to 'auto'", self.output.mode)
            self.output.mode = "auto"

        # Validate recording
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

        return self


def get_platform() -> str:
    """Get the current platform identifier (Windows only)."""
    return "windows"
