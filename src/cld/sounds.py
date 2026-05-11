"""Audio feedback for CLD (Windows only)."""

import logging
import sys
from pathlib import Path
from typing import Literal

# winsound is a Windows-only stdlib module. Guard the import so that
# importing this module on non-Windows (tests, packaging tools, lint)
# doesn't blow up; play_sound() becomes a no-op when winsound is missing.
if sys.platform == "win32":
    import winsound  # type: ignore[import-not-found]
else:  # pragma: no cover - non-windows
    winsound = None  # type: ignore[assignment]

SoundEvent = Literal["start", "stop", "complete", "error", "warning"]
_logger = logging.getLogger(__name__)


from cld.runtime import is_frozen as _is_frozen  # noqa: E402


def _get_exe_dir() -> Path:
    """Get directory containing the executable."""
    return Path(sys.executable).parent


def _get_sounds_dir() -> Path:
    """Get the sounds directory."""
    if _is_frozen():
        exe_dir = _get_exe_dir()
        # Nuitka standalone: sounds/ next to exe
        nuitka_path = exe_dir / "sounds"
        if nuitka_path.exists():
            return nuitka_path
        # PyInstaller onedir: _internal/sounds
        pyinst_path = exe_dir / "_internal" / "sounds"
        if pyinst_path.exists():
            return pyinst_path
        # PyInstaller onefile: _MEIPASS/sounds
        if hasattr(sys, '_MEIPASS'):
            meipass_path = Path(sys._MEIPASS) / "sounds"
            if meipass_path.exists():
                return meipass_path
    # Development: relative to source file
    return Path(__file__).parent.parent.parent / "sounds"


def play_sound(event: SoundEvent) -> None:
    """Play a sound for the given event.

    Args:
        event: The type of sound event to play.
    """
    if winsound is None:
        # Non-Windows platforms have no winsound; skip silently. Cosmetic
        # path only - logged at debug level so we keep a trace for support
        # rather than swallowing every audio-feedback failure invisibly.
        _logger.debug("play_sound(%s): winsound unavailable on this platform", event)
        return
    try:
        sounds_dir = _get_sounds_dir()
        sound_file = sounds_dir / f"{event}.wav"
        if sound_file.exists():
            winsound.PlaySound(str(sound_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return

        sound_map = {
            "start": winsound.MB_OK,
            "stop": winsound.MB_OK,
            "complete": winsound.MB_OK,
            "error": winsound.MB_ICONHAND,
            "warning": winsound.MB_ICONEXCLAMATION,
        }
        sound_type = sound_map.get(event, winsound.MB_OK)
        winsound.MessageBeep(sound_type)
    except Exception:
        _logger.debug("play_sound(%s) failed", event, exc_info=True)
