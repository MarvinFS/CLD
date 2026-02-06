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

        # Import version here to avoid circular imports
        from cld import __version__
        print(f"CLD version {__version__}")

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
        choices=["setup", "start", "stop", "status", "run", "daemon"],
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
