"""Format logging.LogRecord and flight payloads into standard JSONL lines."""

from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timezone
from typing import Any

from replaytrove_logging.schema import (
    STANDARD_TYPE_APPLICATION,
    STANDARD_TYPE_ENCODER_FLIGHT,
    build_record,
    dumps_record,
)
from replaytrove_logging.session import get_session_id

_HOSTNAME = socket.gethostname()

_LOGRECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "msecs",
        "relativeCreated",
        "levelno",
        "levelname",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "process",
        "processName",
        "thread",
        "threadName",
        "message",
        "taskName",
    }
)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return repr(value)


def format_log_record_json(record: logging.LogRecord, *, service: str) -> str:
    """Single standard JSON line (no trailing newline)."""
    flight = getattr(record, "replaytrove_flight_event", None)
    if isinstance(flight, dict):
        ts = str(flight.get("ts") or datetime.fromtimestamp(record.created, timezone.utc).isoformat())
        lvl = str(flight.get("level", "INFO")).upper()
        if lvl in ("WARN", "WARNING"):
            lvl = "WARNING"
        ev = str(flight.get("event", "encoder_flight"))
        msg = str(flight.get("message", ""))
        st = {k: _json_safe(v) for k, v in flight.items()}
        rec = build_record(
            timestamp=ts,
            level=lvl,
            service=service,
            event=ev,
            message=msg,
            correlation_id=flight.get("correlation_id") if isinstance(flight.get("correlation_id"), str) else None,
            session_id=str(flight.get("run_id")) if flight.get("run_id") else get_session_id(),
            clip_id=str(flight["clip_id"]) if flight.get("clip_id") else None,
            context={"source_logger": "replaytrove.encoder.flight"},
            metrics={},
            state=st,
            type=STANDARD_TYPE_ENCODER_FLIGHT,
        )
        return dumps_record(rec)

    ts = datetime.fromtimestamp(record.created, timezone.utc).isoformat()
    msg = record.getMessage()
    structured = getattr(record, "structured", None)
    correlation_id = getattr(record, "rt_correlation_id", None)
    clip_id = getattr(record, "rt_clip_id", None)
    event = getattr(record, "rt_event", None) or "log"
    if isinstance(structured, dict):
        correlation_id = correlation_id or structured.get("correlation_id")
        if clip_id is None and structured.get("clip_id") is not None:
            clip_id = str(structured.get("clip_id"))
        if event == "log" and structured.get("event"):
            event = str(structured.get("event"))

    ctx: dict[str, Any] = {
        "hostname": _HOSTNAME,
        "pathname": record.pathname,
        "filename": record.filename,
        "module": record.module,
        "lineno": record.lineno,
        "funcName": record.funcName,
        "process": {"pid": record.process, "name": getattr(record, "processName", None)},
        "thread": {"ident": record.thread, "name": record.threadName},
        "source_logger": record.name,
    }
    if record.exc_info:
        ctx["exc_info"] = logging.Formatter().formatException(record.exc_info)

    metrics: dict[str, Any] = {}
    state: dict[str, Any] = {}
    if isinstance(structured, dict) and structured:
        state["structured"] = _json_safe(structured)

    extras = {
        k: v
        for k, v in record.__dict__.items()
        if k not in _LOGRECORD_ATTRS and not k.startswith("_")
    }
    extras.pop("replaytrove_flight_event", None)
    extras.pop("structured", None)
    if extras:
        state["logging_extra"] = _json_safe(extras)

    rec = build_record(
        timestamp=ts,
        level=record.levelname,
        service=service,
        event=str(event),
        message=msg,
        correlation_id=str(correlation_id) if correlation_id else None,
        session_id=get_session_id(),
        clip_id=str(clip_id) if clip_id else None,
        context=ctx,
        metrics=metrics,
        state=state,
        type=STANDARD_TYPE_APPLICATION,
    )
    return dumps_record(rec)
