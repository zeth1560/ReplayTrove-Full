"""Cross-process serialization for log writes (Windows Local mutex)."""

from __future__ import annotations

import contextlib
import sys
import threading
from typing import Iterator

_LOCAL_MUTEX_NAME = "Local\\ReplayTroveLogWrite"
_fallback_lock = threading.RLock()


@contextlib.contextmanager
def global_log_write_lock(*, timeout_ms: int = 15_000) -> Iterator[None]:
    """
    Serialize service file + timeline + index updates across processes (Windows).

    On non-Windows, uses an in-process lock only.
    """
    if sys.platform != "win32":
        with _fallback_lock:
            yield
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    h = kernel32.CreateMutexW(None, False, _LOCAL_MUTEX_NAME)
    if not h:
        yield
        return
    try:
        r = kernel32.WaitForSingleObject(h, timeout_ms)
        if r not in (0, 128):  # WAIT_OBJECT_0, WAIT_ABANDONED
            yield
            return
        yield
    finally:
        kernel32.ReleaseMutex(h)
        kernel32.CloseHandle(h)
