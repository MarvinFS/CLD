"""Main daemon process for CLD - Windows-native implementation."""

import argparse
import ctypes
import getpass
import hashlib
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from cld.config import Config
from cld.engine_factory import build_engine
from cld.errors import EngineError, HotkeyError
from cld.hotkey import HotkeyListener
from cld.keyboard import test_injection
from cld.daemon_service import STTDaemon

# Stable app GUID for namespacing kernel objects across CLD releases.
_CLD_APP_GUID = "{8B9E2A4D-3F12-4C7C-9F1A-2F3D9F0B0001}"


def _user_scope() -> str:
    """Return a stable per-user scope tag for kernel-object names.

    Uses the SID hash when available (uniqueness even with same username on
    different machines), otherwise falls back to a hash of the username.
    Two different local users cannot accidentally fight over the same
    mutex / pipe, and a hostile process cannot guess the name without
    knowing the SID/username.
    """
    sid: Optional[str] = None
    try:
        import ctypes.wintypes as wintypes
        OpenProcessToken = ctypes.windll.advapi32.OpenProcessToken
        GetTokenInformation = ctypes.windll.advapi32.GetTokenInformation
        ConvertSidToStringSidW = ctypes.windll.advapi32.ConvertSidToStringSidW
        LocalFree = ctypes.windll.kernel32.LocalFree
        TOKEN_QUERY = 0x0008
        TokenUser = 1

        h_proc = ctypes.windll.kernel32.GetCurrentProcess()
        h_token = wintypes.HANDLE()
        if OpenProcessToken(h_proc, TOKEN_QUERY, ctypes.byref(h_token)):
            try:
                size = wintypes.DWORD(0)
                GetTokenInformation(h_token, TokenUser, None, 0, ctypes.byref(size))
                if size.value > 0:
                    buf = (ctypes.c_byte * size.value)()
                    if GetTokenInformation(
                        h_token, TokenUser, buf, size.value, ctypes.byref(size)
                    ):
                        # TOKEN_USER starts with SID_AND_ATTRIBUTES whose first
                        # field is a PSID pointer.
                        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
                        str_sid_ptr = ctypes.c_wchar_p()
                        if ConvertSidToStringSidW(psid, ctypes.byref(str_sid_ptr)):
                            sid = str_sid_ptr.value
                            LocalFree(ctypes.cast(str_sid_ptr, ctypes.c_void_p))
            finally:
                ctypes.windll.kernel32.CloseHandle(h_token)
    except Exception:
        sid = None

    seed = sid or getpass.getuser() or "default"
    return hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:16]


# Per-user kernel-object names. ``Local\`` confines them to the current
# Terminal Services session so RDP and fast-user-switching users get their
# own namespace; ``{guid}-{user_hash}`` makes the name unpredictable enough
# that a hostile local process can't trivially squat the mutex to lock out CLD.
_USER_SCOPE = _user_scope()
MUTEX_NAME = f"Local\\CLD-{_CLD_APP_GUID}-{_USER_SCOPE}-SingleInstance"
SHUTDOWN_PIPE_NAME = f"\\\\.\\pipe\\CLD-{_USER_SCOPE}-shutdown"

# Global mutex handle (kept alive while running)
_mutex_handle = None


from cld.runtime import is_frozen as _is_frozen  # noqa: E402


def _get_plugin_root() -> Path:
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _acquire_mutex() -> bool:
    """Acquire the single-instance mutex.

    Returns:
        True if mutex acquired (we're the only instance),
        False if another instance is running.
    """
    global _mutex_handle

    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183

    # Create or open the mutex
    _mutex_handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)

    if _mutex_handle is None:
        return False

    # Check if we created it or if it already existed
    last_error = kernel32.GetLastError()
    if last_error == ERROR_ALREADY_EXISTS:
        # Another instance owns the mutex
        kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
        return False

    return True


def _release_mutex() -> None:
    """Release the single-instance mutex."""
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None


def is_daemon_running() -> bool:
    """Check if daemon is running using mutex."""
    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183

    # Try to create the mutex
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if handle is None:
        return False

    last_error = kernel32.GetLastError()
    kernel32.CloseHandle(handle)

    # If ERROR_ALREADY_EXISTS, another instance holds it
    return last_error == ERROR_ALREADY_EXISTS


# Shared shutdown signal: a daemon thread writes its PID to this file and
# polls it; once removed, the file disappearing is interpreted as "please
# shut down". The IPC pipe (preferred path) is set up by the daemon service.
_SHUTDOWN_FLAG_NAME = "daemon.shutdown"


def get_shutdown_flag_path() -> Path:
    """Path of the on-disk shutdown sentinel."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    base = Path(localappdata) / "CLD" if localappdata else Path.home() / ".cld"
    return base / _SHUTDOWN_FLAG_NAME


def request_shutdown_via_ipc(timeout: float = 3.0) -> bool:
    """Politely ask the running daemon to shut itself down.

    Tries the named pipe first (fast, in-process notification), then falls
    back to a filesystem sentinel that the daemon's poll loop notices. Only
    if neither produces a clean shutdown does ``stop_daemon()`` resort to
    ``taskkill``.

    Args:
        timeout: Seconds to wait for the daemon to actually exit (observed
            by the mutex being released).

    Returns:
        True if the daemon was running and exited within ``timeout``.
    """
    logger = logging.getLogger(__name__)
    if not is_daemon_running():
        return False

    delivered = False
    try:
        # Pipe path: writes a single line "shutdown\n" and closes.
        with open(SHUTDOWN_PIPE_NAME, "wb") as fh:
            fh.write(b"shutdown\n")
            fh.flush()
        delivered = True
    except OSError as e:
        logger.debug("Shutdown pipe unavailable (%s); using flag file", e)

    if not delivered:
        try:
            flag = get_shutdown_flag_path()
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(str(int(time.time())), encoding="utf-8")
            delivered = True
        except OSError as e:
            logger.debug("Could not write shutdown flag: %s", e)
            return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_daemon_running():
            return True
        time.sleep(0.1)
    return False


def _get_pid_file_path() -> Path:
    """Get the path to the daemon PID file."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        return Path(localappdata) / "CLD" / "daemon.pid"
    return Path.home() / ".cld" / "daemon.pid"


def _write_pid_file() -> None:
    """Write current process PID to the PID file."""
    pid_path = _get_pid_file_path()
    try:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))
    except Exception:
        logging.getLogger(__name__).debug("Failed to write PID file", exc_info=True)


def _read_pid_file() -> Optional[int]:
    """Read PID from file and validate the process exists.

    Returns the PID if the file exists and the process is alive, else None.
    """
    pid_path = _get_pid_file_path()
    try:
        if not pid_path.exists():
            return None
        pid = int(pid_path.read_text().strip())
        # Validate process exists (signal 0 = check existence)
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        return None
    except Exception:
        return None


def _remove_pid_file() -> None:
    """Delete the PID file."""
    try:
        pid_path = _get_pid_file_path()
        if pid_path.exists():
            pid_path.unlink()
    except Exception:
        logging.getLogger(__name__).debug("Failed to remove PID file", exc_info=True)


def _find_cld_processes() -> list[int]:
    """Find all CLD daemon processes by command line.

    Searches for both Python-based (running from source) and frozen exe processes.
    Falls back to PID file when PowerShell finds nothing.
    """
    pids = []
    try:
        # Use PowerShell to find CLD processes - both source and frozen exe
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process | "
                "Where-Object { "
                "($_.CommandLine -like '*cld.daemon*' -and $_.CommandLine -like '*python*') -or "
                "($_.Name -eq 'CLD.exe' -and $_.CommandLine -like '*daemon*')"
                " } | "
                "Select-Object -ExpandProperty ProcessId"
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    # Don't include ourselves
                    if pid != os.getpid():
                        pids.append(pid)
    except Exception:
        logging.getLogger(__name__).debug("Failed to find CLD processes via PowerShell", exc_info=True)

    # Fallback: check PID file if PowerShell found nothing
    if not pids:
        pid = _read_pid_file()
        if pid and pid != os.getpid():
            pids.append(pid)

    return pids


def _spawn_background(enable_overlay: bool = False) -> bool:
    """Spawn daemon in background.

    Note: In normal mode, daemon.log is not created. The background process
    runs silently without file logging. Use --debug flag for logging.
    """
    env = os.environ.copy()
    env.setdefault("CLAUDE_PLUGIN_ROOT", str(_get_plugin_root()))

    # Detect if running as frozen exe (PyInstaller or Nuitka)
    if _is_frozen():
        # Running as exe - use the actual exe path
        # In Nuitka, sys.executable points to python.exe, not the main exe
        # We need to find the actual CLD.exe path
        main_mod = sys.modules.get("__main__", None)
        if main_mod and hasattr(main_mod, "__compiled__"):
            # Nuitka: get exe path from sys.argv[0], ensure absolute
            exe_path = Path(sys.argv[0]).resolve() if sys.argv else Path(sys.executable).resolve()
            exe_path = str(exe_path)
        else:
            # PyInstaller: sys.executable is the exe
            exe_path = sys.executable
        cmd = [exe_path, "daemon", "run"]
    else:
        # Running as Python script
        cmd = [sys.executable, "-m", "cld.daemon", "run"]

    if enable_overlay:
        cmd.append("--overlay")

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    if enable_overlay:
        # Use CREATE_NO_WINDOW to prevent console but keep window station for pynput
        CREATE_NO_WINDOW = 0x08000000
        creationflags |= CREATE_NO_WINDOW
    else:
        # Fully detach when no GUI needed
        creationflags |= subprocess.DETACHED_PROCESS

    try:
        # Run without log file - daemon runs silently in normal mode
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        # Wait for daemon to acquire the mutex AND for the PID file to
        # report our newly-spawned child's PID. The child's startup
        # ordering is: _acquire_mutex() -> _write_pid_file() ->
        # STTDaemon.run(). The PID file therefore appears slightly AFTER
        # the mutex, so we keep polling until the PID file catches up or
        # the deadline expires - bailing the moment they disagree would
        # produce a false negative on every fast spawn.
        logger = logging.getLogger(__name__)
        deadline = time.monotonic() + 5.0  # 5s total
        mutex_first_seen: Optional[float] = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                logger.error("Spawned daemon exited prematurely (code %s)", proc.returncode)
                return False
            mutex_held = is_daemon_running()
            if mutex_held:
                pid_in_file = _read_pid_file()
                if pid_in_file == proc.pid:
                    logger.info("Daemon started in background (PID %d).", proc.pid)
                    return True
                if mutex_first_seen is None:
                    mutex_first_seen = time.monotonic()
                # If the mutex has been held for >2s but the PID file still
                # doesn't point at us, something else holds it (zombie /
                # other instance). Bail out so the caller can clean up.
                if time.monotonic() - mutex_first_seen > 2.0 and pid_in_file is not None:
                    logger.warning(
                        "Mutex held by PID %s for >2s (we spawned %s); refusing to claim success",
                        pid_in_file, proc.pid,
                    )
                    return False
            time.sleep(0.1)

        logger.warning("Daemon did not start within 5 seconds.")
        return False
    except Exception:
        logging.getLogger(__name__).exception("Failed to spawn background daemon")
        return False


def _cleanup_stale_state() -> None:
    """Remove orphan state files left by a previously-crashed daemon.

    When the daemon crashes (e.g., native segfault during sleep/wake recovery),
    Windows auto-releases its mutex but leaves behind disk artifacts:
      - daemon.pid pointing to a dead PID
      - settings.json.lock from a config write that never finished
      - daemon.shutdown sentinel from an aborted shutdown request

    These do not block a fresh daemon from starting (mutex is the real gate),
    but they can confuse external tooling and surface as "ghost state" in
    diagnostics. Clean them up proactively if no live daemon owns them.

    Safe to call before _acquire_mutex(): only removes files whose referenced
    process is provably dead, so a live daemon's files are never touched.
    """
    logger = logging.getLogger(__name__)
    localappdata = os.environ.get("LOCALAPPDATA", "")
    base = Path(localappdata) / "CLD" if localappdata else Path.home() / ".cld"
    if not base.exists():
        return

    pid_path = base / "daemon.pid"
    if pid_path.exists():
        live_pid = _read_pid_file()  # returns None if process is dead
        if live_pid is None:
            try:
                stale = pid_path.read_text().strip()
            except Exception:
                stale = "?"
            try:
                pid_path.unlink()
                logger.info("Removed stale daemon.pid (PID %s no longer alive)", stale)
            except OSError:
                logger.debug("Failed to remove stale daemon.pid", exc_info=True)

    for orphan_name in ("settings.json.lock", "daemon.shutdown"):
        orphan = base / orphan_name
        if not orphan.exists():
            continue
        if is_daemon_running():
            # A live daemon may legitimately hold these; do not touch.
            continue
        try:
            orphan.unlink()
            logger.info("Removed orphan %s (no live daemon)", orphan_name)
        except OSError:
            logger.debug("Failed to remove orphan %s", orphan_name, exc_info=True)


def start_daemon(background: bool = False, enable_overlay: bool = False):
    """Start the daemon.

    Args:
        background: If True, daemonize the process.
        enable_overlay: If True, show GUI overlay.
    """
    _cleanup_stale_state()
    if is_daemon_running():
        logger = logging.getLogger(__name__)
        # Check if the existing instance might be a zombie (e.g., survived sleep/wake
        # but is unresponsive). If PID file is stale (>30s old) and processes exist,
        # kill them and retry.
        pid_path = _get_pid_file_path()
        try:
            if pid_path.exists():
                age = time.time() - pid_path.stat().st_mtime
                if age > 30:
                    pids = _find_cld_processes()
                    if pids:
                        logger.info("Found potentially zombie daemon (PID file age: %.0fs), killing processes %s", age, pids)
                        for pid in pids:
                            try:
                                subprocess.run(
                                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                                    capture_output=True, timeout=5,
                                )
                            except Exception:
                                pass
                        _remove_pid_file()
                        time.sleep(1)
                        if not is_daemon_running():
                            logger.info("Zombie cleaned up, proceeding with startup")
                        else:
                            logger.info("Daemon is still running after cleanup attempt.")
                            return
                    else:
                        logger.info("Daemon is already running.")
                        return
                else:
                    logger.info("Daemon is already running.")
                    return
            else:
                logger.info("Daemon is already running.")
                return
        except Exception:
            logger.info("Daemon is already running.")
            return

    if background:
        if _spawn_background(enable_overlay=enable_overlay):
            return
        logging.getLogger(__name__).warning(
            "Background spawn failed; running in foreground"
        )

    # Acquire mutex for single instance
    if not _acquire_mutex():
        logging.getLogger(__name__).info("Daemon is already running.")
        return

    _write_pid_file()
    try:
        daemon = STTDaemon(enable_overlay=enable_overlay)
        daemon.run()
    finally:
        _remove_pid_file()
        _release_mutex()


def stop_daemon():
    """Stop the running daemon.

    Prefers graceful IPC shutdown (named pipe, then on-disk sentinel) so the
    daemon can drain in-flight transcription, save config, and free Vulkan
    handles cleanly. ``taskkill`` is only used as a last resort when the
    daemon doesn't honour the shutdown request within a deadline.
    """
    logger = logging.getLogger(__name__)

    if not is_daemon_running():
        logger.info("Daemon is not running.")
        return

    # 1. Graceful: poke the IPC channel and wait briefly for the mutex to
    # drop on its own.
    if request_shutdown_via_ipc(timeout=5.0):
        # Clean up any leftover shutdown flag the daemon didn't get to.
        try:
            get_shutdown_flag_path().unlink()
        except OSError:
            pass
        logger.info("Daemon stopped.")
        return

    logger.warning("Graceful shutdown did not complete; falling back to taskkill")

    pids = _find_cld_processes()
    if not pids:
        logger.warning("Daemon appears running but no CLD process found.")
        return

    for pid in pids:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("Sent stop signal to daemon (PID %s)", pid)
            else:
                logger.warning("Failed to stop PID %s: %s", pid, result.stderr.strip())
        except Exception as e:
            logger.warning("Error stopping PID %s: %s", pid, e)

    # Wait for mutex to be released
    for _ in range(50):  # 5 seconds
        time.sleep(0.1)
        if not is_daemon_running():
            logger.info("Daemon stopped.")
            return

    # Force kill if still running
    logger.warning("Daemon did not stop gracefully, forcing...")
    pids = _find_cld_processes()
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

    # Last resort: kill by image name (catches frozen exe processes)
    if is_daemon_running():
        try:
            subprocess.run(
                ["taskkill", "/IM", "CLD.exe", "/F"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

    _remove_pid_file()
    try:
        get_shutdown_flag_path().unlink()
    except OSError:
        pass
    logger.info("Daemon stopped.")


def daemon_status():
    """Print daemon status."""
    logger = logging.getLogger(__name__)
    running = is_daemon_running()

    if running:
        pids = _find_cld_processes()
        if pids:
            logger.info("Daemon is running (PID %s)", ", ".join(map(str, pids)))
        else:
            logger.info("Daemon is running")
    else:
        logger.info("Daemon is not running.")

    config = Config.load().validate()
    logger.info("Config path: %s", Config.get_config_path())
    logger.info("Hotkey: %s", config.hotkey)
    logger.info("Mode: %s", config.mode)
    logger.info("Engine: %s", config.engine.type)

    try:
        engine = build_engine(config)
        if engine.is_available():
            logger.info("Engine availability: ready")
        else:
            logger.warning("Engine availability: missing dependencies")
    except EngineError as exc:
        logger.warning("Engine availability: %s", exc)

    if config.output_mode == "auto":
        injection_ready = test_injection()
        output_label = "injection" if injection_ready else "clipboard"
        logger.info("Output mode: auto (%s)", output_label)
    else:
        logger.info("Output mode: %s", config.output_mode)

    if running:
        logger.info("Hotkey readiness: managed by daemon")
        return

    try:
        listener = HotkeyListener(hotkey=config.hotkey, mode=config.mode)
    except HotkeyError as exc:
        logger.warning("Hotkey readiness: %s", exc)
        return

    try:
        if listener.start():
            logger.info("Hotkey readiness: ready")
        else:
            logger.warning("Hotkey readiness: failed to start")
    finally:
        listener.stop()


def setup_logging(level: str) -> None:
    """Configure logging - only in debug mode.

    In normal mode, no logging is configured (defaults to WARNING level, no file).
    In debug mode (CLD_DEBUG_MODE=1), full logging is enabled to console.
    """
    debug_mode = os.environ.get("CLD_DEBUG_MODE") == "1"
    if debug_mode:
        logging.basicConfig(
            level="DEBUG",
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        # Normal mode: minimal logging, no daemon.log file
        logging.basicConfig(
            level=level.upper(),
            format="%(levelname)s: %(message)s",
        )


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for the daemon."""
    default_log_level = os.environ.get("CLD_LOG_LEVEL", "INFO")
    parser = argparse.ArgumentParser(description="CLD daemon")
    parser.add_argument(
        "command",
        choices=["start", "stop", "status", "run"],
        help="Command to execute",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="Run daemon in background",
    )
    parser.add_argument(
        "--log-level",
        default=default_log_level,
        help="Logging level (default: CLD_LOG_LEVEL or INFO).",
    )
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="Show GUI overlay for visual feedback.",
    )

    args = parser.parse_args(argv)
    setup_logging(args.log_level)

    if args.command == "start":
        start_daemon(background=args.background, enable_overlay=args.overlay)
    elif args.command == "stop":
        stop_daemon()
    elif args.command == "status":
        daemon_status()
    elif args.command == "run":
        # Run in foreground (for debugging)
        start_daemon(background=False, enable_overlay=args.overlay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
