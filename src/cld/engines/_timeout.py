"""Shared wall-clock timeout helper for STT engines.

Native inference calls (whisper.cpp, sherpa-onnx) release the GIL but cannot
be interrupted from Python. To still enforce a real wall-clock timeout we run
each call on a long-lived single-worker thread and wait on the future. On
timeout we abandon the stuck worker and swap in a fresh executor so the next
call doesn't queue behind it.

We deliberately do NOT use ``with ThreadPoolExecutor(...)``: its ``__exit__``
calls ``shutdown(wait=True)`` and would block until the stuck task finishes,
making the timeout meaningless.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

__all__ = ["TimeoutRunner", "FuturesTimeoutError"]


class TimeoutRunner:
    """Run callables on a single long-lived worker with a wall-clock timeout."""

    def __init__(self, thread_name_prefix: str = "cld-worker"):
        self._thread_name_prefix = thread_name_prefix
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    def _get_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix=self._thread_name_prefix
                )
            return self._executor

    def run(self, fn, timeout: float):
        """Run ``fn()`` and return its result.

        Raises ``FuturesTimeoutError`` if it doesn't finish within ``timeout``.
        On timeout the stuck worker is abandoned and the executor replaced.
        """
        executor = self._get_executor()
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()
            with self._lock:
                stuck = self._executor
                self._executor = None
                if stuck is not None:
                    stuck.shutdown(wait=False, cancel_futures=True)
            raise

    def shutdown(self) -> None:
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None
