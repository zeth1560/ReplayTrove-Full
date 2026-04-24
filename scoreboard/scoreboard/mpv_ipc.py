"""mpv JSON IPC over Windows named pipe (same as ``--input-ipc-server=\\\\.\\pipe\\mpv``)."""

from __future__ import annotations

import json
import logging
from typing import Any

_LOG = logging.getLogger(__name__)

DEFAULT_MPV_PIPE = r"\\.\pipe\mpv"
_MAX_LINE = 1_000_000


def _read_json_line(pipe: Any) -> dict[str, Any]:
    buf = bytearray()
    while len(buf) < _MAX_LINE:
        ch = pipe.read(1)
        if not ch:
            raise OSError("mpv IPC: connection closed before newline")
        buf += ch
        if ch == b"\n":
            break
    line = buf.decode("utf-8", errors="strict").strip()
    if not line:
        raise OSError("mpv IPC: empty response line")
    return json.loads(line)


def _send_request(pipe: Any, req: dict[str, Any]) -> dict[str, Any]:
    raw = (json.dumps(req, separators=(",", ":")) + "\n").encode("utf-8")
    pipe.write(raw)
    pipe.flush()
    resp = _read_json_line(pipe)
    err = resp.get("error")
    if err not in (None, "success"):
        raise OSError(f"mpv IPC error: {err!r} (request={req!r})")
    return resp


def _num(data: Any) -> float:
    if isinstance(data, bool):
        return float(data)
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, str):
        return float(data)
    raise TypeError(f"unexpected mpv property type: {type(data)!r}")


def run_mpv_action(action: str, *, pipe_path: str = DEFAULT_MPV_PIPE) -> None:
    """Run one control macro (matches repo ``scripts/{action}.ps1`` behavior)."""
    with open(pipe_path, "r+b", buffering=0) as pipe:
        if action == "mpv_pause":
            _send_request(pipe, {"command": ["cycle", "pause"]})
            paused = _send_request(pipe, {"command": ["get_property", "pause"]})["data"]
            label = "Paused" if paused in (True, "yes", "true", 1) else "Playing"
            _send_request(pipe, {"command": ["show-text", label, 2000]})
        elif action == "mpv_seek_forward_5":
            _send_request(pipe, {"command": ["seek", 5, "relative"]})
            _send_request(pipe, {"command": ["show-progress"]})
        elif action == "mpv_seek_back_5":
            _send_request(pipe, {"command": ["seek", -5, "relative"]})
            _send_request(pipe, {"command": ["show-progress"]})
        elif action == "mpv_speed_up":
            _send_request(pipe, {"command": ["add", "speed", 0.1]})
            sp = _num(_send_request(pipe, {"command": ["get_property", "speed"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Speed {sp:.2f}x", 3000]})
        elif action == "mpv_speed_down":
            _send_request(pipe, {"command": ["add", "speed", -0.1]})
            sp = _num(_send_request(pipe, {"command": ["get_property", "speed"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Speed {sp:.2f}x", 3000]})
        elif action == "mpv_speed_reset":
            sp = _num(_send_request(pipe, {"command": ["get_property", "speed"]})["data"])
            delta = 1.0 - sp
            if abs(delta) > 1e-6:
                _send_request(pipe, {"command": ["add", "speed", delta]})
            sp = _num(_send_request(pipe, {"command": ["get_property", "speed"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Speed {sp:.2f}x", 3000]})
        elif action == "mpv_zoom_in":
            _send_request(pipe, {"command": ["add", "video-zoom", 0.1]})
            z = _num(_send_request(pipe, {"command": ["get_property", "video-zoom"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Zoom {z:.2f}", 2500]})
        elif action == "mpv_zoom_out":
            _send_request(pipe, {"command": ["add", "video-zoom", -0.1]})
            z = _num(_send_request(pipe, {"command": ["get_property", "video-zoom"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Zoom {z:.2f}", 2500]})
        elif action == "mpv_pan_left":
            _send_request(pipe, {"command": ["add", "video-pan-x", -0.05]})
            px = _num(_send_request(pipe, {"command": ["get_property", "video-pan-x"]})["data"])
            py = _num(_send_request(pipe, {"command": ["get_property", "video-pan-y"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Pan x={px:.2f} y={py:.2f}", 2500]})
        elif action == "mpv_pan_right":
            _send_request(pipe, {"command": ["add", "video-pan-x", 0.05]})
            px = _num(_send_request(pipe, {"command": ["get_property", "video-pan-x"]})["data"])
            py = _num(_send_request(pipe, {"command": ["get_property", "video-pan-y"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Pan x={px:.2f} y={py:.2f}", 2500]})
        elif action == "mpv_pan_up":
            _send_request(pipe, {"command": ["add", "video-pan-y", -0.05]})
            px = _num(_send_request(pipe, {"command": ["get_property", "video-pan-x"]})["data"])
            py = _num(_send_request(pipe, {"command": ["get_property", "video-pan-y"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Pan x={px:.2f} y={py:.2f}", 2500]})
        elif action == "mpv_pan_down":
            _send_request(pipe, {"command": ["add", "video-pan-y", 0.05]})
            px = _num(_send_request(pipe, {"command": ["get_property", "video-pan-x"]})["data"])
            py = _num(_send_request(pipe, {"command": ["get_property", "video-pan-y"]})["data"])
            _send_request(pipe, {"command": ["show-text", f"Pan x={px:.2f} y={py:.2f}", 2500]})
        elif action == "mpv_pan_zoom_reset":
            z = _num(_send_request(pipe, {"command": ["get_property", "video-zoom"]})["data"])
            if abs(z) > 1e-6:
                _send_request(pipe, {"command": ["add", "video-zoom", -z]})
            px = _num(_send_request(pipe, {"command": ["get_property", "video-pan-x"]})["data"])
            if abs(px) > 1e-6:
                _send_request(pipe, {"command": ["add", "video-pan-x", -px]})
            py = _num(_send_request(pipe, {"command": ["get_property", "video-pan-y"]})["data"])
            if abs(py) > 1e-6:
                _send_request(pipe, {"command": ["add", "video-pan-y", -py]})
            z = _num(_send_request(pipe, {"command": ["get_property", "video-zoom"]})["data"])
            px = _num(_send_request(pipe, {"command": ["get_property", "video-pan-x"]})["data"])
            py = _num(_send_request(pipe, {"command": ["get_property", "video-pan-y"]})["data"])
            _send_request(
                pipe,
                {
                    "command": [
                        "show-text",
                        f"Pan/Zoom reset  z={z:.2f}  x={px:.2f}  y={py:.2f}",
                        3500,
                    ]
                },
            )
        elif action == "mpv_quit":
            _send_request(pipe, {"command": ["quit"]})
        else:
            raise ValueError(f"unknown mpv action: {action!r}")


def try_run_mpv_action(action: str, *, pipe_path: str = DEFAULT_MPV_PIPE) -> tuple[bool, str]:
    """Return (True, \"\") on success, (False, reason) on failure (for logging)."""
    try:
        run_mpv_action(action, pipe_path=pipe_path)
        return (True, "")
    except OSError as e:
        _LOG.debug("mpv_ipc failed action=%s", action, exc_info=True)
        return (False, str(e))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        _LOG.debug("mpv_ipc failed action=%s", action, exc_info=True)
        return (False, str(e))
