"""CLI entry point for CLD."""

from __future__ import annotations

import os
import sys

# Disable Intel Fortran console control handler BEFORE any imports
# This prevents "forrtl: error (200)" crash when console window is closed
os.environ.setdefault("FOR_DISABLE_CONSOLE_CTRL_HANDLER", "1")


def _needs_console() -> bool:
    """Check if we need a visible console (--version or --debug flags)."""
    return "--version" in sys.argv or "-V" in sys.argv or "--debug" in sys.argv


# Check for --version BEFORE other imports (needs console in windowed mode)
def _early_version_check():
    """Check for --version flag early and print version before imports.

    In PyInstaller windowed mode, there's no console to print to.
    Try to attach to parent console first (PowerShell/cmd), then allocate
    a new console as fallback (GUI launch). Only wait for keypress if we
    allocated a new console.
    """
    if "--version" in sys.argv or "-V" in sys.argv:
        attached = False
        if getattr(sys, 'frozen', False) and sys.platform == 'win32':
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32

                # Try to attach to parent console (PowerShell/cmd) first
                ATTACH_PARENT_PROCESS = -1
                attached = bool(kernel32.AttachConsole(ATTACH_PARENT_PROCESS))

                if not attached:
                    # No parent console (GUI launch) - create new one
                    kernel32.AllocConsole()

                # Redirect stdout/stderr to the console
                sys.stdout = open('CONOUT$', 'w', encoding='utf-8')
                sys.stderr = open('CONOUT$', 'w', encoding='utf-8')
            except Exception:
                pass

        # Import version here to avoid circular imports. Keep the format
        # identical to the non-frozen path below so scripts can scrape it
        # consistently regardless of how CLD was launched.
        from cld import __version__
        print(__version__)

        # Only wait for keypress if we allocated new console (not attached to parent)
        if getattr(sys, 'frozen', False) and sys.platform == 'win32':
            if not attached:
                print("\nPress Enter to exit...")
                try:
                    input()
                except Exception:
                    pass
        sys.exit(0)


_early_version_check()


# Check for --debug BEFORE other imports to enable console early
def _early_debug_check():
    """Check for --debug flag early and setup console before imports.

    Also installs a console control handler to gracefully handle console
    close events, preventing Intel MKL Fortran runtime crashes.
    """
    if sys.platform == "win32" and "--debug" in sys.argv:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32

            # Always allocate a new console for debug mode
            # This ensures we get a visible console even for windowed exe
            kernel32.AllocConsole()

            # Redirect stdout/stderr to the new console
            # Critical: must happen before any print statements
            sys.stdout = open('CONOUT$', 'w', encoding='utf-8')
            sys.stderr = open('CONOUT$', 'w', encoding='utf-8')

            # Install console control handler to prevent MKL crash on console close.
            # Intel MKL's Fortran runtime crashes with "forrtl: error (200)" when the
            # console window is closed. We intercept CTRL_CLOSE_EVENT (2), detach from
            # the console, and call os._exit(0) to bypass normal cleanup.
            #
            # INTENTIONAL TRADE-OFF: os._exit() skips atexit handlers and __del__
            # methods, but this is acceptable because:
            # 1. The MKL crash is worse (hangs/crashes the process)
            # 2. On console close, the user expects immediate termination anyway
            # 3. Critical cleanup (audio stream, PID file) happens on SIGTERM instead
            #
            # See: https://github.com/numpy/numpy/issues related to MKL on Windows
            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
            def console_handler(event):
                if event == 2:  # CTRL_CLOSE_EVENT
                    # Detach from console FIRST to prevent MKL from seeing the close
                    kernel32.FreeConsole()
                    # Exit immediately - MKL won't crash because we're detached
                    import os
                    os._exit(0)
                return False  # Let other handlers process other events

            # Keep reference to prevent garbage collection
            global _console_handler_ref
            _console_handler_ref = console_handler
            kernel32.SetConsoleCtrlHandler(console_handler, True)

            print("=== CLD Debug Console ===", flush=True)
        except Exception:
            # If console allocation fails, silently continue
            pass

_early_debug_check()


def _ensure_valid_std_handles() -> None:
    """Give a windowed (console=False) frozen launch valid std handles.

    When CLD.exe is started from a shortcut / double-click there is no
    console, so the process inherits invalid standard handles. Any later
    write to stdout/stderr - a logging call, a native lib's fprintf, or just
    a stream object being flushed by the garbage collector - then raises
    ``OSError [WinError 6] The handle is invalid``. In the background-daemon
    spawn path that surfaces (via ``logging``) as a ``SystemError`` that
    aborts ``_spawn_background``, so ``CLD.exe`` with no args appears to "not
    start" at all. Point any invalid fd among 0/1/2 at NUL and rebind the
    Python streams so every such write is a harmless no-op. Valid handles
    (e.g. a real redirect) are left untouched, and ``--debug`` / ``--version``
    are skipped because they set up their own console + streams.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    if _needs_console():
        return

    def _fd_ok(fd: int) -> bool:
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False

    devnull_fd = None
    try:
        for fd in (0, 1, 2):
            if _fd_ok(fd):
                continue
            if devnull_fd is None:
                devnull_fd = os.open(os.devnull, os.O_RDWR)
            try:
                os.dup2(devnull_fd, fd)
            except OSError:
                pass
    except OSError:
        pass
    finally:
        if devnull_fd is not None and devnull_fd > 2:
            try:
                os.close(devnull_fd)
            except OSError:
                pass

    def _stream_ok(stream) -> bool:
        if stream is None:
            return False
        try:
            stream.fileno()
            return True
        except Exception:
            return False

    try:
        if not _stream_ok(sys.stdin):
            sys.stdin = open(os.devnull, "r")
        if not _stream_ok(sys.stdout):
            sys.stdout = open(os.devnull, "w")
        if not _stream_ok(sys.stderr):
            sys.stderr = open(os.devnull, "w")
    except OSError:
        pass


_ensure_valid_std_handles()


def _hide_console_window():
    """Hide console window on Windows for non-debug mode.

    This prevents the brief console flash when launching from Explorer.
    Only hides if not in debug/version mode (those need the console visible).
    """
    if sys.platform != "win32":
        return
    if _needs_console():
        return  # Keep console visible for --debug and --version

    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32 = ctypes.windll.user32
            SW_HIDE = 0
            user32.ShowWindow(hwnd, SW_HIDE)
    except Exception:
        pass


# Hide console AFTER version/debug checks for non-debug mode
_hide_console_window()

import argparse
from typing import Sequence

from cld import __version__
from cld.daemon import main as daemon_main
from cld.setup import main as setup_main


def _emit(message: str, out_path: str | None) -> None:
    """Write to out_path (reliable from a windowed exe) or print to stdout."""
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(message)
            return
        except OSError:
            pass
    print(message)


def _run_transcribe(args: Sequence[str]) -> int:
    """Decode a WAV file with the configured engine and emit the text.

    Headless utility (also the frozen-exe smoke test): proves the engine's
    native stack loads and decodes without a microphone. Usage:
        cld transcribe <wav> [out.txt]
    Writes "OK engine=<e> ms=<n>\\n<text>" to out.txt (or stdout).
    """
    import time
    import wave
    import numpy as np
    from cld.config import Config
    from cld.engine_factory import build_engine

    if not args:
        print("usage: cld transcribe <wav> [out.txt]")
        return 2
    wav_path = args[0]
    out_path = args[1] if len(args) > 1 else None

    try:
        with wave.open(wav_path, "rb") as w:
            if w.getsampwidth() != 2:
                _emit(f"ERROR: expected 16-bit PCM, got {w.getsampwidth()*8}-bit", out_path)
                return 1
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
    except (OSError, wave.Error) as e:
        _emit(f"ERROR: cannot read wav: {e}", out_path)
        return 1

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    config = Config.load()
    engine = build_engine(config)
    if not engine.is_available():
        err = engine.get_last_error() if hasattr(engine, "get_last_error") else None
        _emit(f"ENGINE_UNAVAILABLE: {err}", out_path)
        return 1
    if not engine.load_model():
        err = engine.get_last_error() if hasattr(engine, "get_last_error") else None
        _emit(f"LOAD_FAILED: {err}", out_path)
        return 1
    t0 = time.time()
    text = engine.transcribe(audio, sr)
    ms = int((time.time() - t0) * 1000)
    _emit(f"OK engine={config.engine.type} ms={ms}\n{text}", out_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ClaudeCli-Dictate (CLD)")
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the CLD version and exit.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show console window for debugging (Windows).",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["setup", "start", "stop", "status", "run", "daemon", "transcribe"],
        default="daemon",
        help="Command to execute (default: daemon).",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to the underlying command.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Console already set up early by _early_debug_check() if --debug was passed

    if args.version:
        print(__version__)
        return 0

    if args.command == "setup":
        return setup_main(list(args.args))

    if args.command == "transcribe":
        return _run_transcribe(list(args.args))

    if args.command == "daemon":
        if not args.args:
            if args.debug:
                # Set debug mode environment variable for daemon logging
                os.environ["CLD_DEBUG_MODE"] = "1"
                # Debug mode: run in foreground with overlay so console stays open
                print("Debug mode: running in foreground with overlay", flush=True)
                return daemon_main(["run", "--overlay"])
            else:
                # Normal mode: auto-start in background with overlay
                return daemon_main(["start", "--background", "--overlay"])
        return daemon_main(list(args.args))

    return daemon_main([args.command, *args.args])


if __name__ == "__main__":
    raise SystemExit(main())
