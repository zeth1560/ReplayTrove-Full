"""Standard JSONL record envelope for forensic / cross-service analysis."""

from __future__ import annotations

import json
import time
from typing import Any

STANDARD_TYPE_APPLICATION = "application_log"
STANDARD_TYPE_ENCODER_FLIGHT = "encoder_flight"
STANDARD_TYPE_SYSTEM_HEARTBEAT = "system_heartbeat"
STANDARD_TYPE_SCRIPT = "script"


def build_record(
    *,
    timestamp: str,
    level: str,
    service: str,
    event: str,
    message: str,
    correlation_id: str | None = None,
    session_id: str | None = None,
    clip_id: str | None = None,
    context: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    type: str = STANDARD_TYPE_APPLICATION,
) -> dict[str, Any]:
    """All keys present for stable parsing (nulls where unused)."""
    ctx = dict(context) if context else {}
    ctx.setdefault("observed_at_ns", time.time_ns())
    return {
        "timestamp": timestamp,
        "level": level,
        "service": service,
        "event": event,
        "message": message,
        "correlation_id": correlation_id,
        "session_id": session_id,
        "clip_id": clip_id,
        "context": ctx,
        "metrics": metrics if metrics is not None else {},
        "state": state if state is not None else {},
        "type": type,
    }


def dumps_record(rec: dict[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, default=str, separators=(",", ":"))
