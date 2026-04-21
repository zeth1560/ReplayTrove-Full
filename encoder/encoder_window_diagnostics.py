"""
Tk / Win32 window diagnostics and hardening for the encoder operator.

Hidden (background) mode uses Win32 extended styles so the host window is far
less likely to activate, appear in the taskbar, or jump in z-order if mapped.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("replaytrove.encoder.window")

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


def _get_window_long_ex(hwnd: int) -> int:
    user32 = ctypes.windll.user32
    try:
        return int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
    except AttributeError:
        return int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))


def _set_window_long_ex(hwnd: int, value: int) -> None:
    user32 = ctypes.windll.user32
    try:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, value)
    except AttributeError:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, value)


def win32_hwnd_snapshot(hwnd: int) -> dict[str, Any]:
    """Best-effort Win32 state (``hwnd`` from Tk ``winfo_id()`` on Windows)."""
    user32 = ctypes.windll.user32
    hwnd_i = int(hwnd)
    fg = int(user32.GetForegroundWindow())
    return {
        "win32_hwnd": hwnd_i,
        "win32_is_window": bool(user32.IsWindow(hwnd_i)),
        "win32_visible": bool(user32.IsWindowVisible(hwnd_i)),
        "win32_iconic": bool(user32.IsIconic(hwnd_i)),
        "win32_foreground_hwnd": fg,
        "encoder_is_foreground": bool(fg == hwnd_i),
    }


def apply_win32_noninteractive_host(root: Any) -> dict[str, Any]:
    """
    Mark the Tk toplevel as toolwindow + non-activating and push z-order to bottom
    without activation. Safe to call before ``withdraw`` so the HWND exists.
    """
    root.update_idletasks()
    hwnd = int(root.winfo_id())
    ex_before = _get_window_long_ex(hwnd)
    ex_after = ex_before | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    if ex_after != ex_before:
        _set_window_long_ex(hwnd, ex_after)
    ctypes.windll.user32.SetWindowPos(
        hwnd,
        HWND_BOTTOM,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )
    return {
        "hwnd": hwnd,
        "gwl_exstyle_before": ex_before,
        "gwl_exstyle_after": ex_after,
    }


def tk_window_report(root: Any) -> dict[str, Any]:
    import tkinter as tk

    try:
        wm = str(root.wm_state())
    except tk.TclError:
        wm = "tcl_error"
    try:
        viewable = bool(int(root.winfo_viewable()))
    except tk.TclError:
        viewable = False
    try:
        topmost = bool(root.wm_attributes("-topmost"))
    except tk.TclError:
        topmost = False
    return {
        "pid": os.getpid(),
        "tk_winfo_id": int(root.winfo_id()),
        "wm_state": wm,
        "winfo_viewable": viewable,
        "title": root.title(),
        "wm_topmost": topmost,
    }


def encoder_window_snapshot(root: Any) -> dict[str, Any]:
    r = tk_window_report(root)
    if sys.platform == "win32":
        try:
            r.update(win32_hwnd_snapshot(r["tk_winfo_id"]))
        except (OSError, OverflowError, ValueError):
            pass
    return r


def log_encoder_window_event(reason: str, root: Any, *, extra: dict[str, Any] | None = None) -> None:
    snap = encoder_window_snapshot(root)
    if extra:
        snap = {**snap, **extra}
    logger.info("encoder window event | reason=%s | %s", reason, snap)


def ensure_topmost_disabled(root: Any) -> None:
    """Encoder must never use topmost in production; log if something sets it."""
    try:
        root.wm_attributes("-topmost", False)
    except tk.TclError:
        pass
