"""Global hotkey detection using pynput."""

import logging
import queue
import threading
import time
from typing import Callable, Optional

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
    _PYNPUT_IMPORT_ERROR: Exception | None = None
except Exception as exc:
    keyboard = None
    _PYNPUT_AVAILABLE = False
    _PYNPUT_IMPORT_ERROR = exc

from cld.errors import HotkeyError

# Toggle mode debounce time in seconds (prevents rapid key presses from triggering multiple start/stop cycles)
TOGGLE_DEBOUNCE_SECONDS = 0.3


class HotkeyListener:
    """Listens for global hotkey events.

    Supports both push-to-talk (hold to record) and toggle modes.
    """

    def __init__(
        self,
        hotkey: str = "<ctrl>+<shift>+space",
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        mode: str = "push-to-talk",
    ):
        """Initialize the hotkey listener.

        Args:
            hotkey: Hotkey combination string (pynput format).
            on_start: Callback when recording should start.
            on_stop: Callback when recording should stop.
            mode: "push-to-talk" or "toggle".
        """
        self.hotkey_str = hotkey
        self.on_start = on_start
        self.on_stop = on_stop
        self.mode = mode

        self._listener: Optional[keyboard.Listener] = None
        self._is_recording = False
        self._pressed_keys: set = set()
        self._hotkey_active = False
        self._last_toggle_time: float = 0
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._event_queue: "queue.Queue[Optional[tuple[str, Optional[Callable[[], None]]]]]" = (
            queue.Queue(maxsize=8)
        )
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_stop = threading.Event()

        # Track if hotkey uses specific modifier variants (not generic)
        # This affects key normalization during matching
        hotkey_lower = hotkey.lower()
        self._use_specific_alt = any(x in hotkey_lower for x in ["alt_gr", "alt_r", "alt_l"])
        self._use_specific_ctrl = any(x in hotkey_lower for x in ["ctrl_r", "ctrl_l"])
        self._use_specific_shift = any(x in hotkey_lower for x in ["shift_r", "shift_l"])

        if not _PYNPUT_AVAILABLE:
            message = "pynput unavailable; hotkeys cannot be registered"
            if _PYNPUT_IMPORT_ERROR:
                message = f"{message}: {_PYNPUT_IMPORT_ERROR}"
            raise HotkeyError(message)

        # Parse the hotkey
        self._hotkey_keys = self._parse_hotkey(hotkey)
        if not self._hotkey_keys:
            raise HotkeyError(f"Hotkey '{hotkey}' did not map to any keys")

    def _parse_hotkey(self, hotkey_str: str) -> set:
        """Parse hotkey string to a set of keys.

        Args:
            hotkey_str: Hotkey like "<ctrl>+<shift>+space" or "ctrl+shift+space".

        Returns:
            Set of key objects.
        """
        if not hotkey_str.strip():
            raise HotkeyError("Hotkey cannot be empty")

        try:
            normalized_str = self._normalize_hotkey_string(hotkey_str)
            self._logger.debug("Parsing hotkey: '%s' -> '%s'", hotkey_str, normalized_str)
            keys = keyboard.HotKey.parse(normalized_str)
            self._logger.debug("HotKey.parse returned: %s", keys)
        except Exception as exc:
            # Try fallback: direct key lookup for single keys
            key_name = hotkey_str.strip("<>").lower()
            fallback_key = self._try_key_lookup(key_name)
            if fallback_key:
                self._logger.info("Using fallback key lookup for '%s': %s", hotkey_str, fallback_key)
                return {self._normalize_key(fallback_key, for_matching=True)}
            raise HotkeyError(f"Invalid hotkey '{hotkey_str}': {exc}") from exc

        result: set = set()
        for key in keys:
            normalized_key = self._normalize_key(key, for_matching=True)
            if normalized_key is not None:
                result.add(normalized_key)
                self._logger.debug("Key %s normalized to %s", key, normalized_key)
        return result

    def _try_key_lookup(self, key_name: str) -> Optional[object]:
        """Try to look up a key by name directly from keyboard.Key or as a character."""
        # Map common names to keyboard.Key attributes
        key_map = {
            "alt_gr": "alt_gr",
            "altgr": "alt_gr",
            "alt_r": "alt_r",
            "alt_l": "alt_l",
            "right_alt": "alt_r",
            "left_alt": "alt_l",
            "ctrl_r": "ctrl_r",
            "ctrl_l": "ctrl_l",
            "right_ctrl": "ctrl_r",
            "left_ctrl": "ctrl_l",
            "shift_r": "shift_r",
            "shift_l": "shift_l",
            "right_shift": "shift_r",
            "left_shift": "shift_l",
            "space": "space",
            "tab": "tab",
            "enter": "enter",
            "return": "enter",
            "esc": "esc",
            "escape": "esc",
            "alt": "alt",
            "ctrl": "ctrl",
            "shift": "shift",
        }

        attr_name = key_map.get(key_name, key_name)
        if hasattr(keyboard.Key, attr_name):
            return getattr(keyboard.Key, attr_name)

        # If it's a single character, create a KeyCode for it
        if len(key_name) == 1:
            return keyboard.KeyCode.from_char(key_name)

        return None

    def _normalize_hotkey_string(self, hotkey_str: str) -> str:
        parts = [part.strip() for part in hotkey_str.split("+") if part.strip()]
        if not parts:
            return hotkey_str

        key_map = {
            "ctrl": "<ctrl>",
            "control": "<ctrl>",
            "shift": "<shift>",
            "alt": "<alt>",
            "cmd": "<cmd>",
            "command": "<cmd>",
            "space": "<space>",
            "enter": "<enter>",
            "return": "<enter>",
            "tab": "<tab>",
            "esc": "<esc>",
            "escape": "<esc>",
        }

        normalized_parts = []
        for part in parts:
            lowered = part.lower()
            if lowered.startswith("<") and lowered.endswith(">"):
                normalized_parts.append(lowered)
                continue
            if lowered in key_map:
                normalized_parts.append(key_map[lowered])
                continue
            if lowered.startswith("f") and lowered[1:].isdigit():
                normalized_parts.append(f"<{lowered}>")
                continue
            normalized_parts.append(lowered)

        return "+".join(normalized_parts)

    def _ensure_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._event_worker,
            name="cld-hotkey-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def _event_worker(self) -> None:
        while not self._worker_stop.is_set():
            try:
                item = self._event_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                return
            label, callback = item
            if not callback:
                continue
            try:
                callback()
            except Exception:
                self._logger.exception("Hotkey callback failed: %s", label)

    def _enqueue_event(self, label: str, callback: Optional[Callable[[], None]]) -> None:
        self._ensure_worker()
        try:
            self._event_queue.put_nowait((label, callback))
        except queue.Full:
            self._logger.warning("Dropping hotkey event '%s'; queue full", label)

    def _normalize_key(self, key, for_matching: bool = True) -> Optional[object]:
        """Normalize a key to a comparable form.

        Args:
            key: The key to normalize.
            for_matching: If True, normalize left/right variants to generic form
                         (unless hotkey uses specific variants).
                         If False, keep specific variants (for parsing hotkey config).
        """
        # Handle KeyCode objects with virtual key codes
        if hasattr(key, "vk") and key.vk is not None:
            # Map Windows VK codes to keyboard.Key for special keys
            # Use specific variants if hotkey requires them
            if self._use_specific_alt:
                vk_alt_map = {
                    164: keyboard.Key.alt_l,   # VK_LMENU (left alt)
                    165: getattr(keyboard.Key, "alt_gr", keyboard.Key.alt_r),  # VK_RMENU (right alt / alt_gr)
                }
            else:
                vk_alt_map = {
                    164: keyboard.Key.alt,     # VK_LMENU -> generic alt
                    165: keyboard.Key.alt,     # VK_RMENU -> generic alt
                }

            if self._use_specific_ctrl:
                vk_ctrl_map = {
                    162: keyboard.Key.ctrl_l,  # VK_LCONTROL
                    163: keyboard.Key.ctrl_r,  # VK_RCONTROL
                }
            else:
                vk_ctrl_map = {
                    162: keyboard.Key.ctrl,    # VK_LCONTROL -> generic ctrl
                    163: keyboard.Key.ctrl,    # VK_RCONTROL -> generic ctrl
                }

            if self._use_specific_shift:
                vk_shift_map = {
                    160: keyboard.Key.shift_l, # VK_LSHIFT
                    161: keyboard.Key.shift_r, # VK_RSHIFT
                }
            else:
                vk_shift_map = {
                    160: keyboard.Key.shift,   # VK_LSHIFT -> generic shift
                    161: keyboard.Key.shift,   # VK_RSHIFT -> generic shift
                }

            vk_special_map = {
                32: keyboard.Key.space,      # VK_SPACE
                13: keyboard.Key.enter,      # VK_RETURN
                9: keyboard.Key.tab,         # VK_TAB
                27: keyboard.Key.esc,        # VK_ESCAPE
                **vk_alt_map,
                **vk_ctrl_map,
                **vk_shift_map,
            }
            if key.vk in vk_special_map:
                return vk_special_map[key.vk]

            # Map VK codes to characters (needed when Ctrl/Alt is held)
            # When modifier is pressed, pynput sends VK codes instead of chars
            vk_char_map = {
                # Symbol keys
                186: ';', 187: '=', 188: ',', 189: '-', 190: '.',
                191: '/', 192: '`', 219: '[', 220: '\\', 221: ']', 222: "'",
            }
            # Add letters A-Z (VK 65-90)
            for i in range(65, 91):
                vk_char_map[i] = chr(i).lower()
            # Add numbers 0-9 (VK 48-57)
            for i in range(48, 58):
                vk_char_map[i] = chr(i)

            if key.vk in vk_char_map:
                return keyboard.KeyCode.from_char(vk_char_map[key.vk])

        if hasattr(key, "char") and key.char:
            if key.char == " ":
                return keyboard.Key.space
            if key.char in ("\n", "\r"):
                return keyboard.Key.enter
            return keyboard.KeyCode.from_char(key.char.lower())

        # Handle left/right modifier variants
        # When for_matching=True (key presses), normalize to generic form
        # UNLESS the hotkey uses specific variants
        if for_matching:
            # Ctrl variants
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                if not self._use_specific_ctrl:
                    return keyboard.Key.ctrl
                # Keep specific variant
                return key

            # Shift variants
            if key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
                if not self._use_specific_shift:
                    return keyboard.Key.shift
                return key

            # Alt variants (including alt_gr)
            alt_keys = [keyboard.Key.alt_l, keyboard.Key.alt_r]
            if hasattr(keyboard.Key, "alt_gr"):
                alt_keys.append(keyboard.Key.alt_gr)
            if key in alt_keys:
                if not self._use_specific_alt:
                    return keyboard.Key.alt
                # Keep specific variant - but note that alt_r and alt_gr
                # may need special handling on some keyboards
                return key

            if key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r):
                return keyboard.Key.cmd

        return key

    def _on_press(self, key):
        """Handle key press event.

        Note: This receives ALL keyboard events from pynput's global listener.
        We intentionally do NOT log individual key presses for privacy reasons.
        Only the hotkey match itself is logged.
        """
        normalized = self._normalize_key(key, for_matching=True)
        if normalized is None:
            return

        with self._lock:
            self._pressed_keys.add(normalized)

            # Check if hotkey combination is pressed
            if self._hotkey_keys.issubset(self._pressed_keys):
                if self._hotkey_active:
                    return
                self._hotkey_active = True
                if self.mode == "toggle":
                    # Toggle mode: press to start/stop with debounce
                    current = time.time()
                    if current - self._last_toggle_time < TOGGLE_DEBOUNCE_SECONDS:
                        return
                    self._last_toggle_time = current

                    if not self._is_recording:
                        self._is_recording = True
                        self._enqueue_event("start", self.on_start)
                    else:
                        self._is_recording = False
                        self._enqueue_event("stop", self.on_stop)
                else:
                    # Push-to-talk: press to start
                    if not self._is_recording:
                        self._is_recording = True
                        self._enqueue_event("start", self.on_start)

    def _on_release(self, key):
        """Handle key release event."""
        normalized = self._normalize_key(key, for_matching=True)
        if normalized is None:
            return

        with self._lock:
            self._pressed_keys.discard(normalized)

            # Check if released key is part of hotkey (compare by value, not object identity)
            is_hotkey_key = self._key_in_set(normalized, self._hotkey_keys)

            if is_hotkey_key:
                self._hotkey_active = False

            # In push-to-talk mode, release any hotkey key to stop
            if self.mode == "push-to-talk" and self._is_recording:
                if is_hotkey_key:
                    self._is_recording = False
                    self._enqueue_event("stop", self.on_stop)

    def _key_in_set(self, key, key_set) -> bool:
        """Check if a key is in a set, handling KeyCode comparison properly."""
        # Direct membership check
        if key in key_set:
            return True

        # For KeyCode objects, compare by char value
        if hasattr(key, 'char') and key.char:
            for k in key_set:
                if hasattr(k, 'char') and k.char == key.char:
                    return True
                # Also check if it's a raw string
                if isinstance(k, str) and k == key.char:
                    return True

        return False

    def start(self) -> bool:
        """Start listening for hotkeys.

        Returns:
            True if listener started successfully.
        """
        if not _PYNPUT_AVAILABLE:
            self._logger.error("pynput unavailable; cannot start hotkey listener")
            return False
        if self._listener is not None:
            self._logger.debug("Listener already running")
            return True

        try:
            self._logger.info("Starting keyboard listener for hotkey: %s (keys: %s)", self.hotkey_str, self._hotkey_keys)
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.start()
            self._ensure_worker()
            if not self._listener.is_alive():
                self._logger.error("Hotkey listener failed to start")
                self.stop()
                return False
            self._logger.info("Hotkey listener started successfully")
            return True
        except Exception as e:
            self._logger.error("Failed to start hotkey listener: %s", e)
            return False

    def stop(self):
        """Stop listening for hotkeys."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            self._pressed_keys.clear()
            self._is_recording = False

        # Stop worker thread
        self._worker_stop.set()
        try:
            self._event_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._listener is not None and self._listener.is_alive()

    @property
    def is_recording(self) -> bool:
        """Check if currently in recording state."""
        return self._is_recording
