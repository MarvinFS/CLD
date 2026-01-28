"""Main daemon process for CLD - Windows-native implementation."""

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

from cld.config import Config
from cld.engine_factory import build_engine
from cld.errors import EngineError, HotkeyError
from cld.hotkey import HotkeyListener
from cld.keyboard import test_injection
from cld.daemon_service import STTDaemon

# Windows mutex name for single instance
MUTEX_NAME = "CLD_SingleInstance_Mutex"

# VC++ Redistributable download URL
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def check_vcruntime() -> bool:
    """Check if Visual C++ Runtime is installed.

    Returns:
        True if installed, False otherwise.
    """
    system32 = Path(os.environ.get("SYSTEMROOT", "C:\\Windows")) / "System32"
    required_dlls = ["msvcp140.dll", "vcruntime140.dll"]

    for dll in required_dlls:
        if not (system32 / dll).exists():
            return False
    return True


def show_vcruntime_error() -> None:
    """Show error dialog and open download page for VC++ Runtime."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()

    messagebox.showerror(
        "Visual C++ Runtime Required",
        "CLD requires Microsoft Visual C++ Redistributable to run.\n\n"
        "Click OK to open the download page.\n"
        "After installing, restart CLD.",
        type=messagebox.OK
    )

    root.destroy()

    # Open download page
    webbrowser.open(VCREDIST_URL)
    sys.exit(1)

# Global mutex handle (kept alive while running)
_mutex_handle = None


def _is_frozen() -> bool:
    """Check if running as frozen exe (PyInstaller or Nuitka)."""
    # PyInstaller sets sys.frozen
    if getattr(sys, "frozen", False):
        return True
    # Nuitka sets __compiled__ on __main__
    main_mod = sys.modules.get("__main__", object())
    return "__compiled__" in dir(main_mod)


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


def _find_cld_processes() -> list[int]:
    """Find all CLD daemon processes by command line."""
    pids = []
    try:
        # Use PowerShell to find python processes running cld.daemon
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -like '*cld.daemon*' -and $_.CommandLine -like '*python*' } | "
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
        logging.getLogger(__name__).debug("Failed to find CLD processes", exc_info=True)

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
        subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        # Wait for daemon to acquire mutex
        for _ in range(30):
            if is_daemon_running():
                logging.getLogger(__name__).info("Daemon started in background.")
                return True
            time.sleep(0.1)

        logging.getLogger(__name__).warning(
            "Daemon did not start within 3 seconds."
        )
        return False
    except Exception:
        logging.getLogger(__name__).exception("Failed to spawn background daemon")
        return False


def start_daemon(background: bool = False, enable_overlay: bool = False):
    """Start the daemon.

    Args:
        background: If True, daemonize the process.
        enable_overlay: If True, show GUI overlay.
    """
    if is_daemon_running():
        logging.getLogger(__name__).info("Daemon is already running.")
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

    try:
        daemon = STTDaemon(enable_overlay=enable_overlay)
        daemon.run()
    finally:
        _release_mutex()


def stop_daemon():
    """Stop the running daemon."""
    logger = logging.getLogger(__name__)

    if not is_daemon_running():
        logger.info("Daemon is not running.")
        return

    # Find and kill CLD processes
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
    # Check VC++ runtime before anything else
    if not check_vcruntime():
        show_vcruntime_error()
        return 1

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
