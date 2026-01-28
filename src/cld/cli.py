"""CLI entry point for CLD."""

from __future__ import annotations

import os
import sys

# Disable Intel Fortran console control handler BEFORE any imports
# This prevents "forrtl: error (200)" crash when console window is closed
os.environ.setdefault("FOR_DISABLE_CONSOLE_CTRL_HANDLER", "1")


def _hide_console_window():
    """Hide console window on Windows for non-debug mode.

    This prevents the brief console flash when launching from Explorer.
    Only hides if not in debug mode.
    """
    if sys.platform != "win32":
        return
    if "--debug" in sys.argv:
        return  # Keep console visible in debug mode

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


# Hide console immediately for non-debug mode to prevent blink
_hide_console_window()


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

            # Allocate console if none exists
            hwnd = kernel32.GetConsoleWindow()
            if not hwnd:
                kernel32.AllocConsole()
                hwnd = kernel32.GetConsoleWindow()

            if hwnd:
                # Show the console window
                user32 = ctypes.windll.user32
                SW_SHOW = 5
                user32.ShowWindow(hwnd, SW_SHOW)

                # Redirect stdout/stderr to the new console
                # Critical: must happen before any print statements
                sys.stdout = open('CONOUT$', 'w', encoding='utf-8')
                sys.stderr = open('CONOUT$', 'w', encoding='utf-8')

                # Install console control handler to prevent MKL crash on console close
                # Intel MKL's Fortran runtime crashes with error 200 when console closes
                # We intercept CTRL_CLOSE_EVENT (2), detach from console, and exit cleanly
                @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
                def console_handler(event):
                    if event == 2:  # CTRL_CLOSE_EVENT
                        # Detach from console FIRST to prevent MKL from seeing the close
                        kernel32.FreeConsole()
                        # Now exit cleanly - MKL won't crash because we're detached
                        import os
                        os._exit(0)
                    return False  # Let other handlers process other events

                # Keep reference to prevent garbage collection
                global _console_handler_ref
                _console_handler_ref = console_handler
                kernel32.SetConsoleCtrlHandler(console_handler, True)

                print("=== CLD Debug Console ===", flush=True)
        except Exception:
            pass

_early_debug_check()

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
