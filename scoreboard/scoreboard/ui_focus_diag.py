"""Foreground / window-state diagnostics for scoreboard pilot (Windows-focused)."""

from __future__ import annotations

import logging
import os
from typing import Any

import tkinter as tk

_LOG = logging.getLogger(__name__)


def _root_hwnd(root: tk.Misc) -> int | None:
    try:
        return int(root.winfo_id())
    except (tk.TclError, ValueError, TypeError):
        return None


def foreground_hwnd() -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        _LOG.debug("foreground_hwnd failed", exc_info=True)
        return None


def window_title(hwnd: int | None, max_len: int = 256) -> str:
    if hwnd is None or hwnd == 0 or os.name != "nt":
        return ""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(max_len)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, max_len)
        return (buf.value or "").strip()
    except Exception:
        return ""


def window_pid(hwnd: int | None) -> int | None:
    if hwnd is None or hwnd == 0 or os.name != "nt":
        return None
    try:
        import ctypes

        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None
    except Exception:
        return None


def operator_foreground_ok(
    root: tk.Misc,
    recording_toplevel: tk.Misc | None,
    recording_ui_active: bool,
) -> tuple[bool, int | None, str, int | None]:
    """
    Whether the Windows foreground window is the scoreboard root or (when recording UI is
    active) the recording Toplevel — i.e. operator input is expected to route correctly.
    """
    fg = foreground_hwnd()
    title = window_title(fg)
    pid = window_pid(fg)
    rh = _root_hwnd(root)
    if fg is None or rh is None:
        return (True, fg, title, pid)
    if fg == rh:
        return (True, fg, title, pid)
    if recording_ui_active and recording_toplevel is not None:
        try:
            th = int(recording_toplevel.winfo_id())
            if fg == th:
                return (True, fg, title, pid)
        except (tk.TclError, ValueError, TypeError):
            pass
    return (False, fg, title, pid)


def root_wm_snapshot(root: tk.Misc) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        try:
            out["root_state"] = root.state()
        except tk.TclError:
            out["root_state"] = "?"
        try:
            out["viewable"] = bool(root.winfo_viewable())
        except tk.TclError:
            out["viewable"] = False
        try:
            out["mapped"] = int(root.winfo_viewable())
            _LOG.debug("ui_focus_diag fallback_used winfo_viewable")
        except Exception:
            out["mapped"] = 0
        try:
            out["fullscreen"] = bool(root.attributes("-fullscreen"))
        except tk.TclError:
            out["fullscreen"] = None
        try:
            out["topmost"] = bool(root.attributes("-topmost"))
        except tk.TclError:
            out["topmost"] = None
    except Exception:
        _LOG.debug("root_wm_snapshot failed", exc_info=True)
        out.setdefault("root_state", "?")
        out.setdefault("viewable", False)
        out.setdefault("mapped", 0)
        out.setdefault("fullscreen", None)
        out.setdefault("topmost", None)
    return out
