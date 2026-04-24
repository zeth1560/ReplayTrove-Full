"""Per-process session id for log correlation."""

from __future__ import annotations

import os
import uuid

_SESSION = os.environ.get("REPLAYTROVE_SESSION_ID", "").strip() or uuid.uuid4().hex[:20]


def get_session_id() -> str:
    return _SESSION
