"""Audio feedback for CLD (Windows only)."""

import logging
import sys
import winsound
from pathlib import Path
from typing import Literal

SoundEvent = Literal["start", "stop", "complete", "error", "warning"]
_logger = logging.getLogger(__name__)


def _is_frozen() -> bool:
    """Check if running as frozen exe (PyInstaller or Nuitka)."""
    # PyInstaller sets sys.frozen
    if getattr(sys, 'frozen', False):
        return True
    # Nuitka sets __compiled__ on __main__
    main_mod = sys.modules.get('__main__', object())
    return '__compiled__' in dir(main_mod)


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
    try:
        # Check for custom sound files first
        sounds_dir = _get_sounds_dir()
        sound_file = sounds_dir / f"{event}.wav"
        if sound_file.exists():
            winsound.PlaySound(str(sound_file), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return

        # Fallback to Windows system sounds
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
        pass  # Silently fail
